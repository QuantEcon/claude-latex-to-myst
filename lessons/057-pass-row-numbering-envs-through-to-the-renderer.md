---
id: 057
title: "Once the renderer numbers align rows natively, pass the environment through instead of rewriting it — but the labels must stay IN the body, colon-normalised in place"
category: post-processing
tags: [math, align, equation-numbering, passthrough, labels, qe-v9, upstream]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/transforms/math.py::_can_passthrough_rows / _emit_passthrough_rows / _normalize_labels_in_place
severity: high
date: 2026-08-13
---

## Symptom

A multi-row `align` was rewritten to `$$\begin{aligned}…\end{aligned}$$`,
which mystmd numbers **once**. LaTeX numbers each row. The deep-learning
book's HTML therefore matched the printed PDF on **255 of 272** equations,
and every equation after the first collapsed block in a chapter was shifted.

## What changed

`qe-v9` (QuantEcon/mystmd#81) numbers each `\\` row of a non-starred
`align` / `gather` / `alignat` — honouring per-row `\label`, `\tag` and
`\nonumber` — **with the shared `&` axis preserved**, because the whole
environment stays one KaTeX layout.

That dissolved the tradeoff the converter had been built around. The old
choice was *numbering parity* (split the rows, lose the alignment) **or**
*alignment* (collapse to `aligned`, lose the numbers). Both are now
available, so the converter should stop choosing: pass the environment
through and let the renderer do it.

Result: **272/272, all twelve chapters exact.** Verified positionally too,
not just by count — the PDF prints the LSTM forget gate as (1.25) and
passthrough assigns 1.25, where the old output said 1.21.

## The trap: labels must stay IN the body

`_extract_math_labels` had pulled `\label{}` out of every math body since
#30, because KaTeX silently drops it and an extracted label is the only way
to get a MyST anchor. **Under passthrough that is exactly backwards.**
mystmd reads a row's reference target out of the math source itself
(`mathRows.ts`, `LABEL_PATTERN`) and from nowhere else — so extracting the
label leaves the row with no target, and every `{eq}` to it dangles.

And leaving it verbatim is not enough either. mystmd's `normalizeLabel`
lowercases but does **not** map `:` → `-` (only `createHtmlId` does), so a
raw `\label{eq:foo}` registers the identifier `eq:foo` while the converter's
own `{eq}` roles have already been dashified — all 25 align-internal labels
in the deep-learning book dangle. The label must be **rewritten in place**:
`\label{eq:foo}` → `\label{eq-foo}`, still in the body.

Corollary: a leading `\begin{align}\label{X}` goes back into the body too,
rather than becoming a separate `(X)=` anchor. In amsmath it labels the
first row, mystmd registers it from there, and emitting both produces
`Duplicate identifier in file`.

## What must NOT be passed through

Passthrough is *narrowed to the shapes that used to collapse* — everything
`_align_needs_split` already claimed keeps the split path. That is not
timidity; each exclusion is a measured regression:

- **≥2 `\tag`** — mystmd sets `row.enumerator = row.tag` **raw**, with no
  equivalent of `_normalize_tag_text`, so a `{eq}` reference renders
  `(\text{(capital Euler)})` instead of `(capital Euler)`.
- **≥2 `\label`** — `registerRowTarget` gives every row the *block's*
  `html_id`, so row references scroll to the block rather than the row.
  Keeping these on the split path preserves the distinct anchors, and costs
  nothing: 9 of the 10 collapsing blocks carry no label, so the split-path
  set contributes **0** of the 17 recovered numbers.
- **`\intertext`** — passed through, it is a hard render failure: the whole
  display vanishes while its rows still consume numbers, silently
  desynchronising the counter.
- **`align*`** — mystmd only forces `enumerated: false` when the node has no
  identifier, so a *labelled* `align*` would take a real number, the
  opposite of amsmath. Keep the #113 `{math}` wrapper. (dp1's
  `ch_ctime.tex` `eq:vgctp` is exactly this shape.)
- **`%` comments** — a comment row is counted, but the injected `\tag` lands
  on the commented line, so the number is consumed and never displayed.

## The general rule

**When an upstream renderer gains a capability the converter was
compensating for, the compensation does not simply get deleted — check what
the renderer needs as *input*.** Here the converter had been removing
precisely the thing (`\label` in the body) that the new renderer path reads.
A deletion-only migration would have produced correct numbers and dangling
references everywhere.

Verify the same way: build both variants and diff against ground truth
outside the pipeline — the compiled PDF, not our own counter.

## Related

- #186, QuantEcon/mystmd#73 (the request), QuantEcon/mystmd#81 (the fix)
- Lesson [055](055-amsmath-row-numbering-tokens-unmodelled.md) — the token
  modelling that stays live for every path passthrough does not cover.
- Lesson [056](056-math-row-splitting-must-be-depth-aware.md) — our own
  depth-aware scan, still the guard deciding what is safe to pass through.
- Lesson [032](032-per-row-align-labels-lost-as-anchors.md) — the
  extract-the-label rule this narrows.
