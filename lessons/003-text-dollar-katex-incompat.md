---
id: 003
title: "KaTeX cannot parse $ inside \\text{...}"
category: katex
tags: [katex, math, text-dollar]
source_project: book-dp2
status: codified
codified_in: postprocess.py::fix_text_dollar
severity: high
date: 2026-04-09
---

## Symptom

46 math-parse errors across all chapters of `book-dp2`. Affected equations
fail to render and show raw LaTeX in the HTML output.

## Cause

LaTeX (with MathJax) accepts `$` inside `\text{}` to switch back to math
mode:

```latex
\text{a $x$ b}
```

KaTeX, which MyST uses for HTML math rendering, rejects this. The `$`
inside `\text{}` is a parse error.

## Fix

Brace-depth-aware splitter that converts `\text{...$math$...}` to
`\text{...} math \text{...}`. Must be brace-depth-aware because `\text{f(\hat{x})}`
contains nested braces that are *not* `\text` boundaries.

```python
def fix_text_dollar(text):
    # See postprocess.py::fix_text_dollar for the full implementation —
    # roughly 50 lines, tracking brace depth and $-pairs inside \text{}.
```

This transform must run **first** in the pipeline, before equation conversion
changes the `$$` structure.

## How to detect

```bash
grep -nE '\\text\{[^}]*\$' ch_*.tex
```

Any match is a candidate for breakage. Also run `myst build --html 2>&1 | grep math_parse`
after the first conversion pass.
