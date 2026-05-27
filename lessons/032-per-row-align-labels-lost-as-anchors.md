---
id: 032
title: "Per-row \\label{} inside multi-row \\begin{align} — split into per-row $$ blocks (2+ labels) or stack above (≤1 label)"
category: post-processing
tags: [katex, equations, align, labels, cross-refs, myst-anchors]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/transforms/math.py::convert_equations
severity: high
date: 2026-05-25
updated: 2026-05-27
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

## Followup (#70 — 2026-05-27)

The "stacked anchors above one aligned block" fix above turned out
to be **broken in a different way**: MyST treats two or more
consecutive `(name)=` lines as competing labels for the same next
block element, collapses them to ONE anchor, and renames the rest
(the non-first labels survive as anchors but with auto-generated
names, NOT the names the source declared). Any `{eq}\`eq-X\`` to a
non-first label then dangles. Surfaced in dp-deep-learning's R7 pass:
15 collision cases across 5 chapters, 10 of which had a dangling
`{eq}` ref somewhere in the book.

The original lesson's claim that "broken anchors are much worse
than collapsed numbering" assumed the stacked-anchor approach
preserved every cross-reference. It didn't. Both the column-
alignment compromise AND the cross-ref breakage applied — the
worst combination.

**Updated approach (#70):**

- 0 or 1 per-row label / tag → keep the original `aligned` block
  (column alignment preserved, single anchor doesn't collide).
- 2+ per-row labels OR 2+ per-row `\tag*{}` → SPLIT into per-row
  `$$...$$` blocks each with its own trailing `(name)`. The `&`
  alignment is lost; cross-refs all resolve. Same split also
  resolves #46 (KaTeX `Multiple \tag` error on per-row `\tag*{}`
  inside `\begin{aligned}`).

The split logic lives in `_align_needs_split` / `_split_align_rows`
/ `_emit_split_align` inside `convert_equations`.

Tests in `tests/test_transforms.py`:
`test_convert_equations_multirow_align_per_row_labels_emit_anchors`,
`test_convert_equations_align_leading_plus_per_row_labels`,
`test_convert_equations_align_no_labels_unchanged_shape`,
`test_convert_equations_align_2plus_per_row_labels_splits_to_avoid_collision`,
`test_convert_equations_align_2plus_tags_splits_to_avoid_multiple_tag_error`,
`test_convert_equations_align_leading_plus_2plus_per_row_splits`.

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
