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
writing markers. ``resolve_table_markers`` in ``postprocess.py``
decodes and emits MyST directives.

This is the table analogue of ``_apply_listing_markers.py`` and
``_apply_algorithm_markers.py``.

Usage:
    _apply_table_markers.py TEX_FILE
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Import via path so this works as a script (run from preprocess.sh).
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from transforms.tables_from_latex import (  # noqa: E402
    TableSpec,
    encode_marker,
    find_table_blocks,
    parse_table_block,
)


# Pandoc batch-conversion sentinel. We collect every cell (and the
# caption) from every table in the file into a single LaTeX input
# separated by ``<!--CELL_N-->`` markers. Pandoc preserves the HTML
# comments (escaping them as ``\<!--CELL_N--\>``) and converts the
# LaTeX between them. We then split the output to distribute markdown
# cells back to their TableSpecs.
_CELL_SENTINEL_OUT_RE = re.compile(r'\\?<!--CELL_(\d+)--\\?>')


def _pandoc_batch_convert(cells: list[str]) -> list[str]:
    """Convert a list of LaTeX cell-content strings to markdown in ONE
    pandoc invocation.

    Empty cells are replaced with ``\\mbox{}`` so pandoc still emits a
    paragraph block for them — otherwise consecutive sentinels collapse
    and splitting becomes ambiguous.

    Returns a list of markdown strings, same length and order as input.
    """
    if not cells:
        return []

    parts: list[str] = []
    for i, cell in enumerate(cells):
        parts.append(f'<!--CELL_{i}-->')
        # ``\mbox{}`` produces an empty paragraph that pandoc converts
        # to a blank line — preserves the sentinel boundary for empty
        # cells (common in books, e.g. dp2's checkmark columns).
        parts.append(cell.strip() or r'\mbox{}')

    latex_in = '\n\n'.join(parts) + '\n'

    result = subprocess.run(
        ['pandoc', '-f', 'latex', '-t', 'markdown', '--wrap=none'],
        input=latex_in,
        capture_output=True,
        text=True,
        check=True,
    )
    md_out = result.stdout

    # Split on the sentinel pattern. ``re.split`` with a capture group
    # interleaves the capture (the cell index) with the surrounding
    # text. After the first sentinel, the structure is:
    #   [pre_text, '0', content0, '1', content1, ..., 'N', contentN]
    pieces = _CELL_SENTINEL_OUT_RE.split(md_out)
    if len(pieces) < 3:
        # Pandoc didn't preserve any sentinels — fallback: return
        # original cells (preserves correctness over conversion).
        return list(cells)

    out_cells: list[str] = [''] * len(cells)
    # pieces[0] is pre-first-sentinel text (usually empty).
    for i in range(1, len(pieces), 2):
        try:
            idx = int(pieces[i])
        except (ValueError, IndexError):
            continue
        content = pieces[i + 1] if i + 1 < len(pieces) else ''
        # Strip trailing newlines/paragraph breaks but preserve interior.
        content = content.strip()
        # Replace the \mbox{} placeholder back to empty.
        if content in (r'\mbox{}', ''):
            content = ''
        if 0 <= idx < len(out_cells):
            out_cells[idx] = content

    return out_cells


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
    pandoc in a single batch, and replace each block with a marker."""
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
    flat_out = _pandoc_batch_convert(flat_in)

    # Apply converted cells back to specs.
    converted_specs: list[TableSpec | None] = []
    for spec, (start, length) in zip(specs, offsets):
        if spec is None or start < 0:
            converted_specs.append(None)
            continue
        converted_specs.append(
            _unflatten_table_cells(spec, flat_out[start : start + length])
        )

    # Replace blocks in reverse so offsets stay valid.
    out_parts: list[str] = []
    last_end = 0
    for (start, end, _), spec in zip(blocks, converted_specs):
        out_parts.append(text[last_end:start])
        if spec is None:
            # Couldn't parse — leave the block in place. Pandoc will
            # handle it as best it can.
            out_parts.append(text[start:end])
        else:
            out_parts.append(encode_marker(spec))
        last_end = end
    out_parts.append(text[last_end:])
    return ''.join(out_parts)


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
