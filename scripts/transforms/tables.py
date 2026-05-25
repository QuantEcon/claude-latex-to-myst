"""Pandoc simple_tables → MyST {list-table} directives (closes #19, #34).

Converts pandoc's fixed-width simple_tables and multiline_tables of any
column count (2+) to MyST ``{list-table}`` directives. Handles three
shapes:

- **Shape A** (top rule + body + bottom rule): the classic
  ``\\begin{center}\\begin{tabular}…`` layout. An interior dash-rule
  with the same column count is treated as a header/body separator.
- **Shape B** (header row + single dash-rule + body, no top/bottom
  rule): pandoc's output for ``\\begin{table}\\begin{tabular}…`` floats
  with no ``\\toprule`` / ``\\bottomrule``. The header is detected as
  same-indent non-blank lines immediately above the rule.
- **Fenced-div bounded**: tables wrapped in ``::: center`` may omit
  the closing rule; the ``:::`` line bounds the scan.

Alignment encoding from dash-rule column widths is deliberately NOT
implemented — ``{list-table}`` defaults (left-aligned) cover the
prose-heavy book-table cases. Follow-up if a consumer needs it.
"""

from __future__ import annotations

import re

from ._helpers import convert_label_colons


# A pandoc dash-rule line: indented, then 2+ dash groups separated by
# single-or-more spaces.
_RULE_RE = re.compile(r'^(\s+)(-+(?: +-+)+)\s*$')

# A pandoc table caption line: indented, then ``: text``.
_CAPTION_RE = re.compile(r'^\s*:\s+\S')


def _rule_columns(line: str) -> list[tuple[int, int]] | None:
    """Return ``[(start, end), ...]`` for each dash group in ``line``, or
    ``None`` if the line is not a dash-rule shape."""
    if not _RULE_RE.match(line):
        return None
    return [(m.start(), m.end()) for m in re.finditer(r'-+', line)]


def _is_fence_boundary(line: str) -> bool:
    s = line.strip()
    return s == ':::' or s.startswith('::: ')


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


def _collect_header_above(
    lines: list[str],
    rule_idx: int,
    opener_indent: int,
    col_starts: list[int],
) -> list[str]:
    """Look back from ``rule_idx`` for non-blank, non-rule lines that
    belong to the header. These are header rows of a Shape-B table
    (pandoc emits this for ``\\begin{table}`` floats with no
    ``\\toprule`` / ``\\bottomrule``).

    Pandoc aligns header text by *data-column position*, not by
    leading-whitespace count. Wide tables routinely have headers at
    indent 26+ over a rule at indent 2 — the data columns start where
    the header text appears, not where the rule's leftmost dash sits.
    Tables with a "row-label" first column may also have FEWER header
    cells than rule columns (the row-label column has no header).

    Original v4: required exact indent match — broke ``execution_map``
    (1-col table, header at different indent than rule).

    v5 (PR #41): relaxed to ``opener_indent <= prev_indent < col_starts[1]``
    — fixed ``execution_map`` but rejected ``tab-seq_compare`` and
    similar wide tables where headers sit at indent 26+ above a rule
    starting at indent 2 (col_starts[1] would be ~24).

    Current (v6): drop the upper-bound check entirely. The lower bound
    (``prev_indent >= opener_indent``) is enough to exclude prose at
    column 0; cell-position alignment is enforced by the downstream
    ``_split_row`` parser using the rule's ``col_starts`` (Mode A fix
    for PR #41 silent failures).

    Stops at: blank line, start of file, indent left of the rule
    opener, or another rule line.

    ``col_starts`` is unused in the current implementation but kept in
    the signature for compatibility with existing callers.
    """
    del col_starts  # unused — see docstring
    header: list[str] = []
    k = rule_idx - 1
    while k >= 0:
        prev = lines[k]
        if not prev.strip():
            break
        prev_indent = len(prev) - len(prev.lstrip())
        if prev_indent < opener_indent:
            break
        if _rule_columns(prev) is not None:
            break
        header.insert(0, prev)
        k -= 1
    return header


def convert_simple_tables(text: str) -> str:
    """Convert pandoc simple_tables / multiline_tables to MyST ``{list-table}``.

    Forward-scan terminator decision:

    - A matching same-column-count rule is the **closer** if the next
      non-blank line is the fenced-div boundary, a caption (``  : …``),
      EOF, or content at a different indent than the opener. It is an
      **interior rule** (header separator) if the next non-blank line is
      a row at the same indent as the opener — in that case scanning
      continues looking for the real closer.
    - A ``:::`` line is the fenced-div boundary.
    - A blank line whose following non-blank line is a caption or
      content at a different indent is the **implicit end** of a Shape-B
      table (no closing rule). Multiline_table row-separator blank
      lines are distinguished by the next non-blank being a row at the
      same indent.

    Column-count guard: the closing rule must have the same column
    count as the opener — a 3-col opener and a 5-col rule downstream
    are not the same table.
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    # Stack of enclosing ``::: {#id}`` div ids. When we emit a table
    # directive, the top of the stack is the table's containing div id
    # — used as ``:name:`` on the directive so MyST attaches the table
    # AST node's identifier canonically (Mode B fix for PR #41 silent
    # failures). The ``(tab-X)=`` standalone anchor emitted downstream
    # by ``convert_environment_divs`` is redundant in this case but
    # harmless — both point to the same label.
    div_id_stack: list[str] = []
    i = 0

    # Matches ``::: {#id}`` (id-only fence opener) only — not
    # ``::: env_name`` (which ``_is_fence_boundary`` doesn't match).
    _id_div_open_re = re.compile(r'^\s*:{3,}\s+\{#([^}\s]+)')

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

        # Track ``::: {#id}`` ... ``:::`` div nesting so the table
        # directive emitted below carries the correct ``:name:``.
        if _is_fence_boundary(line):
            id_m = _id_div_open_re.match(line)
            if id_m:
                div_id_stack.append(id_m.group(1))
            elif div_id_stack and line.strip() == ':::':
                div_id_stack.pop()
            # Other shapes (``::: {.class}`` etc.) don't carry an id;
            # leave the stack alone.
            out.append(line)
            i += 1
            continue

        dash_spans = _rule_columns(line)
        if dash_spans is None:
            out.append(line)
            i += 1
            continue

        ncols = len(dash_spans)
        col_starts = [s for s, _ in dash_spans]
        opener_indent = len(line) - len(line.lstrip())

        # Shape-B header rows above (popped off ``out`` below if we
        # actually emit a list-table).
        header_above = _collect_header_above(lines, i, opener_indent, col_starts)

        # Forward scan. Three possible terminators (mutually exclusive):
        rule_positions: list[int] = []
        closer_idx: int | None = None
        boundary_idx: int | None = None
        implicit_end_idx: int | None = None

        j = i + 1
        while j < len(lines):
            cand = lines[j]
            if _is_fence_boundary(cand):
                boundary_idx = j
                break

            cand_spans = _rule_columns(cand)
            if cand_spans is not None and len(cand_spans) == ncols:
                rule_positions.append(j)
                # Closer vs. interior decision via next non-blank line.
                m = j + 1
                while m < len(lines) and not lines[m].strip():
                    m += 1
                if m >= len(lines):
                    closer_idx = j
                    break
                nxt = lines[m]
                if _is_fence_boundary(nxt) or _CAPTION_RE.match(nxt):
                    closer_idx = j
                    break
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent != opener_indent:
                    closer_idx = j
                    break
                # Otherwise this rule is interior (header separator).
                j += 1
                continue

            # Blank-line termination is only meaningful for Shape-B
            # tables (no closing rule; body ends at blank + caption /
            # different-indent content / EOF). For Shape A, an unclosed
            # opener should bail at the outer level — letting blanks
            # implicitly terminate would convert malformed tables that
            # the old 2-col code (and current callers) expect to leave
            # untouched.
            if not cand.strip() and header_above:
                m = j + 1
                while m < len(lines) and not lines[m].strip():
                    m += 1
                if m >= len(lines):
                    implicit_end_idx = j
                    break
                nxt = lines[m]
                if _is_fence_boundary(nxt):
                    # Let the outer loop's boundary check handle it.
                    j += 1
                    continue
                if _CAPTION_RE.match(nxt):
                    implicit_end_idx = j
                    break
                nxt_spans = _rule_columns(nxt)
                if nxt_spans is not None and len(nxt_spans) == ncols:
                    # Next is a same-shape rule (within-table separator
                    # in a multiline_table). Continue scanning.
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent != opener_indent:
                    implicit_end_idx = j
                    break
                # Same-indent row → continuation. Continue.
            j += 1

        # Shape B running to EOF without any explicit terminator.
        if (closer_idx is None and boundary_idx is None
                and implicit_end_idx is None and header_above):
            implicit_end_idx = len(lines)

        if (closer_idx is None and boundary_idx is None
                and implicit_end_idx is None):
            out.append(line)
            i += 1
            continue

        end_for_blocks = (
            closer_idx if closer_idx is not None
            else (boundary_idx if boundary_idx is not None else implicit_end_idx)
        )

        # Rules inside the table body: all collected positions minus the
        # closer (if any). These slice the body into header/body blocks.
        interior_rules = (
            rule_positions[:-1] if closer_idx is not None
            else list(rule_positions)
        )

        blocks: list[list[str]] = []
        last_rule = i
        for r in interior_rules:
            blocks.append(lines[last_rule + 1 : r])
            last_rule = r
        trailing = lines[last_rule + 1 : end_for_blocks]
        if any(rl.strip() for rl in trailing):
            blocks.append(trailing)

        # Defensive caption-peel: in the rare fenced-div case with a
        # caption that wasn't separated from the body by a blank line,
        # the caption can show up as the last block. Drop it so it's
        # not parsed as a row; caption-detection below will find it
        # again via ``next_i``.
        if len(blocks) >= 2:
            last = blocks[-1]
            nonblank = [rl for rl in last if rl.strip()]
            if nonblank and all(_CAPTION_RE.match(rl) for rl in nonblank):
                blocks.pop()

        # Shape-B header rows become blocks[0].
        if header_above:
            blocks.insert(0, header_above)

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
        if any(not rows for rows in parsed_blocks):
            out.append(line)
            i += 1
            continue

        # Pop Shape-B header rows from ``out`` (they were appended in
        # earlier iterations as ordinary non-rule lines).
        if header_above:
            del out[-len(header_above):]

        if closer_idx is not None:
            next_i = closer_idx + 1
        elif implicit_end_idx is not None:
            next_i = implicit_end_idx
        else:  # boundary_idx is not None
            next_i = boundary_idx

        caption = None
        if closer_idx is not None or implicit_end_idx is not None:
            m = next_i
            while m < len(lines) and not lines[m].strip():
                m += 1
            if m < len(lines):
                cap_m = re.match(r'^\s*:\s+(.+)$', lines[m])
                if cap_m:
                    caption = cap_m.group(1).strip()
                    next_i = m + 1

        header_rows_count = len(parsed_blocks[0]) if has_header else 0
        all_rows = [row for rows in parsed_blocks for row in rows]

        # Captioned tables: wrap ``{list-table}`` inside ``{table}``.
        # Rationale (regression from caption-as-argument form, PR #41 v4):
        #
        # MyST's ``{list-table}`` does NOT accept ``:caption:`` as an
        # option (the docutils-style emits "unexpected option caption"
        # and drops the caption text). The caption-as-argument form
        # ``\`\`\`{list-table} Long caption with $math$...`` works for
        # short ASCII captions but breaks MyST's parser when the
        # argument is long or contains inline math/refs — the
        # subsequent ``:header-rows:`` line and bullet rows are
        # mis-attributed and docutils' ``list-table`` body validator
        # fires "list-table directive must have a list of lists".
        #
        # ``{table}`` accepts a caption as its argument too, but its
        # body has NO docutils body-validation constraint (it wraps
        # arbitrary markdown / nested directives). Even if MyST's
        # argument parser has the same long-content quirk, the failure
        # mode degrades from "explicit error + 0 AST nodes" to at worst
        # "caption text bleeds into body" — the directive still
        # produces a table AST node and cross-refs resolve.
        #
        # 4-backtick outer fence so the inner 3-backtick ``{list-table}``
        # closes cleanly inside it. ``(label)=`` anchors emitted by
        # ``convert_environment_divs`` (downstream) attach to the next
        # block — ``{table}`` is enumerable, so ``{numref}`tab-X``
        # renders as "Table N" via the wrapper's auto-counter.
        # ``:name:`` from the enclosing ``::: {#id}`` div fence, if
        # any. Explicit name on the directive ensures the table AST
        # node carries the identifier even when standalone-anchor
        # attachment misfires (Mode B fix). Wrapped in ``convert_label_colons``
        # for the colon→hyphen normalisation MyST expects.
        directive_name = (
            convert_label_colons(div_id_stack[-1]) if div_id_stack else None
        )

        if caption:
            # Caption is emitted as the FIRST PARAGRAPH inside the
            # ``{table}`` body, NOT as the directive argument. Two
            # bugs in MyST's directive-argument parser drove this:
            #
            # (1) Captions containing inline-role backticks (``{ref}
            #     `ch-foo``` / ``{cite:t}`smith2023```) — the parser
            #     misreads the role's backticks as inline-code span
            #     delimiters mid-argument, the directive fails to
            #     parse cleanly, and the ``{table}`` collapses to a
            #     plain paragraph in the AST.
            # (2) Very long mixed-math captions (~400+ chars, multiple
            #     ``$math$`` runs) — argument parser mis-attributes
            #     subsequent lines, body validator fires "list-table
            #     directive must have a list of lists".
            #
            # Caption-as-first-paragraph is the canonical MyST form
            # for ``{table}`` per https://mystmd.org/guide/figures#tables
            # — the body is regular markdown so inline roles, backticks,
            # and math all parse normally. Closes PR #41 silent-fail
            # and explicit-error classes for captioned tables.
            out.append('````{table}')
            if directive_name:
                out.append(f':name: {directive_name}')
            out.append('')
            out.append(caption)
            out.append('')
            out.append('```{list-table}')
            out.append(f':header-rows: {header_rows_count}')
            out.append('')
            for row in all_rows:
                out.append(f'* - {row[0]}')
                for cell in row[1:]:
                    out.append(f'  - {cell}')
            out.append('```')
            out.append('````')
        else:
            out.append('```{list-table}')
            if directive_name:
                out.append(f':name: {directive_name}')
            out.append(f':header-rows: {header_rows_count}')
            out.append('')
            for row in all_rows:
                out.append(f'* - {row[0]}')
                for cell in row[1:]:
                    out.append(f'  - {cell}')
            out.append('```')

        i = next_i

    return '\n'.join(out)
