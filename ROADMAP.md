# Roadmap

What to work on next, in priority order. See [CHANGELOG.md](CHANGELOG.md)
for the record of what's already landed, and [`docs/design/`](docs/design/)
for the architecture design records (the six-phase evolution landed in
PR #103; each design doc carries a "LANDED" banner with its result).

## Where things stand (2026-08)

All three consumer books run on the pipeline, each on its
`mystmd-conversion` branch with a `mystmd/.tool-version` pin:

| Book | Pinned tool version | Notes |
|------|--------------------|-------|
| `book-dp1` | `16f7a3d` (2026-06-20) | Migrated — the former "in flight" migration is done; dp1's bespoke conversion scripts retired. |
| `book-dp2` | `9d8367b` (2026-06-18) | Originating book; validation batches complete. |
| Deep Learning | `b01fa92` (2026-08-14) | **Current with `main`**, and the only book validating recent work end-to-end. Renderer pinned at `qe-v9`; its build is 2 warnings / 0 errors, with both remaining warnings kept by design. Adopted #192/#193/#186 with `qe-v9` (equation numbers 272/272 vs the printed PDF), then #194 on `qe-v9` alone — that fix has no renderer dependency. |

The Deep-Learning book is where the **renderer floor** gets decided in
practice, and the two couplings it has hit differ in severity — worth
knowing before proposing the next one:

- **#186 (`qe-v9`)** — forgiving. On an older renderer the passed-through
  `align` takes one number, so the fix is *silently forfeited*, not broken.
- **#160A (`qe-v10`)** — **not** forgiving. On `qe-v9` and earlier a
  `{.unnumbered}` attribute block leaks as literal braces into the rendered
  heading text *and* its auto-slug id. That is visible corruption, so the
  converter change and the renderer bump must land in one commit.

A converter change with no renderer dependency (#194) ships on its own.

No conversion branch has merged to a book's **default** branch yet. That
merge is the bar for tagging the first release (see CHANGELOG
`[Unreleased]`): tagging earlier freezes a contract no consumer has
validated in production.

## Next

### 1. Ship a consumer book

Merge one book's `mystmd-conversion` branch into its default branch (a
book-side editorial/publishing decision, not tool work). This is the
gate for the first release tag and the real-world validation of the
pipeline contract. Refresh the book's `.tool-version` pin as part of the
ship.

### 2. Decide the long-term architecture question — [#189](https://github.com/QuantEcon/claude-latex-to-myst/issues/189)

Evaluate `tex-to-myst` (mystmd's native LaTeX parser) as a long-term
alternative or complement to the pandoc + marker hybrid. This is a
strategic fork: its outcome should gate any further *large* investment
in converter features (small fixes and book support continue
regardless). The prior "no custom AST" decision record
([phase 4](docs/design/phase-4-surface-reduction.md)) covers building
our own parser, not adopting mystmd's.

### 3. Consolidation — pay down the Phase-3/5 shims

Intentional compatibility shims; retiring them changes no conversion
output.

1. **Migrate the ~850 unit tests off the `postprocess` module-proxy onto
   `ctx`, then remove the proxy** (the module-`__getattr__`/`__setattr__`
   at the bottom of `postprocess.py`). ~1 day, mechanical, golden-gated.
2. **Expose a library entry point** `convert_book(config) -> dict[str, str]`
   (no file I/O) — unlocks programmatic conversion and batch fixture
   testing. ~half a day.
3. **Retire the `tikz_overrides.py` filename alias** (Phase 5 kept it for
   one release; books have moved to `project_overrides.py`).

### 4. Measurement honesty

- **Clean up `validate.py` for `preprocess.split` books**: count the
  pristine monolithic source rather than the marker-aware patch, so the
  count signal is exact. ~1 day; touches the validator loop.
- **CI**: wire the label-gated `fixture-counts` job's consumer-repo clone
  secrets (`BOOK_DP*_URL`) so it runs on demand; bump `actions/checkout`
  past the Node-24 deprecation. Related:
  [#156](https://github.com/QuantEcon/claude-latex-to-myst/issues/156)
  (always-on mini-project smoke build).

### 5. Feature backlog (open issues)

- [#56](https://github.com/QuantEcon/claude-latex-to-myst/issues/56) —
  `\multicolumn` / `\multirow` merged-cell tabulars in the table marker
  preprocessor.
- [#80](https://github.com/QuantEcon/claude-latex-to-myst/issues/80) —
  fence widening for directives injected into a container body by a
  later pipeline stage (sentinel + final-stamp).
- [#6](https://github.com/QuantEcon/claude-latex-to-myst/issues/6) —
  optional prose-wrap config (low priority).
- [#191](https://github.com/QuantEcon/claude-latex-to-myst/issues/191) —
  colon-fence emission for `prf:*` directives whose titles carry roles
  (the alternative to #122's bold lead-in fallback); low priority, wants
  a book where role-bearing theorem titles are common.
- [#197](https://github.com/QuantEcon/claude-latex-to-myst/issues/197) —
  no handler for `flalign` / `alignat` / `eqnarray`, and `gather` with
  2+ labels bypasses the split path. Entirely latent (zero occurrences
  in any of the three books); note `qe-v9` splits these into different
  cases — `alignat` is row-numbered natively, `flalign` and `eqnarray`
  are not supported by KaTeX at all.
- [#199](https://github.com/QuantEcon/claude-latex-to-myst/issues/199) —
  `examples/` and `scripts/new-book.sh` still scaffold the legacy
  `tikz_overrides.py` filename and config key, so a book created today
  contradicts the docs. The alias must keep working (dp1 and dp2 both
  carry the legacy file on their conversion branches).

### Upstream trackers — blocked on `QuantEcon/mystmd`

Converter output is correct, spec-valid MyST; the publisher can't render
it yet (tier-3 routing). Nothing to do here but track:

- [#160](https://github.com/QuantEcon/claude-latex-to-myst/issues/160) →
  mystmd#68 — starred `\section*` / `\paragraph` emitted as numbered
  headings.
- [#169](https://github.com/QuantEcon/claude-latex-to-myst/issues/169) →
  mystmd#70 — algorithm line numbering restarts inside loop bodies.

### Later

- **Onboard a fourth book** — the strongest generality proof is a book
  outside the dp/DL family; the graduation rule predicts most quirks land
  in its `project_overrides.py`.
- **Watch the quirk-vs-permanent lesson ratio** (the Phase-4 axis tag in
  LESSONS.md). A rising *quirk* count means the pandoc/marker boundary is
  leaking and a construct should move onto the marker path.
- **`claude-pdf-to-myst`** as a separate tool (OCR + LLM cleanup is a
  different shape from pandoc + regex); shares only a `myst-conventions`
  doc.
- **Tighten `whitespace_compression: compact`** to byte-match dp1's
  hand-tuned spacing — bigger refactor through
  `convert_environment_divs`; defer unless asked.

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
