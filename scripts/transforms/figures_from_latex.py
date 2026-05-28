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
    (Phase 1 bails on subfigure blocks; ``convert_html_figures`` handles
    those via the existing HTML path)."""
    if _SUBFIGURE_RE.search(body):
        return None  # Phase 2 — issue #94

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

    # \includegraphics{path} or \input{tikz/stem} — at most one in scope.
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


def find_figure_blocks(text: str) -> list[tuple[int, int, str, str | None]]:
    """Return ``[(start, end, body, placement), ...]`` for every
    ``\\begin{figure}[opt]?...\\end{figure}`` block in source order.
    Mirrors ``find_table_blocks``."""
    blocks: list[tuple[int, int, str, str | None]] = []
    for m in _FIGURE_BLOCK_RE.finditer(text):
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


def _emit_figure(spec: FigureSpec) -> str:
    """Emit a MyST ``{figure}`` directive from a FigureSpec (Phase 1)."""
    # Sub-captions come first, in source order, then main caption — same
    # convention as #91's convert_html_figures fix so the visible output
    # doesn't shift for the cases already covered by the HTML path.
    body_parts: list[str] = []
    for sub in spec.sub_captions:
        if sub.strip():
            body_parts.append(sub.strip())
    if spec.caption and spec.caption.strip():
        body_parts.append(spec.caption.strip())
    body = '\n\n'.join(body_parts)

    # Image source: a real raster/vector → ``{figure} path``. A TikZ
    # ``\input{tikz/stem}`` becomes the same admonition placeholder
    # shape ``convert_html_figures`` uses, so ``resolve_tikz_figures``
    # still resolves it via ``TIKZ_FIGURE_MAP``. No behavior change for
    # TIKZ users.
    if spec.image_src:
        path = spec.image_src
        if '/' not in path:
            path = 'figures/' + path
        lines = [f'```{{figure}} {path}']
        if spec.name:
            lines.append(f':name: {spec.name}')
        lines.append('')
        if body:
            lines.append(body)
        lines.append('```')
        return '\n'.join(lines)

    if spec.tikz_input:
        # Admonition placeholder — resolve_tikz_figures will substitute
        # the real figure from TIKZ_FIGURE_MAP keyed by spec.name.
        lines = ['```{admonition} Figure (TikZ — needs manual conversion)']
        if spec.name:
            lines.append(f':name: {spec.name}')
        lines.append('')
        lines.append(body or '*(TikZ diagram — needs manual conversion)*')
        lines.append('```')
        return '\n'.join(lines)

    # Caption / sub-captions only, no image — emit a labelled admonition
    # so the content survives.
    lines = ['```{admonition} Figure']
    if spec.name:
        lines.append(f':name: {spec.name}')
    lines.append('')
    lines.append(body or '*(figure body)*')
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
        try:
            spec = decode_marker(m.group(1))
        except (ValueError, json.JSONDecodeError):
            # Defensive: leave the marker in place so a human can see
            # something went wrong, rather than silently dropping the
            # figure.
            return m.group(0)
        return _emit_figure(spec)

    return _MARKER_RE.sub(repl, text)
