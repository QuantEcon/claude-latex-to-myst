#!/usr/bin/env python3
"""Rewrite ``\\begin{table}...\\end{table}`` (LaTeX float) blocks in a .tex
file into TABLE marker HTML comments that pandoc passes through verbatim
and postprocess.py later expands into MyST ``{table}`` directives.

Closes #51 (Path C from PR #41). Motivation: pandoc's LaTeX reader emits
``simple_tables`` format for narrow tables and **collapses all interior
``\\hline`` separators**. We lose the LaTeX-side header row identity
before pandoc even produces output (verified in PR #41 investigation —
all three rule patterns ``\\hline\\hline...``, single ``\\hline``,
``\\toprule/\\midrule/\\bottomrule`` produce identical pandoc emit
with no interior separator). By extracting the block ourselves we keep
full structural fidelity.

Marker format (single-line HTML comment so pandoc treats it as a
self-contained block):

    <!--TABLE payload=BASE64-->

Payload is base64-encoded JSON ``{name, caption, colspec, header_rows,
body_rows}``. Cells and caption are MARKDOWN at marker-write time —
this preprocessor batches them through pandoc once per file before
writing markers (``pandoc_batch_convert`` from ``transforms._markers``,
the shared marker base — Phase 2). ``resolve_table_markers`` in
``postprocess.py`` decodes and emits MyST directives.

This is the table analogue of ``_apply_listing_markers.py`` and
``_apply_algorithm_markers.py``; it shares the pandoc-batch scaffolding
with ``_apply_figure_markers.py`` via ``transforms._markers``.

Usage:
    _apply_table_markers.py TEX_FILE
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import via path so this works as a script (run from preprocess.sh).
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Shared marker base (Phase 2). ``_pandoc_batch_convert`` is kept as a
# module-level alias because tests monkeypatch + call it by that name on
# this module (tests/test_tables_from_latex.py). Tables do NOT use the
# paren-guard (figures do), so the default ``paren_guard=False`` is correct.
from transforms._markers import (  # noqa: E402
    pandoc_batch_convert as _pandoc_batch_convert,
    reassemble,
)
from transforms.tables_from_latex import (  # noqa: E402
    TableSpec,
    encode_marker,
    find_table_blocks,
    parse_table_block,
)


def _flatten_table_cells(spec: TableSpec) -> list[str]:
    """Flatten a TableSpec's caption + all cells into a single ordered
    list — used for batched pandoc conversion. Order matches
    ``_unflatten_table_cells``."""
    flat: list[str] = []
    # Slot 0: caption (or '' if uncaptioned).
    flat.append(spec.caption or '')
    for row in spec.header_rows:
        flat.extend(row)
    for row in spec.body_rows:
        flat.extend(row)
    return flat


def _unflatten_table_cells(spec: TableSpec, converted: list[str]) -> TableSpec:
    """Apply ``converted`` (markdown) back to ``spec``, returning a new
    TableSpec with markdown cells in place of raw LaTeX. Order must
    match ``_flatten_table_cells``."""
    idx = 0
    new_caption = converted[idx] if spec.caption is not None else None
    if spec.caption is None:
        # Skip the caption slot even though it's empty.
        pass
    idx += 1

    new_header_rows: list[list[str]] = []
    for row in spec.header_rows:
        new_header_rows.append(converted[idx : idx + len(row)])
        idx += len(row)

    new_body_rows: list[list[str]] = []
    for row in spec.body_rows:
        new_body_rows.append(converted[idx : idx + len(row)])
        idx += len(row)

    return TableSpec(
        name=spec.name,
        caption=new_caption,
        colspec=spec.colspec,
        header_rows=new_header_rows,
        body_rows=new_body_rows,
    )


def process_text(text: str) -> str:
    """Find all ``\\begin{table}`` blocks, convert their cells through
    pandoc in a single batch, and replace each block with a marker.

    The marker is wrapped in blank lines by ``reassemble`` — critical when
    a ``\\begin{table}`` sits immediately after prose with no blank line
    (Deep-Learning ``ch07_pinns.tex`` + 4 others): without the wrap the
    marker glues to the paragraph, pandoc emits it inline, and the decoded
    directive collapses (PR #53)."""
    blocks = find_table_blocks(text)
    if not blocks:
        return text

    # Parse each block.
    specs: list[TableSpec | None] = []
    for _, _, body in blocks:
        specs.append(parse_table_block(body))

    # Collect all cells/captions into one flat list. Track each spec's
    # offset so we can distribute back.
    flat_in: list[str] = []
    offsets: list[tuple[int, int]] = []  # (start, length) per spec
    for spec in specs:
        if spec is None:
            offsets.append((-1, 0))
            continue
        cells = _flatten_table_cells(spec)
        offsets.append((len(flat_in), len(cells)))
        flat_in.extend(cells)

    # Single pandoc batch invocation for the whole file.
    flat_out = _pandoc_batch_convert(flat_in, caller='_apply_table_markers')

    # Apply converted cells back to specs.
    converted_specs: list[TableSpec | None] = []
    for spec, (start, length) in zip(specs, offsets):
        if spec is None or start < 0:
            converted_specs.append(None)
            continue
        converted_specs.append(
            _unflatten_table_cells(spec, flat_out[start : start + length])
        )

    # Stream re-assembly in source order (shared ``reassemble``): each
    # parsed block becomes a blank-line-wrapped marker; unparsed shapes
    # (spec is None) are left in place for the post-pandoc fallback.
    spans = [(start, end) for start, end, _ in blocks]
    rendered = [encode_marker(spec) if spec is not None else None
                for spec in converted_specs]
    return reassemble(text, spans, rendered)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _apply_table_markers.py TEX_FILE')
    tex_file = Path(sys.argv[1])
    text = tex_file.read_text(encoding='utf-8')
    new_text = process_text(text)
    if new_text != text:
        tex_file.write_text(new_text, encoding='utf-8')


if __name__ == '__main__':
    main()
