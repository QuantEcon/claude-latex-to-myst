"""Pandoc simple_tables → MyST {list-table} directives (closes #19, #34).

**Status (PR #55):** this transform is now a SAFETY-NET FALLBACK only.
Every ``\\begin{tabular}`` variant in source ``.tex`` is now extracted
BEFORE pandoc sees it by ``_apply_table_markers.py`` (via
``transforms.tables_from_latex.find_table_blocks``), so pandoc no longer
emits dash-rule simple_tables for any tabular originating from
``.tex``. This transform stays in place to catch:

  - Source files that contain literal pandoc-style simple_table markup
    (rare; only happens if a hand-edit injected raw dash-rule tables
    into the markdown OUTPUT, then re-ran the pipeline — not a normal
    flow).
  - Defensive coverage if a future change to ``_apply_table_markers.py``
    misses a tabular shape and lets pandoc emit dash-rule output.

It is no longer reached by any production input across book-dp1,
book-dp2, or Deep-Learning. Retirement is tracked as part of #55's
Phase 4 ("once all corpora pass cleanly through the new path, mark
deprecated, keep one release cycle, then delete").

Original docstring follows.

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

# A "broad" single-group dash-rule (≥10 dashes, no internal spaces) —
# pandoc emits these for ``\toprule``/``\bottomrule`` when the source
# table has no per-column rules between header and body. They bound
# the table but carry no column-position info, so they bypass
# ``_rule_columns`` (which requires 2+ groups). Detected separately
# to bound ``_collect_header_above`` and to terminate the forward
# scan; see PR #41 v8 (``tab-bm_vs_irbc`` shape).
_BROAD_RULE_RE = re.compile(r'^\s+-{10,}\s*$')

# A pandoc table caption line: indented, then ``: text``.
_CAPTION_RE = re.compile(r'^\s*:\s+\S')


def _rule_columns(line: str) -> list[tuple[int, int]] | None:
    """Return ``[(start, end), ...]`` for each dash group in ``line``, or
    ``None`` if the line is not a dash-rule shape."""
    if not _RULE_RE.match(line):
        return None
    return [(m.start(), m.end()) for m in re.finditer(r'-+', line)]


def _is_broad_dash_rule(line: str) -> bool:
    """True if ``line`` is a single-group dash-rule with ≥10 dashes —
    pandoc's broad ``\\toprule``/``\\bottomrule`` shape. Used to
    bound table regions when there's no per-column rule on either
    end. Excludes the multi-group case (``_rule_columns`` covers
    that)."""
    return _BROAD_RULE_RE.match(line) is not None


def _escape_pipe_cell(cell: str) -> str:
    """Escape pipe characters in a pipe-table cell. mystmd treats ``|``
    as a column separator; cell content that contains literal pipes
    (e.g. inline math ``|x|``, code spans with ``|``) must be
    escaped as ``\\|`` to round-trip through the parser."""
    return cell.replace('|', r'\|')


def _emit_pipe_table(all_rows: list[list[str]]) -> list[str]:
    """Emit ``all_rows`` as a markdown pipe-table with the first row
    as the header.

    Pipe tables aren't directives — when nested inside a ``{table}``
    container, mystmd renders them as a regular HTML ``<table>`` and
    does NOT register a separate enumerable container. This avoids
    the phantom-enumerator regression (R2 in PR #41) where the inner
    ``{list-table}`` directive consumed the next table-counter slot,
    making ``{numref}`tab-X`` text drift off-by-one.

    Pipe tables require exactly one header row. Callers must invoke
    this only when ``header_rows_count == 1``; ``0`` and ``>= 2``
    cases fall back to ``{list-table}`` (see caller in
    ``convert_simple_tables``). The 0-header case was previously
    handled here with a synthetic empty header row, but that renders
    as a visible blank row at the top of the table in mystmd —
    surfaced by book-dp2's ``tab-convergence_cases`` where pandoc's
    simple_tables format collapses interior ``\\hline`` separators
    so the LaTeX-side header rows arrive as ``header_rows_count == 0``.
    """
    if not all_rows:
        return []
    ncols = max(len(row) for row in all_rows)

    def fmt_row(row: list[str]) -> str:
        padded = row + [''] * (ncols - len(row))
        return '| ' + ' | '.join(_escape_pipe_cell(c) for c in padded) + ' |'

    header = all_rows[0]
    body = all_rows[1:]
    out: list[str] = []
    out.append(fmt_row(header))
    out.append('|' + '|'.join('---' for _ in range(ncols)) + '|')
    for row in body:
        out.append(fmt_row(row))
    return out


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
) -> tuple[list[str], int]:
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
    opener, or another rule line (multi-group OR broad single-group
    like pandoc's ``\\toprule``).

    Returns ``(header_lines, lines_consumed_above)`` — ``header_lines``
    is the parseable header content (excludes any broad rule);
    ``lines_consumed_above`` is the count of lines that belong to the
    table region above the opener (header + any broad top rule), used
    by the caller to remove them from ``out``. ``lines_consumed_above``
    can exceed ``len(header_lines)`` when a broad rule sits above the
    header — the rule is dropped from parsing but still needs to be
    removed from ``out`` so it doesn't appear as stray dashes above
    the emitted directive. See PR #41 v8 (``tab-bm_vs_irbc`` shape).

    ``col_starts`` is unused in the current implementation but kept in
    the signature for compatibility with existing callers.
    """
    del col_starts  # unused — see docstring
    header: list[str] = []
    consumed = 0
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
        if _is_broad_dash_rule(prev):
            # Broad ``\toprule``-style rule. Include in the
            # consumed-line count so it's removed from ``out``, but
            # don't parse it as a header row, and stop the look-back
            # — content above the rule belongs outside the table.
            consumed += 1
            break
        header.insert(0, prev)
        consumed += 1
        k -= 1
    return header, consumed


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
    out: list[str | None] = []
    in_fence = False
    # Stack of enclosing ``::: {#id}`` div frames. When we emit a table
    # directive, the top of the stack is the table's containing div id
    # — used as ``:name:`` on the directive so MyST attaches the table
    # AST node's identifier canonically (Mode B fix for PR #41 silent
    # failures).
    #
    # When ``:name:`` is emitted from a stack frame, the wrapping
    # ``::: {#id}`` opener and matching ``:::`` closer are SUPPRESSED
    # from the output (set to ``None`` here, filtered at return). This
    # prevents ``convert_environment_divs`` downstream from emitting a
    # redundant ``(tab-X)=`` standalone anchor that would collide with
    # ``:name:`` and fire mystmd's ``duplicate label`` warning on every
    # build. ``:name:`` is the single source of truth for the label.
    div_id_stack: list[dict] = []
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
        # directive emitted below carries the correct ``:name:``. When
        # ``:name:`` is emitted, the frame's ``suppress`` flag is set
        # and both the opener (already in ``out``) and the matching
        # closer are elided from the output (see R1 in PR #41).
        if _is_fence_boundary(line):
            id_m = _id_div_open_re.match(line)
            if id_m:
                div_id_stack.append({
                    'id': id_m.group(1),
                    'opener_idx': len(out),
                    'suppress': False,
                })
                out.append(line)
            elif div_id_stack and line.strip() == ':::':
                frame = div_id_stack.pop()
                if not frame['suppress']:
                    out.append(line)
            else:
                # Other shapes (``::: {.class}`` etc.) don't carry an
                # id and don't push to the stack; pass through.
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
        # actually emit a list-table). ``header_above_consumed`` may
        # exceed ``len(header_above)`` when a broad ``\toprule`` sits
        # above the header — rule is dropped from parsing but counted
        # for ``out`` removal so stray dashes don't appear above the
        # directive.
        header_above, header_above_consumed = _collect_header_above(
            lines, i, opener_indent, col_starts
        )

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

            # Broad single-group dash-rule (pandoc's ``\bottomrule``
            # in no-borders emit). Carries no column info — not added
            # to ``rule_positions`` — but bounds the table region.
            # Treat as closer when next non-blank is caption / fence /
            # different-indent content / EOF. See PR #41 v8
            # (``tab-bm_vs_irbc`` shape).
            if cand_spans is None and _is_broad_dash_rule(cand):
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
                # Otherwise next is same-indent content; treat the
                # rule as within-body filler and continue.
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
        # A broad-rule closer isn't tracked in ``rule_positions`` (no
        # column info), so check whether the closer's index matches the
        # last entry before slicing it off.
        if closer_idx is not None and rule_positions and rule_positions[-1] == closer_idx:
            interior_rules = rule_positions[:-1]
        else:
            interior_rules = list(rule_positions)

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

        # Pop Shape-B header rows + any broad ``\toprule`` from
        # ``out`` (they were appended in earlier iterations as
        # ordinary non-rule lines).
        if header_above_consumed:
            del out[-header_above_consumed:]

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
        # closes cleanly inside it. ``:name:`` on the directive carries
        # the identifier from the enclosing ``::: {#id}`` div fence, if
        # any — this is the canonical Mode B fix (v6). When we emit
        # ``:name:`` we also flag the stack frame for fence
        # suppression: the wrapping ``::: {#id}`` ... ``:::`` is dropped
        # from the output so ``convert_environment_divs`` doesn't emit
        # a competing ``(tab-X)=`` standalone anchor (R1 in PR #41,
        # which fires ``duplicate label`` on every captioned table).
        # Wrapped in ``convert_label_colons`` for the colon→hyphen
        # normalisation MyST expects.
        directive_name = (
            convert_label_colons(div_id_stack[-1]['id'])
            if div_id_stack else None
        )
        if directive_name and div_id_stack:
            frame = div_id_stack[-1]
            out[frame['opener_idx']] = None
            frame['suppress'] = True

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
            #
            # The body table is emitted as a markdown pipe-table when
            # ``header_rows_count == 1`` — the common case. Pipe
            # tables aren't directives, so mystmd treats the inner
            # table as part of the ``{table}`` container — only ONE
            # enumerable per captioned table, not two. This closes R2
            # in PR #41 (the inner ``{list-table}`` was consuming the
            # next table-counter slot, drifting ``{numref}`` text
            # off-by-one).
            #
            # For ``header_rows_count == 0`` (no header detected — most
            # often pandoc's simple_tables format collapsing interior
            # ``\hline`` separators, e.g. book-dp2's
            # ``tab-convergence_cases``) and ``>= 2`` (rare multiline
            # multi-header), we fall back to ``{list-table}`` so the
            # output doesn't carry a synthetic blank header row or a
            # malformed multi-header. The inner directive carries
            # ``:enumerated: false`` so it does NOT claim its own table
            # number — the outer ``{table}`` is the enumerable container.
            # Without that, the inner ``{list-table}`` consumed a phantom
            # ``tab-N.M`` slot and drifted every later table's ``{numref}``
            # by one (issue #52, fixed below).
            out.append('````{table}')
            if directive_name:
                out.append(f':name: {directive_name}')
            out.append('')
            out.append(caption)
            out.append('')
            if header_rows_count == 1:
                out.extend(_emit_pipe_table(all_rows))
            else:
                # ``:enumerated: false`` so the nested ``{list-table}``
                # doesn't claim its own ``tab-N.M`` slot — the enclosing
                # ``{table}`` is the enumerable container. Without it the
                # inner directive drifts every later table's ``{numref}``
                # by one (issue #52; verified honoured in mystmd 1.9.1).
                out.append('```{list-table}')
                out.append(f':header-rows: {header_rows_count}')
                out.append(':enumerated: false')
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

    return '\n'.join(line for line in out if line is not None)
