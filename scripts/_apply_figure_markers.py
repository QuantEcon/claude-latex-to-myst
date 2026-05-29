#!/usr/bin/env python3
"""Rewrite ``\\begin{figure}...\\end{figure}`` (LaTeX float) blocks in a .tex
file into FIGURE marker HTML comments that pandoc passes through verbatim
and ``postprocess.py`` later expands into MyST ``{figure}`` directives.

Closes #89/#90/#92/#93 by sidestepping pandoc's lossy HTML emission for
figure floats — same architectural pattern as the table-marker pipeline
(#51/#55). Pandoc never sees the figure body; the caption and sub-
captions are batch-converted from LaTeX → markdown by THIS script, then
stored in the marker payload alongside the structural fields (label,
image src, TikZ stem). ``resolve_figure_markers`` in
``transforms/figures_from_latex.py`` decodes and emits the directive.

Phase 1 scope: single-figure shapes only. Blocks containing
``\\begin{subfigure}`` are left alone and fall through to
``convert_html_figures`` (Phase 2 — issue #94).

Marker format::

    <!--FIGURE payload=BASE64-->

Usage:
    _apply_figure_markers.py TEX_FILE
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from transforms.figures_from_latex import (  # noqa: E402
    FigureSpec,
    encode_marker,
    find_figure_blocks,
    parse_figure_block,
)


# Same batch-conversion sentinel as ``_apply_table_markers.py``. Collect
# every caption + sub-caption across the whole file into one LaTeX
# input separated by ``<!--CELL_N-->`` markers, run pandoc once, split
# the output, and distribute markdown back into the per-figure
# FigureSpecs. Critically, this is the step that escapes the brackets
# of ``[[CITEP:X]]`` markers (already inserted by ``_apply_rewrites.py``)
# to ``\[\[CITEP:X\]\]`` form — which is what ``decode_natbib_markers``
# matches post-pandoc. Without this conversion the markers would leak
# into the rendered output (#92).
_CELL_SENTINEL_OUT_RE = re.compile(r'\\?<!--CELL_(\d+)--\\?>')
_PANDOC_ADJACENCY_ARTIFACT_RE = re.compile(r'`<!-- -->`\{=html\}')


def _pandoc_batch_convert(cells: list[str]) -> list[str]:
    """Convert a list of LaTeX cell-content strings to markdown in ONE
    pandoc invocation. Mirrors ``_apply_table_markers._pandoc_batch_convert``.

    Empty cells become ``\\mbox{}`` so pandoc still emits a paragraph
    for them and the sentinel-split stays unambiguous.

    Fallback: if pandoc fails or doesn't preserve the sentinels, return
    the original LaTeX cells unchanged — correctness over conversion.
    """
    if not cells:
        return []

    parts: list[str] = []
    for i, cell in enumerate(cells):
        parts.append(f'<!--CELL_{i}-->')
        # Prefix every cell with a LaTeX non-breaking space (``~``) so
        # pandoc doesn't mis-interpret a paragraph-leading ``(letter)``
        # as inline math — a known pandoc quirk where ``(a)`` at the
        # start of input is read as the LaTeX math ``\(a\)``. Common in
        # multi-panel sub-captions like ``(a) the unit ball …``. After
        # conversion the leading space is stripped by ``content.strip()``
        # below.
        content = cell.strip() or r'\mbox{}'
        parts.append('~' + content)
    latex_in = '\n\n'.join(parts) + '\n'

    try:
        result = subprocess.run(
            ['pandoc', '-f', 'latex', '-t', 'markdown', '--wrap=none'],
            input=latex_in,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(
            f'_apply_figure_markers: pandoc batch conversion failed '
            f'({type(e).__name__}); falling back to raw-LaTeX cells. '
            f'stderr: {getattr(e, "stderr", "")!r}',
            file=sys.stderr,
        )
        return list(cells)

    pieces = _CELL_SENTINEL_OUT_RE.split(result.stdout)
    if len(pieces) < 3:
        return list(cells)

    out_cells: list[str] = [''] * len(cells)
    for i in range(1, len(pieces), 2):
        try:
            idx = int(pieces[i])
        except (ValueError, IndexError):
            continue
        content = pieces[i + 1] if i + 1 < len(pieces) else ''
        content = content.strip()
        if content in (r'\mbox{}', ''):
            content = ''
        content = _PANDOC_ADJACENCY_ARTIFACT_RE.sub('', content)
        if 0 <= idx < len(out_cells):
            out_cells[idx] = content

    return out_cells


def _flatten_figure_text(spec: FigureSpec) -> list[str]:
    """Flatten a FigureSpec's caption + sub-captions into a single
    ordered list for batched pandoc conversion. Order must match
    ``_unflatten_figure_text``."""
    flat: list[str] = [spec.caption or '']
    flat.extend(spec.sub_captions)
    return flat


def _unflatten_figure_text(spec: FigureSpec, converted: list[str]) -> FigureSpec:
    """Apply ``converted`` (markdown) back to ``spec``. Order must match
    ``_flatten_figure_text``."""
    new_caption = converted[0] if spec.caption is not None else None
    if spec.caption is None and converted:
        # Slot 0 was empty (no caption) — skip the empty placeholder.
        pass
    n_sub = len(spec.sub_captions)
    new_subs = list(converted[1 : 1 + n_sub])
    return FigureSpec(
        name=spec.name,
        caption=new_caption,
        image_src=spec.image_src,
        width=spec.width,
        tikz_input=spec.tikz_input,
        sub_captions=new_subs,
        placement=spec.placement,
    )


def process_text(text: str) -> str:
    """Find all ``\\begin{figure}`` blocks, batch-convert their captions
    + sub-captions through pandoc, and replace each block with a marker.
    Mirrors ``_apply_table_markers.process_text``."""
    blocks = find_figure_blocks(text)
    if not blocks:
        return text

    specs: list[FigureSpec | None] = [
        parse_figure_block(body, placement) for _, _, body, placement in blocks
    ]

    # Collect captions + sub-captions into a single flat list for the
    # whole-file pandoc batch. Per-spec offsets so we can re-attach.
    flat_in: list[str] = []
    offsets: list[tuple[int, int]] = []
    for spec in specs:
        if spec is None:
            offsets.append((-1, 0))
            continue
        cells = _flatten_figure_text(spec)
        offsets.append((len(flat_in), len(cells)))
        flat_in.extend(cells)

    flat_out = _pandoc_batch_convert(flat_in)

    converted_specs: list[FigureSpec | None] = []
    for spec, (start, length) in zip(specs, offsets):
        if spec is None or start < 0:
            converted_specs.append(None)
            continue
        converted_specs.append(
            _unflatten_figure_text(spec, flat_out[start : start + length])
        )

    # Stream re-assembly in source order. Same blank-line wrapping as
    # ``_apply_table_markers`` so the marker sits on its own paragraph
    # — pandoc otherwise glues the marker to adjacent prose.
    out_parts: list[str] = []
    last_end = 0
    for (start, end, _body, _placement), spec in zip(blocks, converted_specs):
        out_parts.append(text[last_end:start])
        if spec is None:
            # Unhandled shape (subfigure, no parseable content) — leave
            # the original block in place. ``convert_html_figures`` will
            # take it post-pandoc as before.
            out_parts.append(text[start:end])
        else:
            out_parts.append(f'\n\n{encode_marker(spec)}\n\n')
        last_end = end
    out_parts.append(text[last_end:])
    return ''.join(out_parts)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_figure_markers.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
