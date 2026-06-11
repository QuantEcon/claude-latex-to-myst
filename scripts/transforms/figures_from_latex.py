"""Figure marker preprocessor / resolver — Phase 1.

Mirrors the table-marker pattern (``tables_from_latex.py`` + ``_apply_table_markers.py``).
Closes the pandoc-figure-HTML-emission bug class (#89/#90/#92/#93) by
extracting ``\\begin{figure}`` floats pre-pandoc into HTML-comment markers
with the structure base64-encoded inside, then decoding post-pandoc into
``{figure}`` directives. Pandoc never sees the figure body, so its HTML
emission quirks can't drop / mangle anything.

**Phase 1 scope** (this module):
- Single-figure shapes: ``\\begin{figure}`` with at most one
  ``\\includegraphics`` or ``\\input{tikz/...}``.
- Bails on blocks containing ``\\begin{subfigure}`` (Phase 2 — issue #94).

Caption and sub-captions are batch-converted from LaTeX → markdown by
``_apply_figure_markers.py`` (same ``_pandoc_batch_convert`` pattern as
tables). The conversion escapes brackets, which is what makes the
post-pandoc ``decode_natbib_markers`` regex (``\\\\[\\\\[CITEP:X\\\\]\\\\]``)
work — without that escape pass, ``[[CITEP:X]]`` (from the
``_apply_rewrites`` natbib pre-rewrite) would leak as literal text in the
output (#92).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from conversion_context import current_context
from ._helpers import (
    complete_image_path,
    convert_label_colons,
    tikz_map_entry,
)
from ._markers import decode_payload, encode_payload


@dataclass
class FigureSpec:
    """The structural fields of a ``\\begin{figure}`` block we care about
    for MyST emission. Caption and sub-captions are MARKDOWN at
    marker-write time (post-batched-pandoc). All other fields are
    extracted verbatim from the LaTeX source."""

    name: str | None = None            # \label{...} → MyST anchor (colon→hyphen)
    caption: str | None = None         # \caption{...} body, markdown form
    image_src: str | None = None       # \includegraphics{path}, or None
    width: str | None = None           # \includegraphics[width=…] → MyST :width:
    tikz_input: str | None = None      # \input{tikz/stem} → "stem", or None
    sub_captions: list[str] = field(default_factory=list)
    placement: str | None = None       # [ht]?  preserved for fidelity
    # ``\begin{subfigure}`` panels (#94). Non-empty only for a subfigure
    # float whose every panel is a plain ``\includegraphics`` (the
    # fully-modelled shape — scalebox/input/tikz panels bail to the HTML
    # path). Each item: ``{name, caption, image_src, width}``. When set,
    # ``_emit_figure`` emits one ``{figure}`` per panel.
    subfigures: list[dict] = field(default_factory=list)


# ── source parsing (called pre-pandoc by _apply_figure_markers.py) ─────────


_FIGURE_BLOCK_RE = re.compile(
    r'\\begin\{figure\}(?P<opt>\[[^\]]*\])?(?P<body>.*?)\\end\{figure\}',
    re.DOTALL,
)
_SUBFIGURE_RE = re.compile(r'\\begin\{subfigure\}')
# A whole ``\begin{subfigure}[pos]{width} … \end{subfigure}`` panel. The
# ``[pos]`` and ``{width}`` args are optional/consumed; group(1) is the body.
_SUBFIGURE_BLOCK_RE = re.compile(
    r'\\begin\{subfigure\}(?:\[[^\]]*\])?(?:\{[^}]*\})?(.*?)\\end\{subfigure\}',
    re.DOTALL,
)
_TIKZPICTURE_RE = re.compile(r'\\begin\{tikzpicture\}')
# A whole ``\begin{tikzpicture}…\end{tikzpicture}`` region — stripped before
# caption/label extraction so tikz node text isn't scooped (#98 #3).
_TIKZPICTURE_BLOCK_RE = re.compile(
    r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', re.DOTALL
)
_LABEL_RE = re.compile(r'\\label\{([^}]+)\}')
# group(1) = the optional ``[opts]`` (or None), group(2) = the ``{path}``.
# ``\s*`` between them tolerates an ``\includegraphics[…]`` whose ``{path}``
# sits on the next line (#98 #4 — dp1 ``f-finite_lq_1``).
_INCLUDEGRAPHICS_RE = re.compile(r'\\includegraphics(\[[^\]]*\])?\s*\{([^}]+)\}')
_TIKZ_INPUT_RE = re.compile(r'\\input\{tikz/([^}]+?)(?:\.tex)?\}')
_FOOTNOTESIZE_RE = re.compile(r'\{\\footnotesize\b')


def _convert_includegraphics_width(opt: str | None) -> str | None:
    """Convert the ``width=`` value of an ``\\includegraphics`` option
    string to a MyST ``:width:`` value, matching pandoc's LaTeX→Markdown
    behaviour (``0.95\\textwidth`` → ``95%``).

    - ``<coef>\\textwidth`` / ``\\linewidth`` / ``\\columnwidth`` /
      ``\\paperwidth`` → ``<coef*100>%`` (e.g. ``0.8\\linewidth`` → ``80%``).
    - a bare ``\\textwidth`` (implied coefficient 1.0) → ``100%``.
    - an absolute length (``3cm``, ``200pt``, ``300px``) → emitted verbatim.

    Returns ``None`` when there is no ``width=`` key. This restores the
    ``:width:`` the marker path dropped (#98 #1) — the old
    ``figures.convert_figures`` path received the already-converted
    percentage from pandoc; the marker path bypasses pandoc for the figure
    body, so the conversion is reproduced here.
    """
    if not opt:
        return None
    m = re.search(r'\bwidth\s*=\s*([^,\]]+)', opt)
    if not m:
        return None
    val = m.group(1).strip()
    rel = re.fullmatch(
        r'([0-9]*\.?[0-9]+)\s*\\(?:text|line|column|paper)width', val
    )
    if rel:
        pct = float(rel.group(1)) * 100
        return f'{pct:g}%'
    if re.fullmatch(r'\\(?:text|line|column|paper)width', val):
        return '100%'
    return val


def _find_balanced_brace(s: str, start: int) -> int:
    """Return index just past the closing ``}`` that pairs with the
    opening ``{`` at ``s[start]``. Returns -1 on malformed input."""
    if start >= len(s) or s[start] != '{':
        return -1
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            # Skip escaped char (e.g. ``\{``, ``\}``).
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _extract_caption(body: str) -> tuple[str | None, tuple[int, int] | None]:
    """Find ``\\caption{...}`` and return ``(arg_text, (start, end))`` of
    the whole construct. Returns ``(None, None)`` if no caption found.
    Brace-balanced — handles captions with inline ``\\citet{X}`` etc.
    """
    m = re.search(r'\\caption\b\s*', body)
    if not m:
        return None, None
    brace_start = m.end()
    if brace_start >= len(body) or body[brace_start] != '{':
        return None, None
    end = _find_balanced_brace(body, brace_start)
    if end < 0:
        return None, None
    return body[brace_start + 1 : end - 1], (m.start(), end)


def _extract_footnotesize_subcaptions(body: str) -> list[str]:
    """Find all ``{\\footnotesize ...}`` groups (with balanced braces) and
    return their inner content in source order. Covers both the bare
    case (between ``\\end{tikzpicture}`` and ``\\caption{}`` — #93) and
    the wrapped case (inside ``\\begin{minipage}`` — #90)."""
    out: list[str] = []
    for m in _FOOTNOTESIZE_RE.finditer(body):
        brace_start = m.start()  # position of `{`
        end = _find_balanced_brace(body, brace_start)
        if end < 0:
            continue
        # Strip the leading ``\footnotesize`` keyword + optional whitespace.
        inner = body[brace_start + 1 : end - 1]
        inner = re.sub(r'^\\footnotesize\s*', '', inner)
        inner = inner.strip()
        if inner:
            out.append(inner)
    return out


def _parse_subfigures(body: str) -> list[dict] | None:
    """Parse every ``\\begin{subfigure}`` panel into ``{name, caption,
    image_src, width}`` dicts (#94). Returns ``None`` — bail for the whole
    float — if ANY panel is not a plain ``\\includegraphics`` (e.g. dp1's
    ``\\scalebox{\\input{…pdf_t}}`` panels, or a raw ``tikzpicture`` panel):
    those need the consumer's TIKZ map / a render the marker path can't model,
    so they fall through to ``convert_html_figures`` exactly as before. This
    is the same "bail unless fully modelled" stance as the figure/tikz bails.
    """
    subs: list[dict] = []
    for m in _SUBFIGURE_BLOCK_RE.finditer(body):
        panel = m.group(1)
        img_m = _INCLUDEGRAPHICS_RE.search(panel)
        if not img_m:
            return None  # panel has no plain \includegraphics — bail
        cap, _ = _extract_caption(panel)
        if cap is not None:
            cap = _LABEL_RE.sub('', cap).strip() or None
        label_m = _LABEL_RE.search(panel)
        subs.append({
            'name': convert_label_colons(label_m.group(1)) if label_m else None,
            'caption': cap,
            'image_src': img_m.group(2),
            'width': _convert_includegraphics_width(img_m.group(1)),
        })
    return subs or None


def parse_figure_block(body: str, placement: str | None) -> FigureSpec | None:
    """Parse a ``\\begin{figure}[opt]?...\\end{figure}`` body into a
    FigureSpec. Returns ``None`` to signal "leave this block alone" —
    ``convert_html_figures`` handles those via the existing HTML path."""
    if _SUBFIGURE_RE.search(body):
        # #94: a subfigure float whose every panel is a plain
        # ``\includegraphics`` is fully modelled — emit one ``{figure}`` per
        # panel. Mixed shapes (scalebox/input/tikz panels) bail (None).
        subs = _parse_subfigures(body)
        if subs is None:
            return None
        spec = FigureSpec(placement=placement, subfigures=subs)
        # Outer label / caption: search the body with the panels removed so a
        # panel's own \label/\caption can't be mistaken for the float's.
        outer = _SUBFIGURE_BLOCK_RE.sub('', body)
        outer_label = _LABEL_RE.search(outer)
        if outer_label:
            spec.name = convert_label_colons(outer_label.group(1))
        outer_cap, _ = _extract_caption(outer)
        if outer_cap is not None:
            spec.caption = _LABEL_RE.sub('', outer_cap).strip() or None
        return spec

    # A ``\begin{figure}`` wrapping a raw ``\begin{tikzpicture}``: the tikz
    # BODY can't be modelled (it's rendered via the consumer's
    # ``TIKZ_FIGURE_MAP`` override post-pandoc — `_emit_figure` does the
    # lookup, since the preprocessor can't see the map). But the CAPTION can
    # be — and pandoc's HTML figcaption FLATTENS its math
    # (``$\theta_0$`` → ``<span class=math><sub>…``→ unicode ``θ0``), losing
    # fidelity across DL's 78 inline-tikz figures. So extract label + caption
    # from the body with the tikzpicture region REMOVED first — that strip is
    # what stops ``_extract_footnotesize_subcaptions`` scooping the tikz
    # ``{\footnotesize …}`` node labels as sub-captions (the #98 #3 bug the
    # old unconditional bail avoided). The batch-pandoc caption conversion in
    # ``_apply_figure_markers`` then preserves the math. No image/tikz_input
    # is set, so ``_emit_figure`` resolves via the override (mapped SVG +
    # math caption) or, with no override, falls back to a caption admonition.
    if _TIKZPICTURE_RE.search(body):
        outer = _TIKZPICTURE_BLOCK_RE.sub('', body)
        spec = FigureSpec(placement=placement)
        label_m = _LABEL_RE.search(outer)
        if label_m:
            spec.name = convert_label_colons(label_m.group(1))
        cap, _ = _extract_caption(outer)
        if cap is not None:
            spec.caption = _LABEL_RE.sub('', cap).strip() or None
        # Legitimate ``{\footnotesize (a) …}`` sub-panel captions live OUTSIDE
        # the tikzpicture (between/after panels); the tikz NODE labels lived
        # inside it and were just stripped — so extracting from ``outer`` here
        # recovers the real sub-captions (multi-panel figures, e.g. DL's
        # volume-ratio figure) without re-introducing the #98 #3 node scoop.
        spec.sub_captions = _extract_footnotesize_subcaptions(outer)
        # Nothing to carry (no label, no caption, no sub-captions) ⇒ leave it
        # for the HTML path exactly as before — marker-izing gains nothing.
        if not spec.name and not spec.caption and not spec.sub_captions:
            return None
        return spec

    # Phase 1 is single-figure scope. Multi-image / multi-tikz layouts
    # (side-by-side panels without ``\begin{subfigure}``) would silently
    # drop all but the first image if we proceeded — so bail and let
    # the existing HTML path handle them (caught by Copilot review on
    # PR #95).
    n_images = len(_INCLUDEGRAPHICS_RE.findall(body))
    n_tikz = len(_TIKZ_INPUT_RE.findall(body))
    if n_images + n_tikz > 1:
        return None

    spec = FigureSpec(placement=placement)

    # \label{...} — first match wins (multi-label rare; issue #10 handles
    # it via the HTML path which we leave intact for now).
    label_m = _LABEL_RE.search(body)
    if label_m:
        spec.name = convert_label_colons(label_m.group(1))

    # \caption{...} — verbatim LaTeX (with natbib pre-rewrites already
    # applied by _apply_rewrites.py upstream). Will be batch-converted
    # to markdown by _apply_figure_markers.py before being stored in
    # the spec.
    caption_text, _span = _extract_caption(body)
    if caption_text is not None:
        # Captions routinely embed their own \label (the LaTeX idiom
        # ``\caption{\label{fig:x} Text}``). The label is captured
        # separately as ``spec.name`` above; leaving it in the caption
        # makes pandoc emit a ``[]{#…}`` span plus a stray leading space
        # that survives into the rendered caption (#98 #2). Strip every
        # ``\label`` here, at the assembly point, before the batch pandoc
        # pass ever sees it.
        caption_text = _LABEL_RE.sub('', caption_text).strip()
        spec.caption = caption_text or None

    # \includegraphics[opts]{path} or \input{tikz/stem} — bail above
    # guarantees at most one of either. group(2) is the path; group(1) the
    # optional ``[opts]`` we mine for ``width=`` (#98 #1).
    img_m = _INCLUDEGRAPHICS_RE.search(body)
    if img_m:
        spec.image_src = img_m.group(2)
        spec.width = _convert_includegraphics_width(img_m.group(1))
    else:
        tikz_m = _TIKZ_INPUT_RE.search(body)
        if tikz_m:
            spec.tikz_input = tikz_m.group(1)

    # {\footnotesize ...} sub-captions (#90, #93). Source order.
    spec.sub_captions = _extract_footnotesize_subcaptions(body)

    # If the block has neither an image source nor any text-bearing
    # content, there's nothing useful to emit — let the HTML path
    # handle it as a fallback (it'll emit an admonition placeholder).
    if not spec.image_src and not spec.tikz_input and not spec.caption \
            and not spec.sub_captions:
        return None

    return spec


def _starts_in_comment(text: str, pos: int) -> bool:
    """Return True if ``text[pos]`` sits in a LaTeX line-comment — the
    same physical line has an unescaped ``%`` before ``pos``. Same
    logic as ``tables_from_latex._starts_in_comment`` /
    ``_apply_listing_markers._starts_in_comment``."""
    line_start = text.rfind('\n', 0, pos) + 1
    i = line_start
    while i < pos:
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == '%':
            return True
        i += 1
    return False


def find_figure_blocks(text: str) -> list[tuple[int, int, str, str | None]]:
    """Return ``[(start, end, body, placement), ...]`` for every
    ``\\begin{figure}[opt]?...\\end{figure}`` block in source order.
    Mirrors ``find_table_blocks``.

    Skips commented-out blocks: a ``\\begin{figure}`` on a line that's
    been disabled with ``%`` must not be marker-ized — otherwise the
    marker would un-comment the figure and silently change semantics
    (caught by Copilot review on PR #95)."""
    blocks: list[tuple[int, int, str, str | None]] = []
    for m in _FIGURE_BLOCK_RE.finditer(text):
        if _starts_in_comment(text, m.start()):
            continue
        placement = m.group('opt')
        if placement is not None:
            placement = placement[1:-1]  # strip outer []
        blocks.append((m.start(), m.end(), m.group('body'), placement))
    return blocks


# ── marker encode / decode ──────────────────────────────────────────────────


def encode_marker(spec: FigureSpec) -> str:
    """Encode a ``FigureSpec`` as a single-line ``<!--FIGURE payload=…-->``
    marker (shared base64+JSON codec — ``transforms._markers``). Single-line
    so pandoc treats it as a self-contained block."""
    return encode_payload('FIGURE', asdict(spec))


def decode_marker(payload_b64: str) -> FigureSpec:
    """Decode a base64 payload back into a FigureSpec."""
    data = decode_payload(payload_b64)
    return FigureSpec(
        name=data.get('name'),
        caption=data.get('caption'),
        image_src=data.get('image_src'),
        width=data.get('width'),
        tikz_input=data.get('tikz_input'),
        sub_captions=list(data.get('sub_captions') or []),
        placement=data.get('placement'),
        subfigures=list(data.get('subfigures') or []),
    )


# ── post-pandoc resolver ────────────────────────────────────────────────────


def _lookup_tikz_map(
    name: str | None, ctx=None
) -> tuple[str, str | None, bool] | None:
    """Look up ``name`` in the per-project ``ctx.tikz_figure_map`` (populated
    from the consumer book's overrides file). Returns the normalised
    ``(path, caption_override, per_subfigure)`` triple or None — entries
    may be 2-tuples or carry the ``'per-subfigure'`` opt-out tag (#75).

    The map is a runtime concern: consumer books call ``apply_config`` then
    ``load_overrides`` which populate the context; the parsers / emitters
    here read it at call time. ``ctx`` defaults to the current context.
    """
    if not name:
        return None
    ctx = ctx if ctx is not None else current_context()
    entry = ctx.tikz_figure_map.get(name)
    return tikz_map_entry(entry) if entry is not None else None


def _figure_ext_map(ctx=None) -> dict:
    """The current context's figure stem→filename map (#104)."""
    ctx = ctx if ctx is not None else current_context()
    return ctx.figure_ext_map


def _emit_figure(spec: FigureSpec, ctx=None) -> str:
    """Emit a MyST ``{figure}`` directive from a FigureSpec (Phase 1).

    Image-source resolution priority:

    1. ``spec.image_src`` (an ``\\includegraphics{path}`` literal) →
       emit ``{figure} path`` directly. The simple, common case.
    2. ``TIKZ_FIGURE_MAP[spec.name]`` → emit ``{figure} <mapped_path>``.
       Covers two distinct shapes that share the same lookup mechanism:
       * inline ``\\begin{tikzpicture}…\\end{tikzpicture}`` bodies that
         the consumer book pre-renders as SVG and maps via label
         (the dominant DL-book case — 78 figures);
       * ``\\input{tikz/stem}`` references where the consumer book
         supplies the rendered output (the old TIKZ admonition →
         ``resolve_tikz_figures`` flow).
    3. Otherwise — no image source and no map entry → emit a labelled
       admonition so the caption / sub-captions survive.

    The map's ``caption_override`` (when set) replaces the extracted
    caption body. This mirrors ``resolve_tikz_figures``: a consumer
    that wants a different caption than what's in the source uses the
    map's second tuple slot.

    Closes #96: prior version emitted a generic admonition for
    cases 2 and 3 (no map lookup), losing 78 figure images in DL R14.
    """
    body_parts: list[str] = []
    for sub in spec.sub_captions:
        if sub.strip():
            body_parts.append(sub.strip())
    if spec.caption and spec.caption.strip():
        body_parts.append(spec.caption.strip())
    body = '\n\n'.join(body_parts)

    def _emit_figure_directive(path: str, name: str | None,
                               cap_body: str, width: str | None = None) -> str:
        lines = [f'```{{figure}} {path}']
        if name:
            lines.append(f':name: {name}')
        # ``:name:`` then ``:width:`` — matches the option order the legacy
        # ``figures.convert_figures`` emitter used (#98 #1).
        if width:
            lines.append(f':width: {width}')
        lines.append('')
        if cap_body:
            lines.append(cap_body)
        lines.append('```')
        return '\n'.join(lines)

    # #94 subfigure float: one ``{figure}`` per panel. The outer label goes
    # to the first panel; later unlabelled panels get a ``-b`` / ``-c`` suffix
    # (matching the legacy ``convert_html_figures`` nested-pattern semantics,
    # lesson 021). A panel's own ``\label`` wins when present. Panel width is
    # intentionally omitted — the source ``[width=\linewidth]`` is relative to
    # the (sub-page-width) panel, so a standalone ``:width: 100%`` would be
    # wrong; the legacy path dropped it too.
    if spec.subfigures:
        # An OUTER-label TIKZ_FIGURE_MAP override wins over panel expansion:
        # a consumer that maps the whole float to a single composite image
        # (dp1 ``f-du`` → ``du.svg``) means the individual panels are just
        # the pre-render source. The preprocessor can't see the map (#98 #3),
        # so this check lives here, post-pandoc, where the map is visible.
        # An entry tagged ``'per-subfigure'`` (#75) is not a composite —
        # skip the override and expand panels normally.
        mapped = _lookup_tikz_map(spec.name, ctx)
        if mapped is not None:
            mapped_path, caption_override, per_subfigure = mapped
            if not per_subfigure:
                return _emit_figure_directive(
                    mapped_path,
                    spec.name,
                    caption_override if caption_override else body,
                )
        parts: list[str] = []
        outer_used = False
        for i, sub in enumerate(spec.subfigures):
            name = sub.get('name')
            if not name and spec.name:
                if i == 0:
                    name, outer_used = spec.name, True
                else:
                    name = f'{spec.name}-{chr(ord("a") + i)}'
            path = sub.get('image_src') or ''
            if path:
                path = complete_image_path(path, _figure_ext_map(ctx))
            cap = (sub.get('caption') or '').strip()
            parts.append(_emit_figure_directive(path, name, cap))
        out = '\n'.join(parts)
        # If the float carried an outer \label that NO panel adopted (every
        # panel had its own \label), emit it as a target anchor before the
        # first panel so an outer-label reference (e.g. {numref}`f-outer`)
        # still resolves — the lesson-021 "parent label takes the first child
        # slot" rule. Without this the outer ref would dangle.
        if spec.name and not outer_used:
            out = f'({spec.name})=\n\n{out}'
        return out

    # Priority 1: ``\includegraphics`` literal path from source. Mirror
    # ``figures.make_figure`` — when the source path has no directory
    # component, prepend ``figures/`` (the canonical asset folder).
    # This is source-side path completion; only applies to author-
    # written paths, NOT to map entries.
    if spec.image_src:
        path = complete_image_path(spec.image_src, _figure_ext_map(ctx))
        return _emit_figure_directive(path, spec.name, body, spec.width)

    # Priority 2: TIKZ_FIGURE_MAP lookup by label. Covers both inline
    # ``\begin{tikzpicture}`` bodies and ``\input{tikz/stem}`` references
    # — the consumer book's tikz_overrides.py decides the mapping. Emit
    # the mapped path **verbatim**: it's a consumer-controlled override
    # and the legacy ``resolve_tikz_figures`` emits it verbatim (no
    # ``figures/`` prefix). Adding a prefix would silently misroute any
    # entry that uses a bare filename or a non-``figures/`` root
    # (caught by Copilot review on PR #97).
    mapped = _lookup_tikz_map(spec.name, ctx)
    if mapped is not None:
        mapped_path, caption_override, _ = mapped
        final_body = caption_override if caption_override else body
        return _emit_figure_directive(mapped_path, spec.name, final_body)

    # Fallback: no image source, no map entry. Emit a labelled
    # admonition so at least the caption / sub-caption content survives.
    # Two flavours:
    #   - ``\input{tikz/...}`` body but no map entry → "TikZ — needs
    #     manual conversion" wording (matches the legacy shape that
    #     ``resolve_tikz_figures`` recognises, so a downstream consumer
    #     that later adds a map entry can still pick this up).
    #   - no image / tikz at all → generic "Figure" admonition.
    if spec.tikz_input is not None:
        lines = ['```{admonition} Figure (TikZ — needs manual conversion)']
        placeholder = '*(TikZ diagram — needs manual conversion)*'
    else:
        lines = ['```{admonition} Figure']
        placeholder = '*(figure body)*'
    if spec.name:
        lines.append(f':name: {spec.name}')
    lines.append('')
    lines.append(body or placeholder)
    lines.append('```')
    return '\n'.join(lines)


# Pandoc escapes the surrounding ``<`` / ``>`` of the marker to ``\<`` /
# ``\>`` on LaTeX→Markdown — same form as the table marker decoder.
_MARKER_RE = re.compile(
    r'\\?<!--FIGURE\s+payload=([A-Za-z0-9+/=]+?)--\\?>',
    re.DOTALL,
)


def resolve_figure_markers(text: str, ctx=None) -> str:
    """Decode every ``<!--FIGURE payload=...-->`` marker in ``text`` into
    a ``{figure}`` directive."""
    def repl(m: re.Match) -> str:
        # Defensive: a corrupted payload (manual edit of the intermediate
        # file, partial copy-paste, future pandoc version that mangles the
        # marker) shouldn't crash the whole postprocess pipeline. Leave
        # the original marker in place on failure — the visible artefact
        # tells the author something went wrong without taking down the
        # build. Mirrors ``resolve_table_markers``'s broad-Exception
        # pattern (Copilot review on PR #95). ``base64.binascii.Error``
        # and ``UnicodeDecodeError`` are technically ValueError subclasses
        # but matching the table-marker shape future-proofs against
        # unanticipated failure modes.
        try:
            spec = decode_marker(m.group(1))
            return _emit_figure(spec, ctx)
        except Exception:
            return m.group(0)

    return _MARKER_RE.sub(repl, text)
