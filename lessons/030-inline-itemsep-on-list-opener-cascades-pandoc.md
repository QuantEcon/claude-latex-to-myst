---
id: 030
title: "Inline \\itemsep<dim> on a list opener cascades into 'Unknown environment' when nested"
category: preprocess
tags: [pandoc, itemize, enumerate, itemsep, nesting, figure-drop]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/_apply_rewrites.py
severity: medium
date: 2026-05-24
---

## Symptom

Source LaTeX using the common manuscript shorthand for tighter item
spacing:

```latex
\begin{description}
\item[Hard constraints.] Body...
  \begin{itemize}\itemsep1pt
  \item resource equation
  \item economic requirements
  \end{itemize}
\item[Soft constraint.] Body.
\end{description}
```

produced pandoc output that began with `% Unknown environment: itemize`
and an orphan `sep1pt` line, then cascaded — every `{figure}` directive
later in the same chapter was silently dropped at MyST build time (6 of
the remaining figures in ch02 of the Deep-Learning book).

**Top-level uses are fine.** The same book has four
`\begin{itemize}\itemsep2pt` at top level (not nested); pandoc tolerates
them and the build is clean. Only the *nested* combination breaks.

## Cause

When pandoc sees `\begin{itemize}\itemsep1pt` it lexes `\itemsep` as a
single-argument macro (which it isn't — `\itemsep` is a TeX low-level
length, not a function-style command). It doesn't recognise the macro,
drops the command, but keeps the argument (`1pt`) as orphan text. The
opening env then has no `\item` lines following it, so pandoc falls
back to its unknown-environment rendering: `% Unknown environment:
itemize` followed by `::: itemize … :::`. That malformed fenced div
corrupts block context for the rest of the chapter; MyST's parser
drops every subsequent figure directive as unattachable.

Why nesting matters: at top level, pandoc's lexer recovers more
robustly because the surrounding context is paragraph-level. Nested
inside another list, the recovery path produces the broken fenced
div instead.

## Fix

`\itemsep` is a TeX low-level spacing command with no MyST analogue —
the formatting is purely visual. Strip it globally as a built-in in
[scripts/_apply_rewrites.py](../scripts/_apply_rewrites.py), alongside
the natbib rewrites:

```python
_ITEMSEP_STRIP = re.compile(
    r'\\itemsep\s*=?\s*-?[0-9.]+'
    r'(?:pt|em|ex|in|cm|mm|pc|bp|dd|cc|sp)\b'
    r'(?:\s*\\\\)?\s*'
)
# … in main()
text = _ITEMSEP_STRIP.sub('', text)
```

Handles the three shapes that appear in the wild:

- `\begin{itemize}\itemsep1pt` (no space)
- `\itemsep 3pt` (with space)
- `\itemsep=2em` (with equals)

…across any standard TeX length unit, and optionally consumes a
trailing `\\` line break that often follows the directive.

The strip does **not** touch `\setlength{\itemsep}{1pt}` — that's a
different shape that pandoc handles correctly (no bare `\itemsep`
token before the dimension). Tests in
[tests/test_preprocessors.py](../tests/test_preprocessors.py):
`test_itemsep_attached_to_itemize_open_stripped`,
`test_itemsep_strip_variants`,
`test_itemsep_strip_does_not_touch_setlength_form`,
`test_itemsep_strip_full_nested_example`.

## How to detect

After a pipeline run, grep the preprocessed `.tex` files:

```bash
grep -n '\\itemsep' mystmd/tmp/*.tex
```

A clean preprocess should have zero hits. Any hit indicates either a
variant the strip regex doesn't cover yet (file an issue) or a
`\setlength{\itemsep}{…}` form (which is fine — pandoc handles it).

## Generalizable rule

**Pandoc tolerates malformed input at top level but corrupts it when
nested.** Several lessons share this shape — orphan `\label{}` (024),
inline `\itemsep<dim>` (this one), and probably more to come. The
defensive posture is: strip any LaTeX construct that has no MyST
analogue **before pandoc sees it**, rather than trying to fix the
malformed output afterwards. Visual-only formatting commands
(`\itemsep`, `\itemindent`, `\listparindent`, `\topsep`) are all
candidates for the same preprocess strip if they show up in the next
book.

Why bake it into the pipeline rather than leave it to per-book
`preprocess.rewrites`: the failure mode is invisible (silent figure
drops in a chapter several sections later), so the user has no
feedback loop to discover the rule on their own. Anything that fails
silently at the cascade level belongs in the built-in strips.
