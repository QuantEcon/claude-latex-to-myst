---
id: 019
title: "Pandoc simple_tables vs multiline_tables — blank-line presence flips row-parsing logic"
category: post-processing
tags: [tables, list-table, pandoc, glossary, row-parsing]
source_project: book-dp2 (common_symbols regen)
status: codified
codified_in: scripts/postprocess.py::convert_simple_tables
severity: high
date: 2026-05-20
---

## Symptom

While converting pandoc's fixed-width table format to MyST `{list-table}`
for dp2's `common_symbols.md`, the first cut concatenated every row into a
single cell:

```
* - $\alpha$ $\beta$
  - the first letter the second letter
```

instead of:

```
* - $\alpha$
  - the first letter
* - $\beta$
  - the second letter
```

Filed as Issue 1 of [`FIX-frontmatter-and-tables.md`](../FIX-frontmatter-and-tables.md).
The visible table boundary (dash rules top + bottom) looks the same in both
formats pandoc emits — but they require opposite parsing strategies.

## Cause

Pandoc emits two visually similar table formats for LaTeX `tabular`:

**simple_tables** — every non-blank line is its own row. Cells must fit on
one line. No blank lines inside the table body:

```
  ----  --------
  A     short
  B     also short
  ----  --------
```

**multiline_tables** — blank lines separate rows. A row's cells may span
multiple consecutive non-blank lines, joined with a space:

```
  ----  ----------
  A     a long
        wrapped cell

  B     another long
        wrapped cell
  ----  ----------
```

The structural signal that distinguishes them is the presence of blank
lines *inside* the table body. There is no other syntactic marker — the
dash rules above and below look identical.

The first-cut implementation always accumulated non-blank lines into a
"current row" and flushed on blank lines. That works for multiline_tables
but, for simple_tables (which have no blank lines), every line accumulates
into one giant row — collapsing the whole table into a single `* -` /
`  -` pair.

## Fix

Branch on whether the row region contains any blank line:

```python
multiline = any(not rl.strip() for rl in rows_raw)
if multiline:
    # blank-line-separated rows; non-blank lines within a row join
    cur_a, cur_b = [], []
    for rl in rows_raw:
        if not rl.strip():
            flush()
            continue
        cur_a.append(rl[:col2_start].strip())
        cur_b.append(rl[col2_start:].strip())
    flush()
else:
    # each non-blank line is one row
    for rl in rows_raw:
        rows.append((rl[:col2_start].strip(), rl[col2_start:].strip()))
```

Both shapes are exercised in
[tests/test_transforms.py](../tests/test_transforms.py): the
`test_simple_table_two_column_basic` case (no blank lines, multiple rows)
and `test_multiline_table_blank_lines_separate_rows` (explicit blank-line
separators with multi-line cells).

## Scoping decisions resolved at codification

- **2-column only for the first cut.** Per FIX Issue 1's recommendation,
  the transform short-circuits for tables with column count ≠ 2 and
  leaves them as raw pandoc dash-rule format. Wider tables have more
  layout nuance — column alignment, header spans, span-merged cells —
  and that nuance is rarer (only one such table in all of dp2: the
  4-column convergence-cases table in `ch_adps.tex`). Worth extending
  only on demand.
- **Caption (`  : caption text` after the closing rule)** is migrated to
  `{list-table}`'s `:caption:` option. Glossary tables typically don't
  have captions, but the handling is cheap and avoids a separate fix
  later.
- **Code-fence guard.** The transform skips inside ` ``` ` fences so an
  ASCII table inside a code block isn't mistaken for a pandoc table.
- **Unclosed-rule safety.** If a dash-rule has no matching close before
  EOF, the transform passes through unchanged rather than silently
  swallowing the remainder of the file (`test_simple_table_unclosed_rule_passes_through`).

## How to detect

```bash
# Any pandoc-style dash-rule lines remaining in MyST output should
# correspond to tables that are deliberately out of scope (≠ 2 cols).
# In dp2 fresh output: ch_adps.md has 2 (the convergence-cases 4-col
# table). Everywhere else should be 0.
for f in mystmd/*.md; do
  n=$(grep -cE '^\s+-+( +-+)+\s*$' "$f")
  [ "$n" -gt 0 ] && echo "$(basename $f): $n dash-rule lines"
done
```

If a 2-column table appears in this list, the transform missed it —
likely because its dash-group spans were detected with the wrong column
count (e.g., a row with a long header that visually splits a single
column into two).

## Generalizable rule

Visually similar pandoc outputs can have non-obvious structural rules.
When two emission shapes look the same in a glance but differ in one
small signal (blank lines, alignment dots, fenced markers), the parser
must read that signal explicitly and branch — not assume one shape and
hope. The cost of the branch is small; the cost of silently collapsing
every glossary table into a single cell is large.
