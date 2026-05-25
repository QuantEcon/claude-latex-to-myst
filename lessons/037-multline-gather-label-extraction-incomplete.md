---
id: 037
title: "``\\label{}`` extraction not applied to ``multline`` / ``gather`` (incompleteness from #30)"
category: post-processing
tags: [katex, equations, multline, gather, labels, cross-refs, regression]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_equations
severity: low
date: 2026-05-26
---

## Symptom

Incompleteness from lesson 032 / [#30]. That fix wired the
``_extract_align_labels`` helper into the two ``align`` handlers but
left the ``multline`` and ``gather`` handlers using the original
"label immediately after ``\begin``" assumption — the same shape of
bug that [#26] originally fixed for ``equation``, just not refactored
at the same time.

Source like:

```latex
\begin{multline}
a + b \\
+ c = d
\label{eq:foo}
\end{multline}
```

— the dominant LaTeX convention for ``multline``, with the label at
the *end* of the body — passed through:

1. The labeled-multline regex required ``\label{}`` right after
   ``\begin{multline}\s*``. Didn't match here.
2. The unlabeled-multline regex picked up the block and called
   ``replace_unlabeled_equation``, which wrapped as ``$$…$$``
   *without extracting the label*.
3. The label survived inside the math body. KaTeX silently drops it.
   Any ``\eqref{eq:foo}`` resolved to nothing.

Surfaced in the downstream Deep-Learning book: 1 broken ``{eq}``
ref (``eq-irbc_foc_k_raw``) — the only multline in the book.
``gather`` had no broken refs in this book but the same shape
applies for per-row-labelled gather (a common pattern in physics
manuscripts).

## Fix

Same shape as #30: extract every ``\label{}`` from the body
regardless of position; first label becomes the block's trailing
``(label)``; any additional labels stack as anchors above. The
helper from #30 was renamed ``_extract_align_labels`` →
``_extract_math_labels`` since it now serves three math envs.

Collapsed each env's previous labeled-/-unlabeled regex pair into a
single unified handler that always extracts:

```python
def replace_math_block(m):
    content, labels = _extract_math_labels(m.group(1).strip())
    block = f'$$\n{content}\n$$'
    if not labels:
        return block
    leading = convert_label_colons(labels[0])
    block = f'{block} ({leading})'
    extra = labels[1:]
    if extra:
        anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in extra)
        return f'{anchors}\n{block}'
    return block
```

Applied to both ``multline`` and ``gather``. The ``equation`` env
already used a single-pass extraction (#26); ``align`` got the same
treatment in #30; ``multline`` / ``gather`` close the set.

Tests in `tests/test_transforms.py`:
`test_convert_equations_multline_trailing_label_extracted`,
`test_convert_equations_multline_no_label_unchanged`,
`test_convert_equations_gather_per_row_labels`.

## Why the original #30 fix slipped this

The #30 issue explicitly named ``align``, and the immediate test
fixture was ``align``. The pattern "extract every ``\label{}`` from
a multi-line math env body" generalises to ``multline`` and
``gather``, but the #30 fix scope didn't extend that far. Should
have — both envs were carrying the same shape of unfixed bug.

## Generalizable rule

**When fixing a regex bug in one of a family of similar handlers,
audit the rest of the family in the same commit.** The four
math-env families in this codebase — ``equation``, ``align``,
``multline``, ``gather`` — share enough structure that a bug in
one is almost always present in the others. The original #26 fixed
``equation``; #30 fixed ``align``; #37 fixed ``multline`` and
``gather``. Three commits to close a single class of bug. The
discipline going forward: when touching one math-env handler,
sanity-check the body-scan against all four.
