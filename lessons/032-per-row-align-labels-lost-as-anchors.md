---
id: 032
title: "Per-row \\label{} inside multi-row \\begin{align} lost — extract to anchors above the block"
category: post-processing
tags: [katex, equations, align, labels, cross-refs]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_equations
severity: high
date: 2026-05-25
---

## Symptom

A multi-row `\begin{align}` where each row carries its own
`\label{eq:X}` survives pandoc untouched:

```
$$\begin{align}
\mu_{f,t+1} &= \frac{...}{...}, \label{eq:bayes_mean}\\
S_{f,t+1}   &= \frac{...}{...}, \label{eq:bayes_var}
\end{align}$$
```

`convert_equations`'s unlabeled-align branch wrapped this in
`\begin{aligned}` and left the `\label{}` tokens inside the math body.
KaTeX silently drops `\label{}` — no anchor is emitted, so any
`\eqref{eq:bayes_mean}` elsewhere becomes a `{eq}` directive
resolving to nothing.

In the downstream Deep-Learning book: 18 unique labels across 4
chapters, **>30 broken `{eq}` cross-references** in the rendered HTML.

The standalone-label cleanup regex at `convert_equations` (the
single-line version installed by [#26][024]) does not pick these up
because the labels sit inside a multi-line `$$ ... $$` block —
which is correct: a DOTALL form there caused the math-swallow bug
that motivated lesson 024 in the first place.

## Cause

The labeled-align branch only matched `\label{}` immediately after
`\begin{align}` (single block-level label). The unlabeled branch
matched everything else and made no attempt to find labels in the
body. Per-row labels — semantically distinct cross-ref anchors for
each numbered line of a derivation — fell through both branches.

`\begin{aligned}` itself accepts no labels (it's a math-mode-only
environment); KaTeX has no way to honour them and renders the
TeX-level `\label{X}` as a silent no-op.

## Fix

Extract every `\label{}` from the align body in **both** the labeled
and unlabeled branches; emit each one as a `(eq-X)=` MyST anchor
above the `$$ ... $$` block:

```python
def _extract_align_labels(content):
    labels = re.findall(r'\\label\{([^}]+)\}', content)
    content = re.sub(r'\\label\{[^}]+\}', '', content).strip()
    return content, labels
```

Then in `replace_unlabeled_align`:

```python
content, labels = _extract_align_labels(m.group(1).strip())
block = f'$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$'
if labels:
    anchors = '\n'.join(f'({convert_label_colons(lbl)})=' for lbl in labels)
    return f'{anchors}\n{block}'
return block
```

`replace_labeled_align` keeps the existing trailing-`(label)` shape
for the leading label and stacks any additional per-row labels as
anchors above.

**Tradeoff (deliberate):** all per-row anchors target the *same*
math block, so the eq-number rendered by sphinx-proof / MyST is
identical for every label. This collapses the per-row numbering the
original LaTeX had — but it preserves every cross-reference. The
alternative (split each labelled row into its own `$$ ... $$` block)
breaks the `\begin{aligned}` alignment, which is the visual reason
the author used `align` in the first place. Broken anchors are
much worse than collapsed numbering.

Tests in `tests/test_transforms.py`:
`test_convert_equations_multirow_align_per_row_labels_emit_anchors`,
`test_convert_equations_align_leading_plus_per_row_labels`,
`test_convert_equations_align_no_labels_unchanged_shape`.

## How to detect

After a pipeline run, grep the produced MyST for surviving label
markers inside math:

```bash
grep -nE '\\\\label\{' mystmd/*.md
```

A clean run has zero hits — every `\label{}` has been extracted to
either a trailing `$$ (name)` or a leading `(name)=` anchor.

## Generalizable rule

**Pandoc transparently passes LaTeX tokens it doesn't understand
into math blocks.** `\label{}`, `\tag{}`, `\nonumber`, `\eqlabel{}` —
all are quietly preserved by pandoc and silently dropped by KaTeX.
Whenever a LaTeX *labeling* construct is meaningful at the source
level, the postprocess pass must extract it from the math body
before MyST sees it; otherwise the cross-ref target vanishes.
Multi-row `align` is the most common shape, but the same problem
applies to `gather` (legitimately per-row labelled) and any custom
align-like macro.
