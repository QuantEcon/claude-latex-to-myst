# Phase 6 — Deep-Learning parity pass (proving generality across all three books)

**Status:** LANDED (architecture-evolution branch, commit 6/6) · **Effort:** ~1 day · **Risk:** medium (changes DL output) · **Depends on:** Phases 1–5

## Why this phase exists

Phases 1–5 built the architecture; Phase 6 *exercises* it on the book that
was furthest from parity (`book-dp-deep-learning`), to prove the design is
general enough for three genuinely different books — not just dp1/dp2. It is
the `validate-to-zero` workstream the earlier session prompt scoped as
separate, brought in to demonstrate the payoff. It uses every Phase-1 gate
(golden_tex, the §1b differential, the snapshot/parity two-baseline harness)
and the Phase-3/4 marker+override machinery.

## Diagnosis (the apparent gap was mostly two things)

The Phase-0 `validate.py` signal made DL look far behind (theorems `0/N`,
"~half citations uncounted", equation/notation gaps). Investigation showed
**most of that is a measurement artifact, not lost content**:

- **Citations `61/130`** — the column is `latex/myst`, and for DL (which uses
  `preprocess.split`, so it has no per-chapter *pristine* source) `validate`
  counts the **preprocessed tmp file**, where `_apply_rewrites` has already
  turned natbib commands into `[[CITEP:]]` / `[[CITEALT:]]` markers the
  `\cite…{` regex didn't see (ch01: 61 `\cite` + 53 markers in tmp → 130
  faithful `{cite}` roles emitted). So `myst ≥ source`: **no citations are
  lost** — the validator under-counted the source.
  **Fixed:** `count_latex` is now marker-aware (counts `[[CITE…]]` markers and
  `<!--FIGURE-->` markers — the latter decoded for subfigure panels). After
  the fix appA_glossary citations go `1/20 → 20/20`, ch02 figures `10/11 →
  11/11`, ch01 citations `61 → 111`. The residual citation gap (ch01 111/130)
  is *only* multi-key `\citet{a,b}` expanding to two roles — inherent
  counting semantics, not lost content.
- **Theorems `0/N`** — DL's theorem-like content is `definitionbox` /
  `remarkbox` / `keyinsightbox`, mapped (Phase-3 `extra_environments`) to
  `{prf:definition}` / `{prf:remark}` and emitted correctly; the validator's
  latex-side theorem regex just doesn't match `definitionbox`. A residual
  counting artifact, not lost content (the `{prf:*}` directives are emitted).

The **real** fidelity gap was figure captions (lesson 045): DL's 78 inline
`tikzpicture` figures bail the marker path (so the consumer's
`TIKZ_FIGURE_MAP` SVG applies), which means the whole float — caption
included — flowed through pandoc, whose HTML figcaption **flattens caption
math** (`$\theta_0$` → unicode `θ0`).

## The fix

Marker-ize tikzpicture floats **caption-only**: strip the
`\begin{tikzpicture}…\end{tikzpicture}` region first (so node text isn't
scooped — the #98 #3 protection holds), extract the float `\caption` /
`\label` and any *legitimate* `{\footnotesize}` sub-panel captions that live
outside the tikz block, and batch-convert the caption through pandoc (math
preserved). `_emit_figure` resolves the image from `TIKZ_FIGURE_MAP` (the
override path added in Phase 4) and emits the mapped SVG **plus** the
math-faithful caption. See `figures_from_latex.parse_figure_block`
(tikzpicture branch) + lesson 045 + `golden_tex/tikz_figure_caption_math`.

## Result

Deep-Learning parity diff vs the worked-on `mystmd/` baseline:

| | total diff lines | chapters byte-identical |
|---|---|---|
| Phase 0 (before) | 166 | 0 / 12 |
| caption-math fix | 30 | 6 / 12 |
| + sub-caption recovery | **20** | **7 / 12** |

dp1 (no tikz figures) and dp2 (3 tikz figures, plain-text captions) stayed
**byte-identical** — the change is contained to the construct it targets.

## Remaining ~20 lines = documented drift, not bugs

- **`:width:` additions** (ch11): the regen emits `:width: 85%` etc. from
  `\includegraphics[width=0.85\textwidth]`; the worked-on baseline dropped
  them. The converter is *more* source-faithful here — favorable drift.
- **tikz node-text labels** the baseline kept (e.g. "tokens exchange
  information", "$5+2N_b$"): these are inside the tikzpicture and are dropped
  by design (#98 #3 — they belong in the SVG). Recovering them would
  re-introduce the node-scoop bug; a book that wants a specific node label as
  a caption sets it via `TIKZ_FIGURE_MAP`'s `caption_override` (tier-2).

## Scope boundaries

- **In:** tikz figure-caption math preservation; a marker-aware `count_latex`
  so the (B) signal is honest for split-source books (figures + citations
  counted through their preprocessor markers). dp1/dp2 read pristine source
  (no markers) so their counts/output are unchanged.
- **Out:** the residual multi-key citation count delta (`\citet{a,b}` → 2
  roles) and the `definitionbox`-theorem count — these are counting
  semantics, not fidelity loss, and the (C-parity) diff is the authoritative
  fidelity measure.
