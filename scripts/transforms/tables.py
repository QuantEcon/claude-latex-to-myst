"""Pandoc simple_tables → MyST {list-table} directives (closes #19).

Only 2-column tables are converted — wider tables have more layout
nuance (column alignment, header spans, multi-line cells) and are
left untouched. See QUALITY-REVIEW.md §T1c follow-up for the N-col
extension proposal (issue #34, deferred).
"""

from __future__ import annotations

import re

from ._helpers import convert_label_colons


def convert_simple_tables(text: str) -> str:
    """Convert pandoc 2-column simple_tables to MyST ``{list-table}``.

    Pandoc renders LaTeX ``tabular`` as its fixed-width simple_tables
    format::

          ----------    -----------------------
          $\\1\\{P\\}$  indicator function...
          $\\alpha$     defined as 1
          ----------    -----------------------

    which is hostile to manual edits and renders poorly. For the common
    two-column glossary shape, the right MyST target is ``{list-table}``.

    Only 2-column tables are converted — wider tables have more layout
    nuance (column alignment, header spans, multi-line cells) and are
    left untouched. A caption emitted after the closing rule (``: …``)
    is migrated to the directive's ``:caption:`` option.
    """
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False
    i = 0
    rule_re = re.compile(r'^(\s+)(-+(?: +-+)+)\s*$')

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

        if not rule_re.match(line):
            out.append(line)
            i += 1
            continue

        # Column boundaries: positions of the dash groups in the rule.
        dash_spans = [(m.start(), m.end()) for m in re.finditer(r'-+', line)]
        if len(dash_spans) != 2:
            # Wider tables are out of scope for the first cut.
            out.append(line)
            i += 1
            continue

        col2_start = dash_spans[1][0]

        # Collect rows until the matching closing rule (same 2-group shape),
        # or — for pandoc's multiline_table shape, which has no closing
        # dash-rule — until the enclosing ``::: center`` fenced-div boundary.
        # Without the fenced-div bound the scan would run on past the
        # current table, consume intervening paragraphs and a *later*
        # table's header, and only stop when it hit that later table's
        # opening rule (GH #24).
        rows_raw: list[str] = []
        j = i + 1
        stopped_on_rule = False
        while j < len(lines):
            cand = lines[j]
            if rule_re.match(cand):
                cand_spans = [
                    (m.start(), m.end()) for m in re.finditer(r'-+', cand)
                ]
                if len(cand_spans) == 2:
                    stopped_on_rule = True
                    break
            cand_stripped = cand.strip()
            if cand_stripped == ':::' or cand_stripped.startswith('::: '):
                break
            rows_raw.append(cand)
            j += 1

        if j >= len(lines):
            out.append(line)
            i += 1
            continue

        # Parse rows. Pandoc emits two related shapes:
        #   - simple_tables: every non-blank line is a row; no blank
        #     lines inside the table.
        #   - multiline_tables: blank lines separate rows, and a row's
        #     cells may span multiple consecutive non-blank lines.
        # Choose mode by whether ``rows_raw`` contains any blank line.
        rows: list[tuple[str, str]] = []
        multiline = any(not rl.strip() for rl in rows_raw)
        if multiline:
            cur_a: list[str] = []
            cur_b: list[str] = []
            for rl in rows_raw:
                if not rl.strip():
                    a = ' '.join(s for s in cur_a if s)
                    b = ' '.join(s for s in cur_b if s)
                    if a or b:
                        rows.append((a, b))
                    cur_a, cur_b = [], []
                    continue
                cur_a.append(rl[:col2_start].strip())
                cur_b.append(rl[col2_start:].strip())
            a = ' '.join(s for s in cur_a if s)
            b = ' '.join(s for s in cur_b if s)
            if a or b:
                rows.append((a, b))
        else:
            for rl in rows_raw:
                a = rl[:col2_start].strip()
                b = rl[col2_start:].strip()
                if a or b:
                    rows.append((a, b))

        if not rows:
            out.append(line)
            i += 1
            continue

        # Optional caption after the closing rule: ``  : caption text``.
        # When the scan stopped on a ``:::`` boundary (no closing rule),
        # leave that line in place — it closes the wrapping fenced div
        # and must not be eaten as if it were a caption.
        next_i = j + 1 if stopped_on_rule else j
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
        out.append(':header-rows: 0')
        if caption:
            out.append(f':caption: {caption}')
        out.append('')
        for a, b in rows:
            out.append(f'* - {a}')
            out.append(f'  - {b}')
        out.append('```')

        i = next_i

    return '\n'.join(out)


