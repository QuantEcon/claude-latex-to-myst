---
id: 055
title: "amsmath row-numbering tokens (\\nonumber, \\notag, \\tag*) are invisible to KaTeX and mystmd, so the converter must resolve them — a \\nonumber row is a CONTINUATION, and a \\tag REPLACES the number"
category: post-processing
tags: [math, align, equation-numbering, nonumber, notag, tag, enumerator, split-path, katex]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/transforms/math.py::convert_equations (_split_align_rows fuse-forward, _make_row_group, _lift_tag / _normalize_tag_text / _emit_tagged_math)
severity: high
date: 2026-08-13
---

## Symptom

Two distinct defects in the deep-learning book, both traced to the same
root cause: nothing downstream of the converter understands amsmath's
row-numbering tokens, so leaving them in the emitted MyST is not
"passing them through" — it is silently dropping the semantics.

**A. `\nonumber` tore one equation into two.** The per-row split path
(reached at ≥2 `\label{}` or ≥2 `\tag*{}`) split on every `\\`. A row
ending `\nonumber\\` is *unnumbered*, and in practice a continuation of
the row after it, so splitting there produced:

```markdown
$$
\frac{\partial \mathcal{L}}{\partial k_{t+1}} = 0 \; \Leftrightarrow\;
\exp\!\bigl(...\bigr)\,\hat{\lambda}_t - \hat{\beta}_t\Bigl\{\hat{\lambda}_{t+1}\bigl[...\bigr] \nonumber
$$

$$
\quad + \hat{\nu}^{\mathrm{AT}}_{t+1}\,...\Bigr\} = 0
$$ (eq-iam_foc_k)
```

`\Bigl\{` opened and never closed; an orphan `\Bigr\}` in the next
block; a dangling leading `\quad +`; and the label landing on the
**tail fragment**, so all three `{eq}` references to `eq-iam_foc_k` in
the prose pointed at half an expression. The unlabelled first block also
consumed an equation number LaTeX never assigns.

**B. `\tag*` showed a tag *and* a number.** `\tag*{}` was left in the
row body while the block still got a trailing `(label)`, so mystmd
numbered it too. The reader saw both "(capital Euler)" and "(11.40)" on
one line. In amsmath `\tag*` **replaces** the number and does not
advance the counter.

Neither errors. KaTeX swallows `\nonumber`/`\notag` silently and renders
`\tag*` without complaint, so both shipped unnoticed.

## Root cause

The converter treated these tokens as opaque math content. They are not
content — they are *instructions to the numbering engine*, and the
numbering engine on the other side (mystmd) has no equivalent:

| token | LaTeX meaning | what mystmd/KaTeX does |
|---|---|---|
| `\nonumber` / `\notag` | this row takes no number | swallowed silently; the block is numbered anyway |
| `\tag{}` / `\tag*{}` | replace this row's number with literal text | rendered in the body, *beside* the auto-number |
| `\\` in a row-numbering env | row boundary **and** number boundary | ignored; one enumerator per math node (see #186) |

So the converter is the only place the semantics can survive. This is
the same class as lesson 042: a construct whose meaning is invisible to
the renderer has to be resolved before emission, not forwarded.

## Fix

**`\nonumber` → fuse forward.** In `_split_align_rows`, a row containing
`\nonumber`/`\notag` is not a boundary: it accumulates into the next
row's group (transitively for chains), and the group is emitted as one
block wrapping the fused rows in `\begin{aligned}`. A *fused* group keeps
its `&` columns and its trailing punctuation — inside one equation those
are content, not the row-separator artefacts the single-row cleaners
strip. A trailing `\nonumber` row has nothing to fuse into and is emitted
forced-unnumbered instead.

**`\tag` → lift to `:enumerator:`.** `:enumerator:` is the only mystmd
field that sets a literal equation identifier *without* advancing the
counter (`ReferenceState.incrementCount` returns early once
`node.enumerator` is set), and it is what a `{eq}` reference renders. So
the tag text becomes the block's enumerator and the token leaves the
body.

## Gotchas worth knowing

- **Normalization order is load-bearing.** `\tag*{\text{(atm.\ carbon)}}`
  must be unwrapped → paren-stripped → *then* escape-resolved. Bailing on
  the residual `\ ` before resolving escapes would leave real sites
  unfixed. The enclosing parens must come off because mystmd re-adds them
  via its `(%s)` equation template — keep them and the reader sees
  `((budget))`.
- **An empty `:enumerator:` is silently ignored**, and the block then
  takes a real number again — re-creating exactly the defect being fixed.
  A tag that normalizes to empty must bail to `:enumerated: false`, not
  emit an empty option.
- **Never fuse two `\tag`s into one `aligned`.** That is a hard mystmd
  `Multiple \tag` failure — the #46 collision the split path exists to
  avoid. Guard the fusion.
- **Stripping the token is source hygiene, not a render fix.** KaTeX
  swallows `\nonumber` wherever it lands, so the leak was never visible
  to a reader. Don't oversell it; the reader-visible defects are the torn
  equation, the mis-pointed refs and the double numbering.
- **The tokens also appear off the split path.** An align with a single
  `\label` never splits, so its `\notag` leaked straight into the
  `\begin{aligned}` body (deep-learning ch01). The strip and the tag lift
  belong at every emission site — `equation`, `multline`/`gather`, and
  both collapsed align paths — not just in the splitter.

## Related

- #186 / QuantEcon/mystmd#73 — the *other* half of the same family: one
  enumerator per math node means a multi-row `align` still collapses to a
  single number. That one is a renderer gap and is upstream; this lesson
  is the converter-side share.
- Lesson 032 / #70, #46 — created the per-row split path this amends.

## Update 2026-08-13 — the upstream half landed

`QuantEcon/mystmd#73` is closed: QuantEcon/mystmd#81 (released as `qe-v9`)
numbers `align` / `gather` / `alignat` rows per-row **with the `&` axis
preserved**, and models `\nonumber` / `\notag` / `\tag` / per-row `\label`
natively. So the renderer now understands the tokens this lesson is about.

The lesson's reasoning still describes what the converter does **today** —
the `qe-v8` CI pin (`MYSTMD_REF` in `.github/workflows/test.yml`) predates
mystmd#81. Once that pin moves, the right question is not "is this still
correct?" but "is this still *needed*?" — see ROADMAP §2 and #186.

## Update 2026-08-13 (b) — the pin moved, and the scope narrowed

`MYSTMD_REF` is now qe-v9 (`24f6ae8`) and #201 shipped `align` passthrough,
so the open question above is answered: this modelling is **still needed,
but no longer on the `align` path**.

A passed-through `align` now forwards `\nonumber` / `\notag` / `\tag`
verbatim, because qe-v9 honours them natively — the lesson's headline
("the converter must resolve them") holds for every path passthrough does
*not* cover: `equation`, `multline`, `gather`, `align*`, and the tagged /
multi-label / `\intertext` aligns that stay on the split path. See lesson
057 for which is which.
