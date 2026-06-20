---
id: 049
title: "multicols two-column layout needs a MyST {grid} — pandoc mangles literal ::: markup, so reproduce columns via the marker pattern"
category: post-processing
tags: [multicols, grid, columns, layout, markers, enumerate, fidelity]
source_project: book-dp1
status: codified
codified_in: scripts/_apply_multicols_grid.py + scripts/transforms/multicols.py::resolve_multicols_grid
severity: medium
date: 2026-06-20
---

## Symptom

book-dp1 pairs math statements with their property names using a
`multicols{2}` + custom-label `enumerate`: the first half of the items are the
statements `(a)–(d)`, the second half the matching `\item[]` names. `multicols`
balances the 8 items 4-and-4, so each statement sits beside its name in the
PDF. In MyST/HTML the items flowed into one stacked column — every name ended
up below all the statements, divorced from the statement it belongs to.

    \begin{multicols}{2}
      \begin{enumerate}
        \item[(a)] $\| u \| \geq 0$           % statements …
        \item[(b)] $\| u \| = 0 \iff u = 0$
        \item[] (nonnegativity)               % … then names
        \item[] (positive definiteness)
      \end{enumerate}
    \end{multicols}

This was the unfinished layout half of #111 (which fixed the custom `(a)–(d)`
labels and the stray column-count "2" leak, but not the column layout).

## Cause

`multicols` is in `DEFAULT_ENV_SKIP` — the wrapper is dropped and the content
kept, which collapses N columns into one. MyST has no `multicols` primitive.
The obvious fix — emit a MyST `{grid}` — can't be done by passing literal
`:::{grid}` markup through pandoc: pandoc reads LaTeX input, so it treats the
markup as prose and **mangles** it (`::::{grid}` → `::::grid`, `(b)` → `\(b\)`,
closing `:::` glued to content). And CommonMark grid cells flow **row-first**,
so 8 grid-items in a `{grid} 2` would pair (a)|(b), not (a)|(nonnegativity).

## Fix

Reproduce the layout with the marker pattern (the sanctioned route for
structure pandoc can't carry):

- `_apply_multicols_grid.py` (pre-pandoc) extracts a `multicols` wrapping a
  custom-label enumerate, batch-converts each item LaTeX→markdown
  (`pandoc_batch_convert`, `~` paren-guard so a leading `(a)` isn't read as
  `\(a\)`), and emits a `<!--MULTICOLSGRID-->` marker.
- `resolve_multicols_grid` (post-pandoc) splits the items **column-first** into
  N balanced groups and emits **one `{grid-item}` per column** inside a
  responsive `::::{grid} 1 1 N N`. One grid-item = one stacked column, so the
  browser lines (a) up beside (nonnegativity) — matching `multicols`.

Two ordering facts made it work:

1. The pass must run **after `_apply_rewrites`** (so a cell's custom macros are
   already rewritten) but with the `{N}` count **still present** — so the #111
   column-count strip + `[pre-text]` hoist was **moved out of `_apply_rewrites`
   into this same pass**. One pass now owns all `multicols` handling.
2. `resolve_multicols_grid` runs **after `convert_environment_divs`** (so its
   `:::` grid fences aren't mistaken for pandoc env divs) and **before** the
   cross-ref / cite passes (so a ref in a cell is still processed).

Conservative bail (the marker doctrine): only a `multicols` whose body is a
single custom-label enumerate (surrounded by nothing but
whitespace/`\setlength`/`\label`/comments) is gridded; wrapped tabulars,
backmatter prose, auto-counter lists, and nested `multicols` fall through to
the column-strip + `ENV_SKIP` path unchanged.

## Takeaway

A LaTeX *layout* construct with no MyST primitive isn't "drop the wrapper" —
map it to the closest MyST layout (`{grid}`) via the marker pattern, and mind
the cell flow direction: column-first source data needs one cell **per
column**, not one cell per item. Reported in QuantEcon/book-dp-public#26 (item
11) and #27 (item 3).
