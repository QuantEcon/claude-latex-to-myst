---
id: 048
title: "Auto-mapping \\ding{N}→Unicode must run before marker extraction — once a cell's \\ding is base64'd into a table/figure marker, the batch pandoc pass drops it again"
category: preprocess
tags: [pifont, ding, text-macros, markers, ordering, tables, unicode]
source_project: book-dp2 (issue #159, reader report QuantEcon/book-dp-public#29)
status: codified
codified_in: scripts/_warn_dropped_text_macros.py::apply_known_glyphs (invoked by scripts/_apply_pifont_glyphs.py, wired into preprocess.sh before the marker scripts)
severity: high
date: 2026-06-17
---

## Symptom

book-dp2's `tab:convergence_cases` (rendered as Table 2.1) is a plain
`tabular` whose every data cell is a `\ding{51}` checkmark. The converted
`ch_adps.md` list-table had the row labels present but **every check cell
empty** — the table conveyed nothing:

```
* - Regular
  -
  -
  -
```

The same drop removed the circled step numbers (`\ding{172}`, `\ding{173}`)
from the FDP diagram.

## Cause

`\ding{N}` comes from `pifont` via `\usepackage`. Pandoc has no handler for
it, so it silently drops the macro along with its argument (the
lesson [028](028-preamble-text-macros-pandoc-silently-drops.md) family).
Lesson 028 only *warns* and suggests a per-book `preprocess.rewrites` rule;
left un-applied, the default is a blank cell — strictly worse than the
correct ✓, since the loss is invisible to every structural count.

The mapping `\ding{51}`→✓, `\ding{55}`→✗, `\ding{172}`–`{181}`→①–⑩ is
unambiguous and lossless, so it is now **auto-applied** pre-pandoc. The
non-obvious part is *ordering*: the table and figure preprocessors
(`_apply_table_markers.py`, `_apply_figure_markers.py`) extract each cell's
content into a base64-encoded marker payload that is later batch-converted
through pandoc. If the glyph substitution runs *after* marker extraction,
the `\ding{51}` is already sealed inside the payload, and the batch pandoc
pass drops it exactly as the inline reader would — re-introducing the blank
cell. The substitution therefore has to happen **before** any marker
preprocessor sees the cell.

## Fix

`scripts/_apply_pifont_glyphs.py` calls
`_warn_dropped_text_macros.apply_known_glyphs`, which rewrites every
`\ding{N}` whose `N` has a registered glyph and leaves unmapped args (and
the arg-less / open-ended families like `\faIcon`) for the warn path. It is
wired into `preprocess.sh` immediately after `_apply_rewrites.py` and before
the marker scripts:

```bash
python3 "$SCRIPT_DIR/_apply_rewrites.py" "$CONFIG" "$dst"
python3 "$SCRIPT_DIR/_apply_pifont_glyphs.py" "$dst"   # before table/figure markers
python3 "$SCRIPT_DIR/_apply_prf_title_markers.py" "$dst"
# … _apply_table_markers.py, _apply_figure_markers.py, …
```

Only text-mode macros are auto-applied: a bare ✓ inside `$…$` would break
KaTeX, so math-capable macros (`\checkmark`) stay warn-only. The
`tests/test_golden_tex.py` driver's `_MARKER_SCRIPTS` list mirrors this
ordering, so the golden case `pifont_ding_in_table` would catch a
regression if the pass were moved after the markers.

## How to detect

A `tabular` cell that is *only* a dropped macro converts to an empty
list-table row. Grep the source for pifont usage, then check the output
table isn't hollow:

```bash
grep -rn '\\ding{' SRC/*.tex            # any pifont glyphs in the source?
grep -nA3 ':name: tab-' mystmd/*.md     # … and the rendered cells aren't blank
```
