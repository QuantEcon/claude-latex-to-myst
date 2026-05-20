---
id: 013
title: "MyST cannot resolve {ref}`fn-name` to footnote anchors"
category: myst
tags: [footnotes, cross-references, myst-limitation]
source_project: book-dp1 (parity test)
status: codified
codified_in: postprocess.py::strip_footnote_refs
severity: low
date: 2026-05-20
---

## Symptom

`myst build` warns about unresolved cross-references targeting footnote
anchors like `{ref}`fn-clarity-on-action-restrictions``. The warnings come
from prose like "see footnote {ref}`fn-foo` for details".

## Cause

In MyST, footnote anchors (`[^1]: footnote text`) live in a *separate
identifier namespace* from the cross-reference system. `{ref}`fn-NAME``
will always fail to resolve, regardless of whether the footnote itself
exists. This is a MyST limitation, not a fixable bug in the conversion.

## Fix

Drop the unresolvable `{ref}` role and replace the surrounding phrase with
"the previous footnote", while preserving the original LaTeX target in an
HTML comment for lossless round-tripping:

```python
pattern = re.compile(r'\bfootnote\s+\{ref\}`fn-([A-Za-z0-9_-]+)`')

def repl(m):
    name = m.group(1)
    original = name.replace('-', ':')
    return f'the previous footnote <!-- LaTeX-source: \\ref{{fn:{original}}} -->'
```

The HTML comment doesn't render but keeps the original `\ref{fn:...}`
target visible to anyone inspecting the source.

## How to detect

```bash
myst build --html 2>&1 | grep -E '\bfn-[a-zA-Z]'
```

Any matches indicate unresolved footnote refs the transform missed.

## Note

If a future MyST release unifies the namespaces, this transform becomes
obsolete and should be removed (not just bypassed).
