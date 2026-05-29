# book-dp-deep-learning parity report

**Date:** 2026-05-29
**Pipeline version:** the #98 fix branch (figure-marker parser-completeness + cite-decode)
**Baseline tested against:** `book-dp-deep-learning/mystmd @ R13 (b79df24)` — the
committed MyST output, pinned at R13 because R14 (the #95 marker PR) dropped
78/88 figures (#96). See `fixtures/book-dp-deep-learning/mystmd/VALIDATION.md`.

## What was tested

DL is the book that surfaced #96 (and motivated #97). It ships **78 inline
`\begin{tikzpicture}` figures** pre-rendered to SVG via `tikz_overrides.py`,
plus 10 `\includegraphics` figures. The R13 pin held precisely because the
marker path could not route those 78 figures through the post-pandoc
`TIKZ_FIGURE_MAP` lookup. The parity question for this session: do the #98
fixes — in particular the **#98 #3 bail on `\begin{tikzpicture}`** — restore
DL to its R13 figure fidelity while keeping #95's caption wins?

## Setup (Task 0 — fixture normalization)

The DL fixture is a full repo clone with `output_dir: "."`, so a regen would
clobber its own baseline. Normalized to the dp1/dp2 pattern:

- Added `fixtures/book-dp-deep-learning/regen/config.yaml` — identical to the
  canonical `mystmd/config.yaml` except `output_dir` is the separate `regen/`
  dir and `tikz_overrides` points at the already-rendered
  `../mystmd/tikz_overrides.py` (render_tikz.py, a DL-repo pre-step, is not
  re-run). The committed `mystmd/*.md` stays as the diff target.
- Added a `deep-learning` target to `scripts/setup_fixtures.sh`
  (`BOOK_DL_SRC`, default `../Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models`)
  so the fixture is reproducible like dp1/dp2.

```bash
bash scripts/convert.sh  --config fixtures/book-dp-deep-learning/regen/config.yaml
python3 scripts/validate.py --config fixtures/book-dp-deep-learning/regen/config.yaml
diff -r fixtures/book-dp-deep-learning/mystmd/ fixtures/book-dp-deep-learning/regen/
```

## Result: figures fully restored, strictly better than the R13 baseline

| signal | R13 baseline | regen (this branch) |
|--------|-------------:|--------------------:|
| `{figure}` directives | 88 | **88** (label-for-label identical) |
| stray `{admonition} Figure` | 2 | **0** |
| `[[CITEP:…]]` verbatim leaks | 0 *(hand-corrected; R13 produced 5)* | **0** |
| `:width:` on `\includegraphics` figs | 0 | **10** (added) |

- **#98 #3 (tikz bail) is the fix DL was waiting for.** The 78 inline-tikz
  figures bail the marker preprocessor (purely syntactic) and flow through
  pandoc → `convert_html_figures` → `resolve_tikz_figures`, which substitutes
  the pre-rendered SVG from `TIKZ_FIGURE_MAP`. Image-node parity with R13 is
  restored (88/88), and the 2 figures R13 left as admonitions now resolve to
  `{figure}`. The `{\footnotesize}` tikz node labels are correctly dropped
  (they live in the SVG), not leaked.
- **R13's known `[[CITEP:…]]` residual stays closed.** The tikz bail initially
  *re-opened* #92 (5 leaks in ch01/02/04 figure captions — the bailed
  post-pandoc path leaves the natbib marker unescaped). Fixed generically:
  `decode_natbib_markers` now matches both the escaped (`\[\[…\]\]`,
  marker-path) and unescaped (`[[…]]`, HTML-figcaption) bracket forms.
- **`:width:` is a net improvement.** The 10 `\includegraphics` figures gain
  the `:width:` the R13 HTML/`make_figure` path never emitted.

`validate.py` diff (baseline vs regen) shows only improvements: citation
counts move *closer* to the LaTeX source (ch01 130→128, ch02 48→47, ch04
33→31) and ch06 cross-refs now match exactly (76→75).

## Residual `validate.py` mismatches — all pre-existing counting quirks

`validate.py` does **not** exit 0 for DL, but every remaining mismatch is
present identically in the R13 baseline (confirmed by diffing baseline-validate
vs regen-validate) and is a known limitation of the count regexes, not a drop:

- **theorems 0/N** — DL maps `definitionbox`/`remarkbox`/`keyinsightbox`
  tcolorbox wrappers to `prf:*` via `extra_environments`; the LaTeX-side
  count regex only knows `\begin{theorem|lemma|…}`, so it reads 0.
- **equations MyST > LaTeX** — the #70 per-row `align` split emits multiple
  `$$` blocks from one `align`.
- **citations MyST > LaTeX** — multi-key `\citep{a,b,c}` expands to N
  `{cite:p}` roles.
- **figures MyST ≥ LaTeX** — figure-label sets are identical baseline↔regen;
  the count regex undercounts the LaTeX side for some multi-panel blocks.

None of these are introduced by this branch. (Filing a validate.py refinement
for the `extra_environments`/align/multi-key cases is tracked separately; out
of scope for the #98 figure work.)

## Bottom line

The #98 #3 bail closes the #96 figure-loss class for DL end-to-end: 88/88
figures, 0 caption leaks, `:width:` restored — strictly better than the held
R13 baseline. DL can fast-forward off the R13 pin once this branch lands.
Locked by `tests/golden_tex/figure_raw_tikzpicture_with_override_bails`.
