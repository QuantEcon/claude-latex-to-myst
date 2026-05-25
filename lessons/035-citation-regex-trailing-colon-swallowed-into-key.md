---
id: 035
title: "Citation regex trailing-``:`` swallowed into key after the #32 widening"
category: regex-safety
tags: [pandoc, citations, regex, regression]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_citations
severity: medium
date: 2026-05-26
---

## Symptom

Direct regression from lesson 031 / [#32]. That fix widened the
textual-citation regex to allow ``:`` *inside* bib keys
(JabRef/Mendeley/ACM-style ``Author:Year:Tag``). The boundary
lookahead was widened symmetrically to ``(?=[^a-zA-Z0-9_:]|$)`` — and
that's what broke prose like:

```latex
\citet{dietz2019cumulative}: explanation
```

Pandoc emits ``@dietz2019cumulative:`` with a trailing colon attached
(the colon is *prose punctuation*, not part of the key). The widened
regex sees ``:`` as a valid key char, the next char (` `) as a valid
boundary, and captures the colon into the key:

```
{cite:t}`dietz2019cumulative:`
                          ^^^ trailing colon belongs to prose
```

9 sites broken in the downstream book — including the particularly
visible ``ECTA:ECTA1716:`` case where the real key has 1 colon and
the regex captured 2.

## Cause

The constraint is asymmetric: ``:`` is legal *inside* a key but never
*at the end* (no real bib key ends in ``:``). The post-#32 regex did
not encode that asymmetry.

The boundary lookahead, separately, has its own trap: setting it to
``(?=[^a-zA-Z0-9_:]|$)`` means a trailing ``:`` in prose can no
longer serve as a key boundary either, because ``:`` is excluded from
the boundary set. Naive "exclude `:` from last char" without also
reverting the boundary gets you a deadlock where colon-followed keys
match nothing.

## Fix

Three coordinated changes, packaged as a single regex:

```python
r'(?<![`\[@])@([a-zA-Z][a-zA-Z0-9_:]*[a-zA-Z0-9_])(?=[^a-zA-Z0-9_]|$)'
```

1. **Capture pattern** ``[a-zA-Z][a-zA-Z0-9_:]*[a-zA-Z0-9_]``: enforces
   that the key *starts* with a letter, can contain ``:`` in the
   middle, but must *end* with an alphanumeric/underscore. The
   greedy ``*`` is backtracked by the regex engine to make the
   trailing-alphanumeric anchor work.
2. **Boundary reverted** to the pre-#32 form ``(?=[^a-zA-Z0-9_]|$)``.
   ``:`` is now a valid boundary char again, so trailing-colon prose
   terminates the match cleanly.
3. **Dropped the legacy** ``(?:\d{4}[a-zA-Z]?)?`` tail that was
   already subsumed and never load-bearing.

Trace examples:

| Input                                 | Captured                    |
|---------------------------------------|-----------------------------|
| `@dietz2019cumulative: foo`           | `dietz2019cumulative`       |
| `@ECTA:ECTA1716:`                     | `ECTA:ECTA1716`             |
| `@author:2020:tag and ...`            | `author:2020:tag`           |
| `@Smith2020.`                         | `Smith2020`                 |
| `@Bertsekas:2000:DPO:517430`          | `Bertsekas:2000:DPO:517430` |

Tests in `tests/test_transforms.py::test_citation_textual_key_boundary`
(parametrized over 6 cases covering plain keys, colon-bearing keys,
and the trailing-prose-punctuation set).

## Why the original #32 fix slipped this

The #32 review explicitly weighed "minimal symmetric change"
(widen key class + widen boundary class) against the issue's
proposal (positive boundary set with sentence-punctuation). Minimal
symmetric *seemed* safer because the change was small and the only
test cases on the table were happy-path colon keys. The
prose-colon-after-key case never showed up — and the parametrized
test added with #32 didn't cover trailing punctuation other than `.`.

## Generalizable rule

**Asymmetric character constraints need to be encoded asymmetrically
in the regex.** If a char (``:`` here) is legal in the middle of a
token but illegal at the boundary, the capture group must reflect
that — not just the character class. The cheap way is an anchor on
the last char: ``[middle-chars]*[boundary-safe-char]``.

And — when widening a regex's capture set, always widen the
parametrized test set to match. The #32 tests had 5 cases for the
colon-bearing positive path and 1 for the trailing-period
boundary. They should have also covered trailing-`:`,
trailing-`;`, trailing-`)`, etc. A widening that doesn't also
widen the test parametrize is a regression waiting to surface.
