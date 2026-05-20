---
id: 011
title: "Strip prose noun before {prf:ref} — sphinx-proof auto-renders it"
category: post-processing
tags: [cross-references, sphinx-proof, katex]
source_project: book-dp1 (parity test against extracted pipeline)
status: codified
codified_in: postprocess.py::strip_doubled_noun_refs
severity: medium
date: 2026-05-20
---

## Symptom

Output contains phrases like "Theorem Theorem 1.2", "Exercise Exercise 3.5",
"Chapter Chapter 4". Surfaced in dp1 parity test: 727 occurrences in our raw
output vs 164 in their cleaned output — a delta of 563 places.

## Cause

LaTeX writers ubiquitously prefix the noun before `\cref{}` / `\ref{}` because
LaTeX's cref doesn't always auto-name the target object reliably. In MyST,
`{prf:ref}` *always* auto-renders the noun ("Theorem 1.2"), so the prose
prefix is redundant.

A second subtlety: most LaTeX writers use `~` (non-breaking space) between
the noun and the ref to keep them on one line. Pandoc preserves `~` as
U+00A0 in the output, so a naive `'Theorem '` pattern won't match — the
space character there is ` `, not ` `.

## Fix

`strip_doubled_noun_refs` walks a list of (noun, label_prefix) pairs and
drops the noun when it's followed by a `{prf:ref}` to a label that starts
with the corresponding prefix:

```python
_DOUBLED_NOUN_REFS = [
    ('Algorithm',   'algo-'),
    ('Theorem',     't-'),
    ('Exercise',    'ex-'),
    # ...
]

# Negative lookbehind on \w prevents touching "Subtheorem ..."
# `[ \xa0]+` matches regular space OR non-breaking space.
re.sub(
    rf'(?<!\w){re.escape(noun)}[ \xa0]+'
    rf'(\{{prf:ref\}}`{re.escape(prefix)}[^`]+`)',
    r'\1', text,
)
```

The label-prefix check matters: it prevents stripping "Theorem ..." in front
of a ref to a non-theorem object. Without it, a writer's stray prose would
silently lose words.

Pipeline order: runs immediately after `convert_cross_references` so the
`{prf:ref}` refs are already in MyST form.

## How to detect

```bash
python3 -c "
import re, sys
PAT = re.compile(r'\b(Theorem|Exercise|Chapter|Lemma|Proposition|Listing|Algorithm) +\{(prf:)?ref\}')
for f in sys.argv[1:]:
    n = len(PAT.findall(open(f).read()))
    if n: print(f'{f}: {n}')
" mystmd/ch_*.md
```

Or just grep visually for "Theorem {prf:ref}" — any nonzero count is suspect.
