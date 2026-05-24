---
id: 025
title: "Multiline-table forward scan needs the ::: fenced-div boundary or it eats the next table"
category: post-processing
tags: [tables, list-table, pandoc, multiline-tables, forward-scan, fenced-div]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_simple_tables
severity: high
date: 2026-05-24
---

## Symptom

In a chapter with two `\begin{center}\begin{tabular}…\end{tabular}\end{center}`
notation tables separated by a paragraph, the post-processor fused the
two tables and the intervening prose into one mangled `{list-table}`:

- Row 1 = all 15 source rows of table 1 concatenated into a single
  cell (no row separators).
- Row 2 = the paragraph between tables, with column-2 split position
  taken from table 1's rule, so cells mis-aligned mid-word
  ("chapter-speci" / "fic notation").
- Row 3 = a bold heading, similarly mis-aligned.
- Row 4 = `::: center` + table 2's header line.

Table 2's data rows fell *outside* the now-closed `{list-table}` and
survived as raw indented text in the output.

Builds as a noisy mess, but only one obviously broken-looking table
(plus N silent dropped headers) — the symptom undersells how many
chars were swallowed.

## Cause

Pandoc renders LaTeX `tabular` as two visually similar shapes — see
lesson [019](019-simple-vs-multiline-tables.md) for the simple_tables /
multiline_tables distinction. The asymmetry that bites here is in
**multiline_tables wrapped inside `\begin{center}`**:

```
::: center
  Symbol                      Meaning
  --------------------------- ---------------------------
  $\alpha$                    first letter
  ...
:::
```

Note: there is an **opening** dash-rule between header and data, but
**no closing** dash-rule at the bottom. The `:::` div closer is the
only thing demarcating the table's end.

`convert_simple_tables` collected rows by scanning forward from the
opening rule looking for "another rule line with 2 dash-groups". For
this multiline shape, that closing rule doesn't exist — so the scan
ran on past the `:::`, past intervening paragraphs, past the *next*
`::: center` open, past table 2's header line, and only stopped when
it hit **table 2's opening rule**. By then `rows_raw` contained the
entire region between the two tables.

Lesson [019] correctly distinguishes simple_tables from
multiline_tables by checking `any(not rl.strip() for rl in rows_raw)`.
That branching is correct *given* `rows_raw` is the actual table body.
The bug is one level up: `rows_raw` is built by an **unbounded forward
scan** that has no concept of "table region ends here".

## Fix

Bound the forward scan on natural table-region terminators. The
cleanest signal is pandoc's own `\begin{center}…\end{center}`
wrapping, which emits as `::: center` … `:::`:

```python
stopped_on_rule = False
while j < len(lines):
    cand = lines[j]
    if rule_re.match(cand):
        cand_spans = [(m.start(), m.end()) for m in re.finditer(r'-+', cand)]
        if len(cand_spans) == 2:
            stopped_on_rule = True
            break
    s = cand.strip()
    if s == ':::' or s.startswith('::: '):
        break          # fenced-div boundary — terminates the table region
    rows_raw.append(cand)
    j += 1
```

Then preserve the `:::` line in output when the scan stopped on a div
boundary rather than a rule:

```python
next_i = j + 1 if stopped_on_rule else j
caption = None
if stopped_on_rule:
    # caption is only legal after a closing rule; skip the sniff
    # when there was no closing rule to follow it.
    ...
```

Test: `test_multiline_table_bounded_by_fenced_div_closer` in
[tests/test_transforms.py](../tests/test_transforms.py) exercises the
two-tables-with-paragraph-between shape.

## How to detect

Before fix, a grep for `\* - ` in a converted multiline-table
file shows fused rows — long lines containing multiple symbol names
that should each have been their own row:

```bash
awk '/^\* - /{ if (length > 80) print FILENAME":"NR": "$0 }' mystmd/notation.md
```

(After fix, every `* - ` line carries one source row's content.)

Also: if a chapter has two tables wrapped in `::: center` and only one
`{list-table}` directive appears in the output, the scan very likely
fused them.

## Generalizable rule

**Unbounded forward scans must bound on every legitimate terminator,
not just the expected one.** Whenever a parser looks for a closing
marker, ask: what other tokens could legitimately end this region? If
the parser doesn't recognise them, it will run on until it
accidentally finds one — and that accidental hit is usually deep
inside the next semantic block.

Concretely for pandoc → MyST:

- Tables can be terminated by closing dash-rules **or** by the
  `\begin{center}` / `:::` div boundary.
- Math blocks can be terminated by `$$` **or** by paragraph breaks
  (in MyST).
- Environment divs can be terminated by `:::` **or** by EOF (always
  have an EOF fallback so a malformed source doesn't hang the scan).

The pattern: "scan forward until X" → "scan forward until X or any
boundary semantically equivalent to X". The extra check is one line;
the silent-fusion bug it prevents is hours of debugging.

This extends lesson [019] — that lesson handles the *row-parsing*
mode-selection within a table region, this one handles correctly
*identifying* the table region in the first place.
