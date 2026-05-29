# Roadmap

What to work on next, in priority order. See [CHANGELOG.md](CHANGELOG.md)
for the per-release record of what's already landed.

## In flight

### Migrate `book-dp1` to this pipeline

**Effort:** ~half a day (mostly config porting, no tool changes expected).
**Impact:** High. dp1 still runs ~1500 lines of its own
`mystmd/scripts/` (postprocess.py, preprocess.sh, perl rewriters) that
duplicate transforms now in this repo. Migrating drops the duplication
and means future improvements propagate to dp1 automatically.

All known gaps are closed on `main`:

- `preprocess.split` handles `book/appendix.tex` (3 `\chapter{}` → appA/appB).
- Per-file `frontmatter_style` handles dp1's mixed conventions
  (numbered chapters standalone, front-matter absorbed).
- Book-side wrapper post-steps run `render_tikz.py` + `build_llms_txt.py`
  inside the same `bash mystmd/convert.sh` invocation.
- `validate.broken_inline_math` folds in dp1's standalone
  `_find_broken_math.py`.
- `postprocess.rewrites` is available if dp1 needs editorial rewrites
  comparable to dp2's `## Mathematical Notation` promotion.

Remaining work is dp1-side config (not tool changes):
`\scalebox{N}{\input{...}}` unwrap, `\input{figures/*.pdf_t}` rewrite,
`\inputminted` strip, `\pageref` variants. All entries in
`config.preprocess.rewrites` / `config.preprocess.strip`.

Handover briefing for the dp1-side agent lives in the `book-dp1`
repo (kept book-side rather than here so it travels with the work).

## Architecture evolution (long-term)

Outcome of the deep implementation review
([`notes/DESIGN-REVIEW.md`](notes/DESIGN-REVIEW.md) → design docs in
[`notes/design/`](notes/design/)). Goal: support **more general
conversion** without over-specializing on edge cases — and without
over-generalizing into a rewrite. Five phases, priority order; each is a
focused unit with its own design doc, scope, and exit criteria. Later
phases assume earlier ones.

**A second, standing objective runs alongside the phases: get close to
parity across all three real-world books** (`book-dp1`, `book-dp2`,
`book-dp-deep-learning`). The real books are the complexity benchmark the
synthetic tests can't match — every parity gap closed is a translation
capability the tool gains, and each fix is captured as a `tests/golden_tex/`
reproducer so the corpus grows with the work. Parity here is *aspirational*:
the committed `mystmd/` on each book's `mystmd-conversion` branch is the
human-worked-on target and carries irreducible hand-edits the deterministic
tool won't reproduce, so the bar is "close / only documented drift," not
byte-equality. Validation uses **two baselines** — a pinned per-book
snapshot of current tool output proves each refactor is behavior-preserving
(byte-identity), while the diff against the worked-on `mystmd/` measures the
parity gap to drive down. The fixture-validation harness
(`scripts/validate_fixture.sh`, added with the common-fixture-validation
work) runs both: `--against snapshot` for the safety check, the default for
the parity gap. Because refactor-safety rides on the snapshot, reaching
parity is *not* a precondition for starting the phases.

### Phase 1 — Validation gate + CI

**Effort:** ~1–2 days. **Risk:** low. **Urgency:** ESCALATED — guards every
refactor below and would have caught #96 *and* the four #98 figure-marker
regressions pre-merge. Recommend freezing further fallback→marker
migrations (#94) until this lands.

No CI exists today (`.github/workflows/` is absent) and no end-to-end gate
is rooted in `.tex` — the existing golden corpus starts from pandoc
output, so the preprocess/pandoc/marker boundary (where #95/#96 and most
lessons live) is untested e2e. Add a `.tex`-rooted golden tier
(`tests/golden_tex/`, curated — not the gitignored consumer clones),
seed it from the pandoc-quirk lessons, and wire `pytest` + `validate.py`
into a CI workflow with a pinned pandoc.
Design: [`notes/design/phase-1-validation-gate.md`](notes/design/phase-1-validation-gate.md).

### Phase 2 — Marker shared base + hybrid boundary

**Effort:** ~1–2 days. **Risk:** low (pure refactor, gated by Phase 1).

Factor the duplicated marker scaffolding (`_pandoc_batch_convert`, the
`CELL_N` sentinel split, marker encode/decode, blank-line stream
reassembly — currently near-identical across the figure/table
preprocessors) into one shared base; each preprocessor keeps only its
construct-specific parser + emitter. Plain functions, **not** a plugin
framework. Also: write the pandoc↔marker boundary into CLAUDE.md so it
stops moving by accretion.
Design: [`notes/design/phase-2-marker-shared-base.md`](notes/design/phase-2-marker-shared-base.md).

### Phase 3 — `ConversionContext` (state threading)

**Effort:** ~3–5 days, incremental. **Risk:** medium. **Hard prereq:** Phase 1.

The deepest generality win. Post-pandoc state lives in module-level
mutable globals on `postprocess.py`, read by 7 transform modules via
late-`import postprocess`. This makes the pipeline non-reentrant (can't
convert two books in one process) and is the root cause of 🔴 lesson 038.
Replace with a `ConversionContext` dataclass threaded as an argument;
migrate one transform family per PR, golden gate green on each; then
delete the globals and the `sys.modules` alias.
Design: [`notes/design/phase-3-conversion-context.md`](notes/design/phase-3-conversion-context.md).

### Phase 4 — Surface reduction + decision records

**Effort:** subfigure ~2–3 days; fallback removal ~1 day. **Risk:** medium.
**Depends on:** Phases 2–3 and GH #94.

Each structural construct carries two code paths today — the marker
resolver plus an old post-pandoc HTML fallback. Finish marker coverage
(subfigure, #94; table-shape audit), then retire the HTML fallbacks so
there's one path per construct. Record the "no custom AST" decision in
CLAUDE.md, and re-tag the lesson catalogue along the quirk-vs-permanent
axis so its growth becomes interpretable.
Design: [`notes/design/phase-4-surface-reduction.md`](notes/design/phase-4-surface-reduction.md).

### Phase 5 — Book-side overrides + graduation rule

**Effort:** ~1–2 days. **Risk:** low–medium. **Hard prereq:** Phase 3.

Gives book-specific *programmatic* edge cases a home that is neither a
re-run-fragile hand-edit nor over-specialization in `postprocess.py`.
Generalize the existing `tikz_overrides.py` seam into a **closed**
`project_overrides.py` surface (data maps + `EXTRA_REWRITES` + one optional
`POST_CONVERT` hook) — not a plugin framework. The conceptual payload is
the **graduation rule:** one book needs it → book-side override; a second
book needs it → graduate into the generic pipeline with a lesson + golden
case. Gated on Phase 3 because overrides must *contribute to*
`ConversionContext`, not mutate module globals.
Design: [`notes/design/phase-5-book-overrides.md`](notes/design/phase-5-book-overrides.md).

## Open items

### GH issue [#1](https://github.com/QuantEcon/claude-latex-to-myst/issues/1) — em/en-dash conversion

**Effort:** ~half a day for `---` only; ~full day with `--` too.
**Impact:** Low / cosmetic. MyST renders `---` literally; ~40 instances
per dp2 book chapter would benefit. The committed dp2 chapters already
accept `---`, so this is a polish item rather than a blocker.

Full scope analysis is in the issue. When picking this up, start with
`---` only (em-dash) and skip `--` (en-dash) — the en-dash positions
include legitimate `Author--Author` proper nouns and `(i)--(iii)` ranges
that are higher-judgment cases.

### Optional polish

- **Tighten `whitespace_compression: compact`** to match dp1's
  hand-tuned spacing byte-for-byte. The flag works for projects that
  want denser source; exact dp1 parity would require preserving
  source-spacing through `convert_environment_divs` — bigger refactor,
  defer unless asked.

## Things to consider once gaps are closed

### Adopt this tool in additional books

The bar for "adopt" is now `mystmd/config.yaml` + drop in the wrapper.
After dp1 migrates, the obvious next candidates are any other
QuantEcon books with LaTeX sources and chapter structure.

### Set up the `claude-pdf-to-myst` repo (separate tool)

PDF → MyST conversion has a fundamentally different shape (OCR + LLM
cleanup vs. pandoc + regex). Different repo, different lessons
catalogue, but a shared `myst-conventions.md` doc. Not blocking
anything in this repo.

## Things I won't do (and why)

- **Won't add LLM calls to the pipeline.** Determinism and
  re-runnability are non-negotiable. LLM-driven cleanup for edge
  cases happens in the user's editor / Claude Code session, not
  inside `convert.sh`. Settled in [CLAUDE.md](CLAUDE.md).
- **Won't write a YAML subset parser to avoid the PyYAML dep.** Per
  [lesson 010](lessons/010-pep-668-system-python.md), `uv` solved the
  installation problem more cleanly than dropping the dep.
- **Won't generalise beyond academic books.** The tool assumes
  chapters, theorems, equations, bibliography. Documents without that
  shape need a different tool.
- **Won't add a hooks framework to `convert.sh`.** The book wrapper
  is the right place to hang project-specific post-steps; coupling
  the tool to book-side script semantics adds complexity for no gain.
