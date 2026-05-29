#!/usr/bin/env python3
"""Rewrite ``\\begin{figure}...\\end{figure}`` (LaTeX float) blocks in a .tex
file into FIGURE marker HTML comments that pandoc passes through verbatim
and ``postprocess.py`` later expands into MyST ``{figure}`` directives.

Closes #89/#90/#92/#93 by sidestepping pandoc's lossy HTML emission for
figure floats — same architectural pattern as the table-marker pipeline
(#51/#55), sharing the pandoc-batch scaffolding via ``transforms._markers``
(Phase 2). Pandoc never sees the figure body; the caption and sub-
captions are batch-converted from LaTeX → markdown by THIS script
(``pandoc_batch_convert``, with the ``~`` paren-guard enabled so a
sub-caption like ``(a) …`` isn't misread as math), then stored in the
marker payload alongside the structural fields (label, image src, TikZ
stem). ``resolve_figure_markers`` in ``transforms/figures_from_latex.py``
decodes and emits the directive.

Phase 1 scope: single-figure shapes only. Blocks containing
``\\begin{subfigure}`` are left alone and fall through to
``convert_html_figures`` (Phase 4 — issue #94). See the bail-predicate
audit in ``transforms/_markers.py``.

Marker format::

    <!--FIGURE payload=BASE64-->

Usage:
    _apply_figure_markers.py TEX_FILE
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from transforms._markers import pandoc_batch_convert, reassemble  # noqa: E402
from transforms.figures_from_latex import (  # noqa: E402
    FigureSpec,
    encode_marker,
    find_figure_blocks,
    parse_figure_block,
)


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
    Mirrors ``_apply_table_markers.process_text`` (shared base)."""
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

    # Figures enable the ``~`` paren-guard (multi-panel sub-captions like
    # ``(a) the unit ball …`` that pandoc would otherwise read as math).
    flat_out = pandoc_batch_convert(
        flat_in, paren_guard=True, caller='_apply_figure_markers'
    )

    converted_specs: list[FigureSpec | None] = []
    for spec, (start, length) in zip(specs, offsets):
        if spec is None or start < 0:
            converted_specs.append(None)
            continue
        converted_specs.append(
            _unflatten_figure_text(spec, flat_out[start : start + length])
        )

    # Stream re-assembly in source order (shared ``reassemble``): parsed
    # blocks become blank-line-wrapped markers; unhandled shapes (subfigure,
    # raw tikzpicture, multi-image — see the bail audit in _markers.py) are
    # left in place for ``convert_html_figures`` post-pandoc.
    spans = [(start, end) for start, end, _body, _placement in blocks]
    rendered = [encode_marker(spec) if spec is not None else None
                for spec in converted_specs]
    return reassemble(text, spans, rendered)


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
