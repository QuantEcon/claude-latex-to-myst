---
id: 002
title: "Cross-ref regex consumes equation blocks via [0,1) bracket false-match"
category: regex-safety
tags: [regex, cross-references, pandoc, long-lines]
source_project: book-dp2
status: codified
codified_in: postprocess.py::convert_cross_references
severity: high
date: 2026-04-09
---

## Symptom

Entire equation blocks and surrounding text disappear from the output.
Equations like `eq-sce` and `eq-badp` lost without any error message — the
output simply doesn't contain them.

## Cause

With `pandoc --wrap=none`, lines can be thousands of characters long. The
cross-reference regex used `[^\]]*` for the link-text portion of a pattern
like `\[([^\]]+)\]\(#([^\)]+)\)`. Inside a long line, a literal `[` in math
content like `$\lambda \in [0,1)$` paired with a later
`[\[l:bw0\]](#l:bw0){reference-type=ref}` cross-reference — consuming
hundreds of characters of equation content as the "link text."

This is the most insidious bug from the dp2 conversion because the *symptom*
(equations vanishing) gave no hint that the cross-reference converter was
responsible.

## Fix

Exclude `$` and `\n` from the character class:

```python
# WRONG — matches across $ boundaries and newlines
re.compile(r'\[([^\]]+)\]\(#([^\)]+)\)\{reference-type="([^"]+)"[^}]*\}')

# RIGHT — refuses to cross structural boundaries
re.compile(r'\[([^\]\n$]+)\]\(#([^\)]+)\)\{reference-type="([^"]+)"[^}]*\}')
```

## How to detect

After conversion, diff equation labels between source and output:

```bash
grep -oE '\\label\{eq:[^}]+\}' ch_*.tex | sort -u > expected.txt
grep -oE '\$\$\s+\(eq-[^)]+\)' mystmd/ch_*.md | sort -u > actual.txt
diff expected.txt actual.txt
```

Missing labels in `actual.txt` mean the regex ate them.

## General rule

When matching bracketed content on potentially long lines, **always exclude
structural delimiters** (`$`, `\n`, and sometimes `[`, `]` themselves) from
character classes. The "negation" character class is one of the easiest
regex constructs to get wrong on real-world data.
