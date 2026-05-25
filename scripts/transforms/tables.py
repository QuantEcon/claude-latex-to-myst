"""Pandoc simple_tables → MyST {list-table} directives (closes #19, #34).

Converts pandoc's fixed-width simple_tables and multiline_tables of any
column count (2+) to MyST ``{list-table}`` directives. An interior
dash-rule is treated as a header/body separator and triggers
``:header-rows: 1`` in the emitted directive.

Alignment encoding from dash-rule column widths is deliberately NOT
implemented — ``{list-table}`` defaults (left-aligned) cover the
prose-heavy book-table cases. Follow-up if a consumer needs it.
"""

from __future__ import annotations

import re


# ── Module-level regexes ──────────────────────────────────────────────────────

# A pandoc dash-rule line: indented, then 2+ dash groups separated by
# single-or-more spaces.
_RULE_RE = re.compile(r'^(\s+)(-+(?: +-+)+)\s*$')


def _rule_columns(line: str) -> list[tuple[int, int]] | None:
    """Return ``[(start, end), ...]`` for each dash group in ``line``, or
    ``None`` if the line is not a dash-rule shape."""
    if not _RULE_RE.match(line):
        return None
    return [(m.start(), m.end()) for m in re.finditer(r'-+', line)]


def _split_row(line: str, col_starts: list[int]) -> list[str]:
    """Slice ``line`` into cells at ``col_starts`` positions and strip each.

    ``col_starts[0]`` is treated as 0 so the first column captures any
    leading indent (stripped). For 2-col this mirrors the historical
    ``rl[:col2_start]`` / ``rl[col2_start:]`` split exactly.
    """
    cells: list[str] = []
    for k, start in enumerate(col_starts):
        if k == 0:
            start = 0
        end = col_starts[k + 1] if k + 1 < len(col_starts) else None
        cells.append(line[start:end].strip() if end is not None else line[start:].strip())
    return cells


def _parse_block(
    block_lines: list[str],
    col_starts: list[int],
    multiline: bool,
) -> list[list[str]]:
    """Parse ``block_lines`` (lines between two rules, or rule + boundary)
    into a list of rows. In multiline mode, blank lines separate rows and
    non-blank lines within a row join with single spaces."""
    rows: list[list[str]] = []
    if multiline:
        cur: list[list[str]] = [[] for _ in col_starts]
        for rl in block_lines:
            if not rl.strip():
                joined = [' '.join(s for s in c if s) for c in cur]
                if any(joined):
                    rows.append(joined)
                cur = [[] for _ in col_starts]
                continue
            for k, cell in enumerate(_split_row(rl, col_starts)):
                if cell:
                    cur[k].append(cell)
        joined = [' '.join(s for s in c if s) for c in cur]
        if any(joined):
            rows.append(joined)
    else:
        for rl in block_lines:
            if not rl.strip():
                continue
            row = _split_row(rl, col_starts)
            if any(row):
                rows.append(row)
    return rows


def convert_simple_tables(text: str) -> str:
    """Convert pandoc simple_tables / multiline_tables to MyST ``{list-table}``.

    Pandoc renders LaTeX ``tabular`` as fixed-width dash-bordered blocks::

          ----------    -----------------------
          $\\1\\{P\\}$  indicator function...
          $\\alpha$     defined as 1
          ----------    -----------------------

    which is hostile to manual edits and renders poorly. The right MyST
    target is ``{list-table}``.

    Header detection: an interior dash-rule with the same column count as
    the opener marks the header/body boundary. Tables with such a
    separator emit ``:header-rows: 1``; bare tables (no interior rule)
    emit ``:header-rows: 0``.

    Column-count guard: the closing rule must have the SAME column count
    as the opener. A 3-col opener followed downstream by a 2-col rule is
    not a match — preserves us against fusing two adjacent tables of
    different shapes.

    Caption: ``  : caption text`` after the closing rule is migrated to
    the directive's ``:caption:`` option.

    Bounding: when no closing rule exists (e.g. multiline_tables wrapped
    in ``::: center``), the scan stops at the ``:::`` fenced-div
    boundary rather than running on into the next table (issue #24).
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        dash_spans = _rule_columns(line)
        if dash_spans is None:
            out.append(line)
            i += 1
            continue

        ncols = len(dash_spans)
        # ``col_starts[k]`` is the horizontal position of column k's
        # left edge in the rule. The first column slice starts at 0
        # so leading indent is captured and stripped (matches the
        # historical 2-col behavior).
        col_starts = [s for s, _ in dash_spans]

        # Forward-scan: collect interior matching rules and the boundary
        # (either a same-column-count closing rule or a ``:::`` fenced-div
        # marker). Rules that do NOT match the opener's column count are
        # ignored — they belong to a different table.
        rule_positions: list[int] = []
        boundary_idx: int | None = None
        j = i + 1
        while j < len(lines):
            cand = lines[j]
            cand_stripped = cand.strip()
            if cand_stripped == ':::' or cand_stripped.startswith('::: '):
                boundary_idx = j
                break
            cand_spans = _rule_columns(cand)
            if cand_spans is not None and len(cand_spans) == ncols:
                rule_positions.append(j)
            j += 1

        # No closing rule and no fenced-div boundary → unclosed opener,
        # leave it alone (defensive: don't swallow rest of file).
        if not rule_positions and boundary_idx is None:
            out.append(line)
            i += 1
            continue

        # Segment row-content into "blocks" delimited by interior rules
        # and the boundary. A simple_table with header has one interior
        # rule (between header and body) plus a closing rule → two
        # blocks. A headerless table has only a closing rule → one
        # block. Fenced-div bounded tables may have 0 or 1 interior
        # rules depending on whether a header is present.
        blocks: list[list[str]] = []
        last_rule = i
        for r in rule_positions:
            blocks.append(lines[last_rule + 1 : r])
            last_rule = r
        # The "trailing" block: content between the last rule and the
        # boundary (when fenced-div bounded). If there's a closing rule
        # at the end with nothing after it before the boundary, the
        # trailing block is empty and we don't add it.
        if boundary_idx is not None and last_rule < boundary_idx:
            trailing = lines[last_rule + 1 : boundary_idx]
            if any(rl.strip() for rl in trailing):
                blocks.append(trailing)

        # Caption inside a fenced div: pandoc emits captions on their
        # own line as ``^\s*:\s+TEXT``. When a table is wrapped in
        # ``::: center`` and has a caption between the closing rule and
        # the ``:::`` boundary, that caption ends up as the last block.
        # Peel it off so caption-detection below picks it up from
        # ``next_i`` — otherwise it would either inflate the block count
        # (bail) or render as a fake table row.
        if len(blocks) >= 2:
            last = blocks[-1]
            nonblank = [rl for rl in last if rl.strip()]
            if nonblank and all(re.match(r'^\s*:\s+\S', rl) for rl in nonblank):
                blocks.pop()

        # 1 block → headerless. 2 blocks → header + body. 3+ blocks
        # (multiple interior rules → multi-section table) is rare and
        # ambiguous; leave alone.
        if not blocks or len(blocks) > 2:
            out.append(line)
            i += 1
            continue

        has_header = len(blocks) == 2
        multiline = any(
            not rl.strip()
            for block in blocks
            for rl in block
        )

        parsed_blocks = [_parse_block(b, col_starts, multiline) for b in blocks]
        # A block that yields zero rows (e.g. only blank lines) makes the
        # table degenerate — bail to passthrough rather than emit a
        # malformed list-table.
        if any(not rows for rows in parsed_blocks):
            out.append(line)
            i += 1
            continue

        # Determine where to resume after the table and whether a
        # caption follows. A caption only appears after a real closing
        # rule, not after a fenced-div boundary (the ``:::`` line itself
        # must be preserved).
        stopped_on_rule = bool(rule_positions) and (
            boundary_idx is None or rule_positions[-1] < boundary_idx
        )
        next_i = (rule_positions[-1] + 1) if stopped_on_rule else (boundary_idx or j)

        caption = None
        if stopped_on_rule:
            k = next_i
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines):
                cap_m = re.match(r'^\s*:\s+(.+)$', lines[k])
                if cap_m:
                    caption = cap_m.group(1).strip()
                    next_i = k + 1

        out.append('```{list-table}')
        out.append(f':header-rows: {1 if has_header else 0}')
        if caption:
            out.append(f':caption: {caption}')
        out.append('')
        all_rows = [row for rows in parsed_blocks for row in rows]
        for row in all_rows:
            out.append(f'* - {row[0]}')
            for cell in row[1:]:
                out.append(f'  - {cell}')
        out.append('```')

        i = next_i

    return '\n'.join(out)
