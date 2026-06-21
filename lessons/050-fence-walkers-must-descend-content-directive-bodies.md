---
id: 050
title: "fence-walking math/typography passes must treat `{prf:*}` (content) directives as transparent, not as opaque code fences — otherwise prose inside theorem/proof/example bodies is silently skipped"
category: post-processing
tags: [dashes, en-dash, em-dash, inline-math, line-break, fence-stack, prf, collapse_inline_math_newlines, convert_latex_dashes]
source_project: claude-latex-to-myst (issue #174, from book-dp-public#29 / book-dp2)
status: codified
codified_in: scripts/transforms/math.py::_update_fence_stack (collapse_inline_math_newlines, join_split_inline_math); scripts/transforms/typography.py::convert_latex_dashes
severity: medium
date: 2026-06-21
---

## Symptom

After #168 (collapse inline `$…$` spanning a hard line break) and #1 (dash
conversion) were both believed complete, ~15 literal `--`/`---` survived in
book-dp2 output. Three shapes:

- En-dash in `{prf:theorem}` **titles**: `` ```{prf:theorem} Bolzano--Weierstrass ``
- Dash **adjacent to inline math** and en-dash **ranges** (`(i)--(ii)`,
  `Cauchy--Schwarz`) — but *only* when they sat inside a `{prf:proof}` /
  `{prf:example}` body. The identical shapes in top-level prose converted fine.

## Cause

Two independent fence-handling gaps, both about content directives:

1. **`collapse_inline_math_newlines` / `join_split_inline_math` (#168) treated
   every ``` `` ` ``` `` fence as opaque** via a naive `in_fence = not in_fence`
   toggle. A `` ```{prf:proof} `` opener flipped it into "inside fence" mode, so
   the entire proof body was passed through verbatim. An inline `$…$` span
   wrapping a hard line break inside the proof was therefore never collapsed —
   leaving a continuation line that (a) starts with a dangling closing `$`,
   throwing the dash pass's per-line `$`-pairing off by one (parity-dependent:
   some `--` survive, some don't), and (b) carries pandoc's 4-space hanging
   indent, which the dash pass skips as an indented code block. Top-level prose
   has no enclosing fence, so #168 already collapsed it — hence only
   directive-body cases leaked.

2. **`convert_latex_dashes` never substituted the fence *opener* line.** Its
   lesson-040 fence stack classifies the opener (`prose` vs `verbatim`) and
   pushes it, but then did `out.append(line)` verbatim — so a prose directive's
   **argument** (the theorem title carried on the opener line) was always
   skipped.

The unifying rule both passes violated: a fence walker must distinguish a
**code-bearing** fence (plain ```` ``` ````, ```` ```python ````, or a
`_CODE_DIRECTIVE_NAMES` / `_DASH_VERBATIM_DIRECTIVES` directive — opaque) from
a **content** directive (`{prf:*}`, admonitions — body is prose/math the pass
must reach). A boolean toggle cannot express this and cannot match a bare ```` ``` ````
closer to the right opener; only a `(ticks, kind)` stack can.

## Fix

- math.py: a shared `_update_fence_stack` (mirroring the stack already in
  `fix_spacing_superscript`) replaces the boolean in both
  `collapse_inline_math_newlines` and `join_split_inline_math`. Only `kind ==
  'code'` frames are opaque; `{prf:*}` bodies are descended into, so the inline
  span collapses there too.
- typography.py: in `convert_latex_dashes`, a `prose`-kind opener now has the
  text after its `}` run through `_dash_sub_line` (which still protects `$…$` /
  inline code in the title). The `{directive}` token and verbatim openers stay
  byte-identical.

Both are count-neutral and pass the dp2 render gate unchanged.

## How to detect

Grep converted output for residual ligatures outside front-matter / table
rules — including inside directive bodies and on opener lines:

```bash
grep -nE '[^-]-{2,3}[^-]' output/*.md | grep -vE ':\s*---\s*$|\|[-:]+\|'
```

A regression in the collapse pass shows up as a markdown line that *starts*
with a closing `$` (inline math opened on the previous physical line):

```bash
grep -nE '^\s*[^$`]*[^\\]\$[^$]' output/*.md   # continuation line opening mid-math
```
