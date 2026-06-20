#!/usr/bin/env python3
r"""Rewrite a ``\begin{multicols}{N}`` wrapping a custom-label ``enumerate``
into a MULTICOLSGRID marker that ``postprocess.py`` expands into a MyST
``{grid}`` (#170 — the unfinished layout half of #111).

``multicols`` balances its items into ``N`` side-by-side columns; book-dp1 uses
that to pair math statements ``(a)–(d)`` with their property names. Dropped to a
single column (the ``ENV_SKIP`` default), every name ends up stacked below all
the statements. This preprocessor extracts the paired enumerate pre-pandoc,
batch-converts each item's content LaTeX→markdown (``~`` paren-guard on, so a
leading ``(a)`` isn't read as the math ``\(a\)`` — same quirk the figure
sub-captions hit), and stores the result in a marker; ``resolve_multicols_grid``
splits the items column-first and emits the grid.

Runs BEFORE ``_apply_rewrites.py`` so the ``{N}`` column count is still present
(``_apply_rewrites`` strips it for the non-grid ``multicols`` it leaves behind),
and before ``_apply_custom_label_enumerates.py`` so the paired enumerate is
still intact (a grid-ized enumerate is now inside the marker, so the flattener
correctly skips it). Only the fully-modelled paired shape is marker-ized; every
other ``multicols`` is left untouched for the existing path (see the bail audit
in ``transforms/multicols.parse_multicols_block``).

Marker format::

    <!--MULTICOLSGRID payload=BASE64-->

Usage:
    _apply_multicols_grid.py TEX_FILE
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from transforms._markers import pandoc_batch_convert, reassemble  # noqa: E402
from transforms.multicols import (  # noqa: E402
    encode_marker,
    find_multicols_blocks,
    parse_multicols_block,
    strip_remaining_multicols_args,
)


def process_text(text: str) -> str:
    """Replace every grid-eligible ``multicols`` block with a marker, then strip
    the column count from the rest (#111 behaviour, moved here from
    ``_apply_rewrites``). Mirrors the figure / table marker preprocessors."""
    blocks = find_multicols_blocks(text)
    if not blocks:
        return text

    # parse → (spec, raw item cells) per block; None for blocks we don't model.
    parsed = [parse_multicols_block(cols, body) for _, _, cols, body in blocks]

    # One pandoc batch over every item cell of every modelled block. Offsets
    # let us re-attach the converted markdown to each spec.
    flat_in: list[str] = []
    offsets: list[tuple[int, int]] = []
    for entry in parsed:
        if entry is None:
            offsets.append((-1, 0))
            continue
        _spec, cells = entry
        offsets.append((len(flat_in), len(cells)))
        flat_in.extend(cells)

    flat_out = pandoc_batch_convert(
        flat_in, paren_guard=True, caller='_apply_multicols_grid'
    )

    rendered: list[str | None] = []
    for entry, (start, length) in zip(parsed, offsets):
        if entry is None or start < 0:
            rendered.append(None)
            continue
        spec, _cells = entry
        spec.items = flat_out[start: start + length]
        rendered.append(encode_marker(spec))

    spans = [(start, end) for start, end, _cols, _body in blocks]
    text = reassemble(text, spans, rendered)
    # Non-grid multicols (wrapped tabulars, backmatter prose, …) keep the old
    # behaviour: strip the {N} count and hoist any [pre-text] (#111).
    return strip_remaining_multicols_args(text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_multicols_grid.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
