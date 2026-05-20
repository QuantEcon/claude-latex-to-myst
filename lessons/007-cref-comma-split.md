---
id: 007
title: "\\cref{a,b,c} becomes a single broken pandoc link"
category: post-processing
tags: [cross-references, cleveref, pandoc]
source_project: book-dp2
status: codified
codified_in: postprocess.py::convert_cross_references
severity: medium
date: 2026-04-12
---

## Symptom

17 cross-references unresolved in `book-dp2`, with target names like
`a-feba,a-firms` and `eq-x,eq-y`.

## Cause

Cleveref allows multiple targets:

```latex
See \cref{a:feba, a:firms} for the assumptions.
```

Pandoc collapses this into a single bracketed link whose anchor is the comma-
joined string. The label converter then runs colon-to-hyphen on the whole
thing, producing a nonsense label like `a-feba,a-firms`.

## Fix

In the cross-reference converter, after extracting the target, split on
commas and emit one MyST ref per key, joined with `, `:

```python
targets = [t.strip() for t in match.group('target').split(',')]
refs = [f'{{prf:ref}}`{convert_label_colons(t)}`' for t in targets]
return ', '.join(refs)
```

## How to detect

```bash
grep -E '\{(prf:)?ref\}`[^`]*,[^`]*`' mystmd/*.md
```

Any match has a comma inside what should be a single label — broken.
