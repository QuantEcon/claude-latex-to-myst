---
id: 001
title: "Blank lines inside $$ math blocks silently terminate them"
category: post-processing
tags: [katex, equations, myst-parser]
source_project: book-dp2
status: codified
codified_in: postprocess.py::convert_equations
severity: high
date: 2026-04-09
---

## Symptom

Display-math blocks render as raw LaTeX in the built HTML. In `book-dp2` this
affected ~696 equations on the first end-to-end build — by far the largest
single source of broken output.

## Cause

Pandoc emits blank lines inside multi-line equations (for example between
`\right].` and the closing `$$`). MyST treats any blank line as a block
terminator, so the equation splits in two and the math context is lost.

The LaTeX source has no blank lines inside the equation; pandoc introduces
them when converting `\begin{equation}` / `\end{equation}` to `$$ ... $$`.

## Fix

Final pass inside `convert_equations`: track an `in_math` flag toggled on
every `$$` line; drop blank lines while inside math.

```python
def _strip_blanks_in_math(text):
    out = []
    in_math = False
    for line in text.split('\n'):
        if line.strip() == '$$':
            in_math = not in_math
            out.append(line)
        elif in_math and not line.strip():
            continue   # drop blank line inside $$
        else:
            out.append(line)
    return '\n'.join(out)
```

## How to detect

Visual inspection of the *markdown* won't catch this — the broken block looks
fine to a human reader. Only the built HTML reveals it. Run
`myst build --html` and grep the HTML for raw `\begin{` markers.
