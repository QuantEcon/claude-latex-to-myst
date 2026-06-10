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

## Architecture evolution — LANDED (PR #103)

Outcome of the deep implementation review
([`notes/DESIGN-REVIEW.md`](notes/DESIGN-REVIEW.md) → design docs in
[`notes/design/`](notes/design/)). Goal: support **more general
conversion** without over-specializing on edge cases — and without
over-generalizing into a rewrite. **All six phases landed** on one branch
(one commit each) in PR #103; each design doc carries a "LANDED" banner with
its result. The standing parity objective (get close to parity across
`book-dp1`, `book-dp2`, `book-dp-deep-learning`) rode alongside, measured by
the two-baseline harness (`scripts/validate_fixture.sh`: `--against snapshot`
= refactor-safety byte-identity gate, default = parity gap vs the worked-on
`mystmd/`). The bar is "close / only documented drift," not byte-equality
(the worked-on baselines carry irreducible hand-edits).

| Phase | What landed | Output change |
|------:|-------------|---------------|
| 1 | Validation gate + CI — `.tex`-rooted `golden_tex` tier, §1b differential gate, per-book count baselines, `.github/workflows/test.yml` (pinned pandoc) | none |
| 2 | Marker shared base (`transforms/_markers.py`) + documented pandoc/marker boundary | none |
| 3 | `ConversionContext` — run state threaded, module globals + lesson-038 `sys.modules` alias gone, reentrant | none |
| 4 | Surface reduction — `#94` subfigure markers, "no custom AST" record, lessons re-tagged | yes (re-pinned) |
| 5 | Book-side `project_overrides.py` (closed surface: `EXTRA_REWRITES` + `POST_CONVERT`) + graduation rule | none |
| 6 | Deep-Learning parity pass — tikz figure-caption math (166→20 diff lines; 7/12 chapters byte-identical) + marker-aware `validate.py` | yes (DL re-pinned) |

The standing lesson: the architecture is **general enough for a third book**
— DL fell into place through the intended seams (config + one tier-1 fix +
the override tier), and the Phase-1 gates caught every output change. What's
left is consolidation + adoption, below.

## What's next (post-architecture-evolution)

The architecture work proved the design generalizes (three books). The
forward work splits into three themes: **pay down the shims** the phases
deliberately left, **make the measurement honest**, and **adopt + grow**.
Priority order within each is roughly top-down.

### A. Consolidation — pay down the Phase-3/5 shims

These were intentional compatibility shims; retiring them is the cleanup the
design docs anticipated. None changes conversion output.

1. **Migrate the ~600 unit tests off the `postprocess` module-proxy onto
   `ctx`, then remove the proxy.** Phase 3 kept a module-`__getattr__`/
   `__setattr__` proxy so tests could still poke `postprocess.ENV_MAP` etc.
   It's a clever-but-load-bearing shim; once tests configure state via an
   explicit `ConversionContext`, delete it. **Effort:** ~1 day (mechanical,
   golden-gated). **Risk:** low.
2. **Expose a library entry point** `convert_book(config) -> dict[str, str]`.
   Phase 3 made the pipeline reentrant; surfacing a clean in-process API
   (no file I/O) unlocks programmatic conversion, batch fixture testing, and
   a future service without re-deriving it. **Effort:** ~half a day.
3. **Retire the `tikz_overrides.py` filename alias** after one release
   (Phase 5 kept it for one). Books move to `project_overrides.py`.

### B. Measurement honesty

4. **Clean up `validate.py` for `preprocess.split` books.** Phase 6 made
   `count_latex` marker-aware as a patch; the principled fix is to count the
   **pristine monolithic source** for split books (and/or model multi-key
   citation expansion) so the (B) count signal is exact, not approximate.
   The (C-parity) diff remains the authoritative fidelity measure regardless.
   **Effort:** ~1 day. **Risk:** medium (touches the validator loop).
5. **Wire the label-gated `fixture-counts` CI job** with the consumer-repo
   clone secrets (`BOOK_DP*_URL`) so it actually runs on demand, and bump the
   workflow's `actions/checkout` to a Node-24-compatible version (the runner
   deprecation warning).

### C. Adoption & parity — the real generality test

6. **Finish Deep-Learning parity** (book-side, tier-2). ~20 residual diff
   lines: `:width:` additions (favorable — converter is more source-faithful)
   and tikz node-text labels (set via `TIKZ_FIGURE_MAP` `caption_override` if
   wanted). Land DL's drift ledger on its `mystmd-conversion` branch.
7. **Migrate `book-dp1` onto the pipeline** (see *In flight* above) — drops
   ~1500 lines of dp1-side bespoke scripts; book-side config work.
8. **Onboard a fourth book.** The strongest proof of generality is a book
   *outside* the dp/DL family. The graduation rule predicts most of its
   quirks land in its `project_overrides.py`; watch which graduate.

### D. Vigilance (ongoing, not a task)

9. **Watch the quirk-vs-permanent lesson count** (the Phase-4 axis tag in
   LESSONS.md). A rising *quirk* count means the pandoc/marker boundary is
   leaking and a construct should move onto the marker path; a rising
   *permanent* count is just normal coverage. This is the early-warning
   signal that the architecture needs attention.
10. **Tag the first release** — held until at least one consumer book ships
    in production on the pipeline (see CHANGELOG `[Unreleased]`); tagging
    earlier freezes a contract consumers haven't validated.

Design substrate for all of the above: [`notes/design/`](notes/design/) (each
phase doc + its LANDED banner). New large efforts get their own design doc
there before implementation.

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
