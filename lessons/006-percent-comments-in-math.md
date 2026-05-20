---
id: 006
title: "LaTeX % comments inside math blocks break KaTeX"
category: katex
tags: [katex, comments, math]
source_project: book-dp2
status: codified
codified_in: postprocess.py::cleanup_typography
severity: low
date: 2026-05-15
---

## Symptom

`commentAtEnd` warnings during `myst build`. For TikZ-style math
environments like `tikzcd`, this escalates to a hard parse error.

## Cause

Pandoc preserves LaTeX `%` comments verbatim inside math blocks. KaTeX
rejects `%` comments entirely (LaTeX accepts them).

## Fix

Strip standalone `%` lines in the cleanup phase:

```python
text = re.sub(r'^\s*%\s*$\n?', '', text, flags=re.MULTILINE)
```

Only strips lines that are *entirely* a `%` comment — preserves inline
`%`s that are inside text (rare but possible).

## How to detect

```bash
myst build --html 2>&1 | grep -E 'commentAtEnd|tikzcd'
```
