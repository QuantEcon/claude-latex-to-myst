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

import base64
import json
import re
from dataclasses import asdict, dataclass, field

from ._helpers import convert_label_colons


@dataclass
class FigureSpec:
    """The structural fields of a ``\\begin{figure}`` block we care about
    for MyST emission. Caption and sub-captions are MARKDOWN at
    marker-write time (post-batched-pandoc). All other fields are
    extracted verbatim from the LaTeX source."""

    name: str | None = None            # \label{...} → MyST anchor (colon→hyphen)
    caption: str | None = None         # \caption{...} body, markdown form
    image_src: str | None = None       # \includegraphics{path}, or None
    tikz_input: str | None = None      # \input{tikz/stem} → "stem", or None
    sub_captions: list[str] = field(default_factory=list)
    placement: str | None = None       # [ht]?  preserved for fidelity


# ── source parsing (called pre-pandoc by _apply_figure_markers.py) ─────────


_FIGURE_BLOCK_RE = re.compile(
    r'\\begin\{figure\}(?P<opt>\[[^\]]*\])?(?P<body>.*?)\\end\{figure\}',
    re.DOTALL,
)
_SUBFIGURE_RE = re.compile(r'\\begin\{subfigure\}')
_LABEL_RE = re.compile(r'\\label\{([^}]+)\}')
_INCLUDEGRAPHICS_RE = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}')
_TIKZ_INPUT_RE = re.compile(r'\\input\{tikz/([^}]+?)(?:\.tex)?\}')
_FOOTNOTESIZE_RE = re.compile(r'\{\\footnotesize\b')


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


def parse_figure_block(body: str, placement: str | None) -> FigureSpec | None:
    """Parse a ``\\begin{figure}[opt]?...\\end{figure}`` body into a
    FigureSpec. Returns ``None`` to signal "leave this block alone"
    (Phase 1 bails on subfigure blocks and multi-image blocks;
    ``convert_html_figures`` handles those via the existing HTML path)."""
    if _SUBFIGURE_RE.search(body):
        return None  # Phase 2 — issue #94

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
        spec.caption = caption_text

    # \includegraphics{path} or \input{tikz/stem} — bail above
    # guarantees at most one of either.
    img_m = _INCLUDEGRAPHICS_RE.search(body)
    if img_m:
        spec.image_src = img_m.group(1)
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
    """Encode a ``FigureSpec`` as a single-line HTML-comment marker.

    Format::

        <!--FIGURE payload=BASE64-->

    where BASE64 is the base64 of JSON-encoded spec fields. Single-line
    so pandoc treats it as a self-contained block.
    """
    payload = base64.b64encode(
        json.dumps(asdict(spec), ensure_ascii=False).encode('utf-8')
    ).decode('ascii')
    return f'<!--FIGURE payload={payload}-->'


def decode_marker(payload_b64: str) -> FigureSpec:
    """Decode a base64 payload back into a FigureSpec."""
    data = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
    return FigureSpec(
        name=data.get('name'),
        caption=data.get('caption'),
        image_src=data.get('image_src'),
        tikz_input=data.get('tikz_input'),
        sub_captions=list(data.get('sub_captions') or []),
        placement=data.get('placement'),
    )


# ── post-pandoc resolver ────────────────────────────────────────────────────


def _lookup_tikz_map(name: str | None) -> tuple[str, str | None] | None:
    """Look up ``name`` in the per-project ``TIKZ_FIGURE_MAP`` (populated
    from the consumer book's ``tikz_overrides.py``). Returns
    ``(path, caption_override)`` or None.

    Late-imported from ``postprocess`` to avoid the load-time circular
    per the state-coupling pattern used in ``figures.py``. The map is a
    runtime concern: consumer books call ``apply_config`` which
    populates ``postprocess.TIKZ_FIGURE_MAP``; the parsers / emitters
    here read it at call time.
    """
    if not name:
        return None
    try:
        import postprocess as pp
    except Exception:
        return None
    entry = pp.TIKZ_FIGURE_MAP.get(name)
    return entry


def _emit_figure(spec: FigureSpec) -> str:
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
                               cap_body: str) -> str:
        lines = [f'```{{figure}} {path}']
        if name:
            lines.append(f':name: {name}')
        lines.append('')
        if cap_body:
            lines.append(cap_body)
        lines.append('```')
        return '\n'.join(lines)

    # Priority 1: ``\includegraphics`` literal path from source. Mirror
    # ``figures.make_figure`` — when the source path has no directory
    # component, prepend ``figures/`` (the canonical asset folder).
    # This is source-side path completion; only applies to author-
    # written paths, NOT to map entries.
    if spec.image_src:
        path = spec.image_src
        if '/' not in path:
            path = 'figures/' + path
        return _emit_figure_directive(path, spec.name, body)

    # Priority 2: TIKZ_FIGURE_MAP lookup by label. Covers both inline
    # ``\begin{tikzpicture}`` bodies and ``\input{tikz/stem}`` references
    # — the consumer book's tikz_overrides.py decides the mapping. Emit
    # the mapped path **verbatim**: it's a consumer-controlled override
    # and the legacy ``resolve_tikz_figures`` emits it verbatim (no
    # ``figures/`` prefix). Adding a prefix would silently misroute any
    # entry that uses a bare filename or a non-``figures/`` root
    # (caught by Copilot review on PR #97).
    mapped = _lookup_tikz_map(spec.name)
    if mapped is not None:
        mapped_path, caption_override = mapped
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


def resolve_figure_markers(text: str) -> str:
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
            return _emit_figure(spec)
        except Exception:
            return m.group(0)

    return _MARKER_RE.sub(repl, text)
