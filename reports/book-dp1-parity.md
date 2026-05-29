# book-dp1 parity report

**Date:** 2026-05-20
**Pipeline version:** through commit `fa85014` (3 dp1 transforms ported)
**Source branch tested:** `book-dp1/mystmd-conversion @ 990f576`
**Reference PR:** [QuantEcon/book-dp1#336](https://github.com/QuantEcon/book-dp1/pull/336)

## What was tested

`book-dp1` is the first **cross-project** test for `claude-latex-to-myst`.
The book already has its own MyST conversion in PR #336 (adapted from
dp2's pipeline by the dp1 maintainers), so the parity question is:

> Can our extracted tool, configured for dp1, reproduce dp1's
> hand-tuned conversion output?

This is a much stronger test than dp2 (where the tool's transforms came
directly from). It surfaces what's *generic* in the pipeline vs. what was
project-specific in dp2.

## Method

```bash
git worktree add --detach ../book-dp1-pipeline-test mystmd-conversion
mkdir -p ../book-dp1-pipeline-test/mystmd-test
$EDITOR ../book-dp1-pipeline-test/mystmd-test/config.yaml   # hand-write
bash claude-latex-to-myst/scripts/convert.sh \
  --config ../book-dp1-pipeline-test/mystmd-test/config.yaml
diff -r mystmd/ mystmd-test/
```

The config (committed-out, not yet promoted to `examples/book-dp1/`) is
roughly 60 lines and covers:

- 10 chapter stems + `common_symbols`
- Source in `book/` (not the repo root, unlike dp2)
- Bibliography at `book/qe_bib.bib`
- Figures at `../figures` (relative to `book/`)
- 11 strip rules (6 dp1-specific pageref variants)
- 7 rewrite rules (`\navy`, scalebox unwrapping, tikz placeholder, xfig
  `.pdf_t`, minted listings, algorithm captions)
- `tikz_overrides: null` (TikZ resolution map not populated for the test)

## Result: end-to-end success on first run

All 10 chapters + `common_symbols` converted without crashes or warnings.
Figures copied (85 files). Bibliography copied. Validation step ran.

This validates the config-driven architecture: a hand-written ~60-line
config was enough to convert a book the tool had never seen.

## Divergence from dp1's committed output

| Chapter | Line-count diff (after porting) |
|---------|---------------------------------:|
| ch_intro | 412 |
| ch_fps | 158 |
| ch_mcs | 323 |
| ch_opt_stop | 607 |
| ch_mdps | 716 |
| ch_state_dep | 223 |
| ch_val | 210 |
| ch_rdps | 358 |
| ch_adps | 64 |
| ch_ctime | 266 |

Categorising the diffs:

### 1. Genuine gaps in the tool (codifiable improvements)

**Three transforms ported in this session** (lessons 011–013):

- `strip_doubled_noun_refs` — eliminated 563 redundant "Theorem ", "Exercise ",
  "Chapter " prefixes before `{prf:ref}`. Pandoc preserves LaTeX `~`
  (non-breaking space) as U+00A0, which we now match alongside regular
  space. After porting: ~727 → 164 occurrences.
- `ensure_blank_after_display_math` — readability fix; inserts blank line
  after closing `$$`.
- `strip_footnote_refs` — replaces unresolvable `{ref}`fn-...`` with prose
  + HTML-comment annotation.

**Two transforms documented as open gaps** (lessons 014–015):

- `resolve_algorithms` + `_algo_convert_body` (algorithm2e). dp1
  preprocesses `\begin{algorithm}` blocks via a Perl script that base64-
  encodes the body before pandoc sees it, then a 130-line Python parser
  reconstructs the bullet-list structure. **Estimated 3–4 hours to port.**
  Without it, algorithm bodies in our output are flat run-on paragraphs.
- `resolve_listings` (minted). dp1 preprocesses `\inputminted` blocks via
  Perl + reads source files at postprocess time to inline line ranges
  into MyST `code-block` directives. **Estimated 1–2 hours to port** —
  also introduces a new `source_code_dir` config concept.

### 2. Stylistic differences (project choices, not bugs)

These differ between dp1 and dp2 — neither is "right":

- **Frontmatter style.** dp1: `(c-foo)=\n# Title\n...`. dp2 and our tool:
  `---\ntitle: "..."\nlabel: c-foo\n---\n...`. Both valid MyST.
- **Whitespace stripping.** dp1 collapses blank lines after `:label:`,
  before `$$`, and between adjacent directives. dp2 (and our tool) keeps
  them for source readability.

Could be config flags (`frontmatter_style: absorbed | standalone`,
`whitespace: strict | readable`) but not implemented yet. The bulk of the
remaining diff is in this category.

### 3. dp1-specific config (not pipeline)

All handled cleanly via `config.yaml`:

- 6 `\pageref` strip variants (page references don't render in HTML)
- xfig `.pdf_t` figure imports
- `\inputminted` → placeholder (the *placeholder* is in config; the full
  source-file-inlining version is the open gap #015)
- Algorithm caption label hoisting

## What surprised us

- **Non-breaking space.** Our initial doubled-noun-ref grep returned 0
  because the LaTeX source uses `Theorem~\cref{}` which pandoc emits as
  `Theorem {prf:ref}` — not a regular space. The `[ \xa0]+`
  character class in the ported transform handles both. Worth remembering
  for any future text-pattern matching against pandoc output.
- **Algorithm2e is unrecoverable post-pandoc.** Pandoc destroys the
  structure entirely (control commands, `\;` terminators all gone). The
  only way back is a preprocessor that wraps the body before pandoc, and
  a postprocessor that decodes it. This is why dp1 uses Perl + base64 —
  it's the simplest way to keep an opaque blob alive through pandoc.

## What dp1 chose to do that we deliberately didn't

dp1's `convert_environment_divs` strips leading/trailing blank lines from
directive bodies. Our version preserves them. **Not a bug to fix** — it's
a style preference. Imposing dp1's compression on every book would force
dp2 (and any new book) into a particular convention.

If users want dp1-style, that's the case for a `whitespace: strict`
config flag. Until then we keep dp2-style as the default.

## Next actions for dp1

If the goal is to consolidate dp1 onto this tool:

1. Decide on stylistic conventions (frontmatter, whitespace) — currently
   ours = dp2's. Adopting dp1's choices requires either changing the
   defaults or adding config flags.
2. Close gaps #014 (algorithms) and #015 (listings) before adopting,
   otherwise dp1 loses algorithm structure and listing inlining.
3. Promote `examples/book-dp1/` (currently the test config lived only in
   the worktree).

See `ROADMAP.md` for prioritisation.

## Bottom line

The tool's architecture is validated: project-specific stuff stayed in
config and worked, generic gaps are clearly identified and 3 are already
closed. The 2 remaining gaps are documented with reference
implementations — they're "fund this work" items, not "redesign the
tool" items.

---

## Status update (2026-05-22)

Both open gaps from this report are closed on `main`:

- Gap #014 (algorithm2e) — closed by `9118518`, lesson
  [014](../lessons/014-algorithm2e-resolution.md) marked codified.
- Gap #015 (minted listings) — closed by `223bd12`, lesson
  [015](../lessons/015-minted-listings-resolution.md) marked codified.

The dp1 migration is no longer tracked here — the handover briefing now
lives in the `book-dp1` repo (see commit `2cd78ae`). For the up-to-date
list of pipeline changes since this report was written, see
[CHANGELOG.md](../CHANGELOG.md) under `[Unreleased]`.

---

## Status update (2026-05-29) — #98 figure-marker regen audit

dp1 is where #98 #4 (image dropped when `\includegraphics`'s `{path}` is on
the next line) bites: `f-finite_lq_1` is `\scalebox{0.64}{\includegraphics[trim=…,clip]\n  {../figures/finite_lq_1.pdf}}`.
Fixed by allowing `\s*` between `[opts]` and `{path}` in
`_INCLUDEGRAPHICS_RE` — the figure is no longer dropped.

While auditing, found the dp1 **regen fixture config was a deliberately-minimal
smoke-test config** missing 4 of the 5 preprocess rewrites the canonical
`book-dp1/mystmd/config.yaml` carries (scalebox×2, tikz-input placeholder,
xfig `.pdf_t`). Without the xfig rewrite, the 5 `\input{…/foo.pdf_t}` overlay
figures fell through to generic admonitions. **Ported all four verbatim into
`fixtures/book-dp1/regen/config.yaml`** (book-specific config, not a pipeline
change). Result — dp1 figures now at **full parity with the committed
baseline**: every chapter has identical `{figure}` counts, 0 unresolved
admonitions in both (`ch_intro` 12→12, `ch_mdps` 14→15, etc.).

**`validate.py` status (honest):** does not exit 0; the residual figure
mismatches are **pre-existing** (identical in baseline-validate): `ch_val`
6/5 (`\begin{subfigure}` — #94), `ch_fps` 14/15, plus the usual unlabeled-eq
and multi-`\cref` count quirks and one `{eq}\`ex-vmeml\`` directive-type
mismatch. None introduced by this branch.

**Documented drift (unchanged from this report's body):** the large
frontmatter/whitespace stylistic divergence stands. One figure-path note: the
`../figures/…` source paths emit `{figure} ../figures/foo.pdf` (the marker
emitter's `'/' not in path` rule) vs the legacy baseline's
`figures/../figures/foo.pdf` (its `startswith('figures/')` rule); both resolve
to the same copied asset. The xfig figures emit `figures/foo.pdf` and match
the baseline exactly.

Locked by `tests/golden_tex/figure_includegraphics_path_on_next_line`. See
lesson [044](../lessons/044-marker-migration-needs-differential-tex-gate.md).
