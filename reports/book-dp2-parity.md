# book-dp2 parity report

**Date:** 2026-05-20
**Pipeline version:** through commit `fa85014` (3 dp1 transforms ported)
**Source branch tested:** `book-dp2/mystmd-conversion @ 759647d`

## What was tested

`book-dp2` is the originating project — its `mystmd/scripts/` is what we
extracted and generalized into `claude-latex-to-myst`. The parity question:
does the extracted, config-driven pipeline reproduce the output of the
hand-tuned original?

Method:

```bash
git worktree add --detach ../book-dp2-pipeline-test mystmd-conversion
mkdir -p ../book-dp2-pipeline-test/mystmd-test
cp examples/book-dp2/config.yaml ../book-dp2-pipeline-test/mystmd-test/
cp examples/book-dp2/tikz_overrides.py ../book-dp2-pipeline-test/mystmd-test/
bash claude-latex-to-myst/scripts/convert.sh \
  --config ../book-dp2-pipeline-test/mystmd-test/config.yaml
diff -r mystmd/ mystmd-test/   # compare against committed output
```

## Result: parity ✓ (with deliberate, beneficial drift)

### Initial extraction (commits `1e2dc1a` + `671fa11`)

All 10 chapters **byte-identical** to the committed `mystmd/ch_*.md`. Only
front-matter files (`preface.md`, `common_symbols.md`) differed — and those
had post-conversion hand edits, not pipeline drift. See `mystmd/preface.md`
in the dp2 repo's git history (commits `47e5a0f`, `722fe56`).

This confirmed the extraction preserved transform behaviour exactly.

### After porting 3 dp1 transforms (commit `fa85014`)

Re-running picks up `strip_doubled_noun_refs`, `ensure_blank_after_display_math`,
and `strip_footnote_refs`. Per-chapter drift now:

| Chapter | Blank-line additions | Semantic changes |
|---------|---------------------:|-----------------:|
| ch_egs | 88 | 0 |
| ch_adps | 30 | 0 |
| ch_adps2 | 39 | **1** |
| ch_adps3 | 34 | 0 |
| ch_transforms | 35 | 0 |
| ch_ldps | 24 | 0 |
| ch_rdps | 49 | 0 |
| ch_apps | 78 | 0 |
| ch_approx_learning | 33 | 0 |
| ch_math_foundations | 34 | 0 |

All "blank-line additions" are `ensure_blank_after_display_math` inserting a
readability break after closing `$$`. No semantic change.

The single semantic change in `ch_adps2.md`:

```diff
- Our first is a min-version of Theorem {prf:ref}`t-pospace`.
+ Our first is a min-version of {prf:ref}`t-pospace`.
```

This is `strip_doubled_noun_refs` removing the redundant "Theorem " prefix —
sphinx-proof renders `{prf:ref}` as "Theorem 1.2" automatically. The source
LaTeX was `Theorem~\ref{t:pospace}` (the only such occurrence in all of
dp2). The new output is strictly correct.

## Implications

- The committed `book-dp2/mystmd/` is now ~440 cosmetic lines behind what
  the pipeline would produce today.
- Re-running the pipeline against dp2 produces a clean diff (almost all
  `+\n` blank lines, plus the one `Theorem~\ref` fix).
- Recommendation: regenerate `book-dp2/mystmd/` from the new pipeline and
  commit. One commit, no surprises. See `ROADMAP.md` for the decision.

## Portability bugs surfaced during the test

The dp2 test also caught two macOS portability issues that hadn't shown up
in the dp2 repo (which has its own setup):

- bash 3.2 lacks `mapfile` — replaced with `while IFS= read -r` loop
- BSD sed treats `\{` `\}` as repetition syntax — moved all sed-style
  transforms into Python (`_apply_rewrites.py`)

See lesson [009](../lessons/009-bsd-sed-mapfile-portability.md).

## Pyproject / uv adoption surfaced through this test

PEP 668 made `pip install pyyaml` fail on the test machine. Rather than
documenting a manual venv setup, we made `uv` the project manager:
`pyproject.toml` + `uv.lock` committed, shell scripts auto-bootstrap via
`uv sync`. See lesson [010](../lessons/010-pep-668-system-python.md) and
commit `e73d8a4`.

## Bottom line

The extraction is faithful. The drift after porting dp1 transforms is
deliberate, small, and strictly improves the output. dp2 can be regenerated
when convenient.

---

## Status update (2026-05-29) — #98 figure-marker regen audit

Re-ran the regen against the figure-marker work (#95/#97) and fixed three of
the four #98 regressions that surface in dp2 (the fourth, dropped-image, is
dp1's). All fixes are in `scripts/transforms/figures_from_latex.py`; counts
are unchanged (they fix output *quality*, not structure):

| #98 | dp2 symptom | before | after |
|-----|-------------|-------:|------:|
| #1 width | `[width=0.95\textwidth]` dropped | 31 missing `:width:` | **0** (95%/85%/80%/… restored) |
| #2 caption | leading space on `\caption{\label{} …}` | 66 captions | **0** |
| #3 tikz leak | `f-coase_subp`/`f-coase_no` node labels | leaked | **0** (bail → `{figure} …coase.svg` via map) |

One intentional width *improvement* remains as drift: the single
`width=\textwidth` (no fraction) figure (`f-ti_iterates`) now emits
`:width: 100%` instead of the baseline's broken `:width: \\textwidth` (pandoc
left it as a literal control word).

**`validate.py` status (honest):** does **not** exit 0, but the regen is
*strictly better* than the committed baseline — running `validate.py` against
`mystmd/` itself shows ~30 `{ref}\`algo-*\`` / `{ref}\`eg-*\`` directive-type
mismatches and the same equation/cross-ref count quirks; the regen has **1**
directive-type mismatch (`ex-rsigrv`). The residual count mismatches are
pre-existing in both:

- `ch_adps` figures 6/5 and `ch_approx_learning` 11/10 — `\begin{subfigure}`
  blocks whose per-panel SVGs are each mapped, collapsed to one `{figure}` by
  the `#49` composite-override fast path in `convert_html_figures`. This is
  **#94 (Phase-2 subfigure)** — noted there, deliberately not half-fixed here.
- `ch_*` equation counts off by 1–2 (unlabeled `equation`/`align` blocks) and
  cross-ref MyST > LaTeX (multi-target `\cref{a,b}` expansion) — counting
  artifacts, identical in baseline and regen.

Locked by `tests/golden_tex/figure_width_option`,
`figure_label_in_caption`, `figure_raw_tikzpicture_with_override_bails`. See
lesson [044](../lessons/044-marker-migration-needs-differential-tex-gate.md).
