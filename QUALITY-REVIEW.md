# Quality Review — `claude-latex-to-myst`

**Date:** 2026-05-26
**Scope:** flexibility, robustness, and onboarding cost as the pipeline starts
to cater to multiple books beyond `book-dp1` / `book-dp2`.
**Status:** review document only — no code changes proposed yet. Triages
risks; recommends next steps in tiered priority.

---

## Executive summary

The pipeline is in good shape for what it currently is: a deterministic,
hermetic, regex-based LaTeX→MyST translator. The core architecture
(per-project config + generic transforms + lessons catalogue) has held up
across three books and 37 codified pitfalls. There is no urgent rewrite.

But the recent batch of issues (#30–#37) surfaced three concrete
flexibility/robustness gaps that will compound as more books come online:

1. **Validation is count-based, not resolution-based.** Every regression
   in the last two batches (#30, #31, #33, #35, #36, #37) produced
   *broken cross-references that survived `validate.py`*. They were
   detected only when a human noticed wrong numbers in rendered HTML.
2. **Transforms in a "family" diverge.** Math envs (`equation`,
   `align`, `multline`, `gather`) needed three separate commits across
   three months to all gain the same label-extraction fix. The same
   shape of bug surfaced repeatedly because no testing or code structure
   forced sibling parity.
3. **Hardcoded tables are not config-extensible.** Several knobs that
   genuinely vary across books (label-prefix routing, doubled-noun list,
   natbib variant set) live as Python module constants. Books with
   idiosyncratic conventions cannot extend without forking
   `postprocess.py`.

The pipeline is pre-1.0 by deliberate policy (no tag until a consumer
ships). This is the right moment to consolidate before any consumer
pins to a SHA.

---

## Methodology

What I looked at:

- `scripts/postprocess.py` — structure, regex density, extension points,
  hardcoded tables ([scripts/postprocess.py](scripts/postprocess.py),
  2958 lines, 113 regexes, ~25 transforms).
- `scripts/_apply_*.py` — preprocess marker passes (6 files, ~725 lines
  total).
- `scripts/validate.py` — what's actually checked at run time
  ([scripts/validate.py](scripts/validate.py), 179 lines).
- `tests/test_transforms.py` + `test_preprocessors.py` — 216 tests,
  shape coverage, fixture style.
- `LESSONS.md` / `lessons/` — 37 codified pitfalls; severity / category
  distribution.
- `CHANGELOG.md` + last 20 commits — pattern of regressions and
  follow-ups.
- `examples/book-dp1/config.yaml`, `examples/book-dp2/config.yaml` —
  config shape used in production.
- Recent issue threads (#30–#37) — the regression / incompleteness
  patterns the latest work exposed.

What I did NOT look at:

- `convert.sh` shell wrapper internals
- `_apply_*.py` algorithm/algorithmics parsers (assumed correct;
  separately reviewed in lessons 014, 023).
- The MyST / sphinx-proof rendering side — review stops at the
  `.md` output.

---

## What's working

These should not be re-litigated. Each was a deliberate choice with
evidence behind it; each continues to pay off.

| Pattern | Why it works |
|---|---|
| Per-project config + generic transforms | Three books share 95%+ of `postprocess.py`; book-specific divergence sits cleanly in `config.yaml`. Verified by reviewing dp1/dp2 configs — no transform code lives in either. |
| `uv` for project management | Zero dependency-resolution friction across MacOS / Linux contributors. Lesson 010 sealed this. |
| Lessons catalogue lifecycle (open → codified) | 37 entries, all codified, all linked from `CHANGELOG.md`. Cumulative learning across books is real and visible. |
| Hermetic regex-pipeline tests | 216 tests, ~0.2s suite. Tight feedback loop. No pandoc shell-out in tests. |
| Deterministic, no LLM in pipeline | Re-runnable; output is reviewable in diff form; book maintainers know exactly what changed when they update the tool. |
| Per-stem frontmatter + style overrides | Books that mix `absorbed` and `standalone` chapters (dp1) work without two passes. |
| Strict config schema with typo hints | `validate_config` catches `whitespace_comression` etc. with a "did you mean" suggestion. Small effort, large UX win. |
| `lessons/*.md` per-file with grep-able frontmatter | A new maintainer can `grep tags lessons/*` and find relevant pitfalls in seconds. |

---

## Risk areas

Six categories, ordered by severity-of-impact-if-not-addressed.

### A. Silent cross-reference breakage (🔴 high)

**The pattern.** Every fix in the last two batches (#30, #31, #33,
#35, #36, #37) had the same downstream symptom: a `{ref}`, `{eq}`,
`{numref}`, or `{cite}` directive resolves to nothing in the rendered
HTML, because the corresponding anchor / bib key was never emitted or
was emitted with a different name. `validate.py` did not catch any of
these — its checks are *counts*: source has 18 `\label{eq:`, output
has 18 `(eq-`, mismatch column is `0`, marked clean. But 17 of those
18 anchors had the right name and one did not; the count is preserved
while the resolution is broken.

**Evidence.**

- [scripts/validate.py:51](scripts/validate.py#L51) counts
  `\label{eq:` vs `(eq-`. Counts only. No name matching, no
  reference-side scan.
- #30: 18 broken `{eq}` refs in Deep-Learning book passed validation.
- #31, #35: lstlisting labels were never emitted as anchors;
  cross-refs to them passed validation (counted on the source side as
  `\cite[pt]?\{` doesn't include `\ref{lst:}`).
- #33: caption ref kept a wrong baked-in number; validation has no
  text-quality check.
- #37: 1 broken `multline` label passed.

**What this means at scale.** The next book validation will produce a
clean `validate.py` run, but the rendered output will have an unknown
number of broken refs. The current detection mechanism is "a careful
human compares the rendered HTML against the source PDF" — that does
not scale and does not survive a maintainer change.

**Severity assessment.** This is the single highest-leverage issue
identified by this review. Every other category in this list is one
or two follow-up commits behind a cross-ref check that would surface
the problem before it ships.

### B. Sibling-handler divergence (🔴 high)

**The pattern.** Several "families" of transforms — math envs,
citation forms, ref types, figure shapes — share enough structure
that a fix in one usually applies to all. But the codebase makes no
attempt to enforce this. The fixes happen one-at-a-time, one issue at
a time, generating predictable follow-up issues.

**Evidence.**

- Math env label extraction (`\label{}` anywhere in body):
  - #26 (2026-04-25) fixed `equation`.
  - #30 (2026-05-25) fixed `align`.
  - #37 (2026-05-26) fixed `multline` and `gather`.
  - Three months and three commits to cover four envs of the same
    semantic family. Every commit was triggered by a new book
    surfacing the same bug shape against a new env.
- Citation regex widening:
  - #32 widened key class for `:` — tested with 5 happy-path keys
    and one trailing-period case.
  - #36 surfaced the missing trailing-`:` case 24 hours later.
  - The test set for #32 did not cover the boundary-character space
    systematically.
- Pandoc-attr fence regex:
  - #31 introduced an `[^}\n]+` attribute group — tested with
    happy-path captions only.
  - #35 surfaced "real LaTeX captions contain `}`" 24 hours later.

**What this means at scale.** Every new family in the pipeline
(future biblatex variants, future custom envs, future figure shapes)
is at risk of the same one-at-a-time discovery cycle. The cost is
not the code (each fix is small) — it's the *feedback latency*
(catch-it-in-the-next-book vs catch-it-in-the-next-test-run) and
the maintainer attention required to discover the pattern repeatedly.

### C. Hardcoded conventions vs per-book variability (🟡 medium)

**The pattern.** Several "looks generic but actually book-specific"
tables live as Python module constants. Books with idiosyncratic
conventions cannot extend them without editing `postprocess.py`.

**Evidence — hardcoded tables that books need to extend:**

- [`_DOUBLED_NOUN_REFS`](scripts/postprocess.py#L82) — English
  nouns: Theorem/Lemma/Chapter/Section/etc. Hardcoded, not
  config-extensible. Any non-English book (or any book that
  introduces a new theorem-class with a custom noun like "Claim"
  or "Fact") would need to edit `postprocess.py`. A non-English
  book is not hypothetical; QuantEcon's Japanese / Chinese
  translations would hit this immediately.
- [`make_ref` label-prefix routing](scripts/postprocess.py#L587) —
  decides whether `\ref{X}` becomes `{ref}` / `{eq}` / `{numref}` /
  `{prf:ref}`. Hardcoded prefix list (`thm:`, `eq:`, `fig:`, …).
  Books that use `lst:` instead of `list:` (Deep-Learning book) or
  `prog:` instead of `code:` get `{ref}` instead of `{numref}` —
  technically works but loses auto-numbering. I noted this
  inconsistency in the #31 review but didn't fix it.
- [`_NATBIB_MARKER_ROLE`](scripts/postprocess.py#L652) — natbib
  variants only. `\textcite`, `\autocite`, `\fullcite` (biblatex
  family) are not handled. Any book that uses biblatex (rapidly
  becoming the default in newer texts) will hit silently-dropped
  citations.
- [`_DOUBLED_SECTION_SYMBOL_PREFIXES`](scripts/postprocess.py#L1388) —
  hardcoded section-prefix list. Same shape of issue.

**What this means at scale.** Each "Book N" that surfaces a new
convention requires a `postprocess.py` change *plus* a release of the
tool *plus* the consumer book pinning the new release. The friction
is highest for the convention that varies most (label prefixes), and
the upgrade story for consumers is brittle.

### D. Pipeline-order constraints implicit (🟡 medium)

**The pattern.** `process_file` is a 28-line sequence of transform
calls; the order is correct but the *constraints* that pin the order
are scattered.

**Evidence.**

- [Lesson 008](lessons/008-pipeline-ordering.md) documents 7+
  ordering rules (e.g., "fix_text_dollar must be first",
  "convert_equations before cross-refs", "convert_citations after
  environment_divs"). Maintained as a flat prose list.
- [`process_file`](scripts/postprocess.py#L2854) has 28 transform
  calls. Inline comments mark only 4 of the ~7 ordering constraints
  (e.g., "before cross-refs (lesson 020)" at line 2887). The other
  ordering constraints are unannotated.
- Lesson 008 itself doesn't track which constraints have been
  encoded in test assertions (only #27 added a true ordering-test
  via `test_simple_table_in_center_survives_pipeline_ordering`).
- 113 `re.*` calls in `postprocess.py`. Most operate on the full
  document. If a future transform is added in the wrong position,
  there is no automated check that surfaces the conflict — the
  failure mode is "downstream book validation produces weird
  output."

**What this means at scale.** As contributors arrive who didn't
write the original pipeline, the cost of "where exactly does my new
transform go?" climbs. A reorder-detector or a declared dependency
graph would be more useful than the inline comments — the latter
catch typos but don't enforce structure.

### E. Test inputs are synthetic, not real-world-shaped (🟡 medium)

**The pattern.** All 216 tests use synthetic in-line strings. They
exercise the canonical shape of pandoc output but not the messy
variations pandoc produces against real LaTeX (which has comments
mid-environment, optional args, escaped chars, math-inside-text,
text-inside-math, brace-bearing macros, weird spacing).

**Evidence.**

- Every regression in #30–#37 had a real-world LaTeX shape that
  was *not* covered by any test. Each lesson now adds the specific
  shape as a test. But:
  - The discipline is reactive (add the test after the bug).
  - There is no test pass that runs the full pipeline against
    real LaTeX excerpts from each known book.
- `fixtures/` exists per CLAUDE.md and is populated by
  `setup_fixtures.sh` for parity testing — but the unit-test suite
  doesn't touch it. So real-world LaTeX is exercised only manually
  (during parity runs), never automatically (during `uv run
  pytest`).
- Counterexample: the `_table` helper in test_transforms.py
  produces ASCII-grid table fixtures programmatically. A similar
  helper for "real-LaTeX excerpts the pipeline must survive" does
  not exist.

**What this means at scale.** The bug-discovery curve flattens as
fixtures accumulate, but only if shapes from each new book get
distilled into reusable fixtures. Currently each lesson adds one
fixture for one shape; cross-pollination across lessons doesn't
happen.

### F. Onboarding cost for new-book maintainers (🟢 low, but rising)

**The pattern.** The path "new book → first MyST build" is
documented in CLAUDE.md and the "iterative error reduction" section
is genuinely good. But there's no preflight: a book maintainer
discovers their LaTeX has a custom convention only after running
the pipeline and inspecting validation output.

**Evidence.**

- The lessons catalogue is 37 entries; a new maintainer cannot
  read them all up front. They learn by hitting issues.
- `config.yaml` is well-documented per book but doesn't surface
  "you might need to extend `_DOUBLED_NOUN_REFS`" until something
  visibly doubles in the rendered output.
- No "scan-your-source-first" step. A 5-minute scan of a new
  book's `.tex` for known-troublesome patterns (custom macros,
  unsupported envs, exotic bib keys, etc.) would warn the
  maintainer about the work ahead.

**What this means at scale.** As the number of books grows, the
ratio of new maintainers to original contributors grows.
Documentation that's discoverable rather than archeological will
matter more.

---

## Recommendations

Three tiers. Effort estimates in hours; values are "moderate-experience
contributor going at a reasonable pace."

### Tier 1 — do in the next milestone (high leverage, modest effort)

#### T1a. Cross-reference resolution check in `validate.py` (2–3h)

Single biggest leverage point in this review. Parse the produced
`.md`, collect:

- All declared anchors: `(name)=`, `:name: X`, heading auto-ids
  (`# Title {#X}`), `:label: X` in directives, code-block names.
- All references: `{ref}\`X\``, `{eq}\`X\``, `{numref}\`X\``,
  `{prf:ref}\`X\``.
- Bib keys: parse `.bib` file (already accessed via `bibliography`
  config) → collect declared keys; collect `{cite*}\`X\`` references.

Report unresolved refs and orphan anchors per chapter. The first
class catches every bug in #30, #31, #33, #35, #37 *before* the
build step. The second class catches `\label{}` that were extracted
but never referenced — useful for editorial cleanup.

Wire into `validate.py` behind a `validate.cross_ref_resolution`
config flag (default `true`). Existing count check stays.

#### T1b. Shape catalogue tests for transform families (4–6h)

For each family with sibling handlers, introduce a parametrized
test that runs *every* handler against *every* relevant input
shape. Three families to start:

- **Math envs**: `(equation, align, multline, gather)` × `(no
  label, label after \begin, label mid-body, label at end, label
  per row)` — 20 cells. Each cell asserts: (a) anchor exists in
  output, (b) `\label{}` not in body, (c) shape-specific
  invariants.
- **Cite forms**: textual `@key`, bracketed `[@key]`, multi-cite,
  natbib marker → product with `(plain key, colon-bearing key, key
  followed by .;:,!)\]}\s$)`. Locks the boundary behavior
  systematically.
- **Figure shapes**: markdown `![cap](path){#id}` × HTML
  `<figure id="X"><img/><figcaption>...</figcaption></figure>` ×
  `(no caption, plain caption, caption with ref, caption with
  brace-bearing macro)` — locks the work from #25, #31, #33, #35
  together.

When a fix is needed for one cell, the test grows by adding the
specific input — and every sibling automatically re-exercises.
Sibling divergence becomes structurally hard to introduce.

#### T1c. Config hooks for hardcoded tables (3h)

Promote three tables to config-extensible:

```yaml
# In config.yaml:
cross_ref_routing:
  - { prefix: "lst",  role: "numref" }   # extends default mapping
  - { prefix: "prog", role: "numref" }

doubled_noun_refs:
  - { noun: "Claim",      prefix: "claim-" }   # extends default list
  - { noun: "Conjecture", prefix: "conj-" }

extra_natbib_variants:
  textcite:  { role: "cite:t", parens: false }   # biblatex
  autocite:  { role: "cite:p", parens: false }
```

Default behavior unchanged (existing books need zero config
change). Books with idiosyncratic conventions extend without
forking. Each addition is ~15 lines in `postprocess.py` plus 2
lines of schema.

The biblatex coverage in particular unblocks an entire class of
book (newer manuscripts default to biblatex over natbib).

### Tier 2 — do in the milestone after that (medium leverage, larger effort)

#### T2a. Pipeline-order dependency annotation (3–5h)

For each transform function in `postprocess.py`, declare its
dependencies as a small comment header:

```python
def convert_citations(text: str) -> str:
    """
    Order:
      after: convert_cross_references, decode_natbib_markers,
             convert_environment_divs
      before: resolve_listings, resolve_algorithms
    """
```

Then a small `tests/test_pipeline_order.py` parses these
annotations and asserts the call order in `process_file` satisfies
every declared constraint. A reorder either fails the test
immediately or requires updating the annotations (which is the
right discipline).

Lower-effort alternative if topological-sort feels heavy: just
require every `process_file` line to carry a `# before: X` /
`# after: Y` trailing comment when it matters, and have a
linter-style script that diff-checks the comments against lesson
008.

#### T2b. Real-world fixtures in the test pass (6–8h)

Add `tests/fixtures_real/<book>/` containing 20–50 short LaTeX
excerpts per book (carbon-tax caption, ECTA bib key, multline
derivation, etc.). Run the full pipeline against each fixture.
Assertions are minimal — "doesn't crash; output passes structural
validate". Bug-find rate per fixture is high because real LaTeX
exposes shapes synthetic tests don't.

Maintenance: when a new bug surfaces in a book, distill the
shape into a fixture in the same commit. Over time these become
the "shape catalogue" T1b imagines, populated by real input.

#### T2c. `postprocess.py` module split (4–6h, cosmetic but worth it at this size)

2958 lines in one file is past the comfort threshold. Reasonable
split:

```
scripts/transforms/
    math.py         # convert_equations, fix_text_dollar, join_split_inline_math
    refs.py         # convert_cross_references, strip_doubled_noun_refs, …
    figures.py      # convert_figures, convert_html_figures, resolve_tikz_figures
    code.py         # convert_pandoc_attr_code_blocks, resolve_listings, …
    cite.py         # convert_citations, decode_natbib_markers
    envs.py         # convert_environment_divs, convert_description_lists
    frontmatter.py  # add_frontmatter, convert_section_labels
    typography.py   # cleanup_typography, ensure_blank_after_display_math, …
scripts/postprocess.py  # orchestrator: imports + process_file
```

Pure mechanical refactor. Tests untouched. `process_file` becomes
the only place a contributor needs to read to understand the
sequence. Each transform module is 200–400 lines, browseable.

### Tier 3 — defer, document the option

#### T3a. `--strict` mode that fails CI on validation warnings (1h)

A consumer book that wants "broken refs are blocking" can opt in.
Trivial wrapper around the existing validation output.

#### T3b. Preflight scanner for new books (4–6h)

A `scripts/preflight.py` that scans a fresh book's `.tex` and
reports likely issues *before* the first conversion run: custom
macros pandoc will drop, unsupported envs, bib keys with `:`,
custom theorem types, etc. Catches the issues lessons 022, 028,
029 surface at the latest possible moment, well earlier.

#### T3c. Per-book parity snapshot tests (effort scales with number of books)

`reports/` has parity reports but they're prose. A snapshot test
that re-runs the pipeline against fixture inputs and asserts
"output byte-identical to expected.md" catches inadvertent
behavior change across releases. Effort is mostly initial
snapshot capture; maintenance is a `pytest --update-snapshots`
when a transform legitimately changes output shape.

---

## Execution plans

This section turns the recommendations above into concrete, ordered
work items. Each plan is self-contained — a contributor should be
able to execute it without further questions.

**Phase ordering (dependency-driven).** Phase 0 lays the test safety
net that makes the rest of the work low-risk. Phase 1 is the
high-leverage validation + config work. Phase 2 broadens test
coverage. Phase 3 does the structural refactor. Phase 4 (Tier 3
items) is deferred and not detailed here.

```
Phase 0 (safety nets) → Phase 1 (validation + config) →
Phase 2 (shape tests) → Phase 3 (structural refactor)
```

Within a phase, items are independent and can be done in any order.

---

### Phase 0 — Test safety net

Prerequisite for any structural refactor. Without these, T2c
(module split) and T2a (ordering annotations) are risky against the
current 155-direct-call test surface.

#### P0a — `pytest-cov` baseline visibility (15min, no deps)

**Goal:** see which transforms are well-covered and which are not,
so subsequent phases prioritise weak spots.

**Approach:**
1. Add `pytest-cov` to `[dependency-groups].dev` in `pyproject.toml`.
2. Update `scripts/test.sh` to emit a coverage report (`--cov=scripts
   --cov-report=term-missing:skip-covered`).
3. Run baseline. Note the headline figure in this section of the
   review. Do NOT enforce a minimum — coverage gates this early
   would just create busywork.

**Files touched:** `pyproject.toml`, `scripts/test.sh`.

**Verification:** `bash scripts/test.sh` prints coverage. Baseline
number recorded here as a reference point.

**Baseline (2026-05-26):** 69% total, 70% on `postprocess.py`.
Notable gaps: `_apply_rewrites.py` (32%) and `_config.py` (18%) are
both shell-driven entry points exercised end-to-end via `convert.sh`
rather than unit tests — coverage understates their real exercise.
`validate.py` at 49% is genuine — the `main()` orchestration path
isn't unit-tested. P1a will lift this materially.

#### P0b — Pipeline-order assertion test (45min, no deps)

**Goal:** lock the current canonical order in `process_file` so a
reorder fails CI explicitly rather than silently corrupting output.
Codifies [lesson 008](lessons/008-pipeline-ordering.md).

**Approach:**
1. Inspect `process_file` via `inspect.getsource()`; parse the
   `text = X(text)` call sequence using a regex.
2. Compare against a checked-in `EXPECTED_PIPELINE_ORDER` constant in
   the test file.
3. When a contributor intentionally reorders, they update the
   constant — explicit, visible, reviewable.
4. Bonus: also assert each line carries either no comment (clean) or
   a `# before/after` ordering note (declared intent).

**Files touched:**
- New `tests/test_pipeline_order.py` (~50 lines).
- No changes to `postprocess.py`.

**Verification:** `uv run pytest tests/test_pipeline_order.py -v`
passes. Manual sanity: swap two adjacent transforms in
`process_file`, re-run, test fails with a clear diff.

#### P0c — Golden-file pipeline tests (3–4h, no deps)

**Goal:** lock current end-to-end behaviour against ~15 real
pandoc-output snippets so any refactor that changes downstream
output is loud.

**Approach:**

1. **Refactor `process_file` to expose an in-memory inner function.**
   Currently it does file I/O + transform pipeline. Split into:

   ```python
   def process_text(text: str, stem: str, title: str, *,
                    style: str | None = None) -> str:
       # all 28 transforms, no I/O
       ...

   def process_file(input_path: Path, output_path: Path = None):
       text = input_path.read_text(encoding='utf-8')
       stem = input_path.stem
       title = CHAPTER_TITLES.get(stem, stem)
       out = process_text(text, stem, title,
                          style=CHAPTER_STYLES.get(stem))
       (output_path or input_path).write_text(out, encoding='utf-8')
   ```

   This is a pure refactor — no behaviour change. The 1 existing
   end-to-end test stays green.

2. **Capture initial fixtures.** Run the current pipeline against
   a curated set of pandoc-output snippets (one per transform
   family). Check the input AND the current output into
   `tests/golden/`:

   ```
   tests/golden/
     math_equation_label_after_body.in.md
     math_equation_label_after_body.out.md
     math_align_per_row_labels.in.md
     math_align_per_row_labels.out.md
     math_multline_trailing_label.in.md
     math_multline_trailing_label.out.md
     cite_textual_colon_key.in.md
     cite_textual_colon_key.out.md
     cite_natbib_marker_citep.in.md
     cite_natbib_marker_citep.out.md
     ref_caption_with_section_ref.in.md
     ref_caption_with_section_ref.out.md
     code_pandoc_attr_with_braces_in_caption.in.md
     code_pandoc_attr_with_braces_in_caption.out.md
     figure_html_subfigure_nested.in.md
     figure_html_subfigure_nested.out.md
     table_simple_two_col.in.md
     table_simple_two_col.out.md
     env_theorem_to_prf.in.md
     env_theorem_to_prf.out.md
     section_label_with_unnumbered_class.in.md
     section_label_with_unnumbered_class.out.md
     listing_minted_block.in.md
     listing_minted_block.out.md
     algorithm_2e_block.in.md
     algorithm_2e_block.out.md
     description_list_term_labels.in.md
     description_list_term_labels.out.md
     full_minichapter_kitchen_sink.in.md   # one bigger one
     full_minichapter_kitchen_sink.out.md
   ```

   15 pairs covering every transform family + 1 integration
   "kitchen sink" snippet.

3. **Test runner.** New `tests/test_golden.py` with a parametrized
   test:

   ```python
   @pytest.mark.parametrize("name", _golden_names())
   def test_golden(name):
       input_text = (GOLDEN_DIR / f"{name}.in.md").read_text()
       expected   = (GOLDEN_DIR / f"{name}.out.md").read_text()
       actual = postprocess.process_text(input_text, stem=name,
                                         title=name.replace("_", " "))
       assert actual == expected, _diff(actual, expected)
   ```

   Plus an env-var `UPDATE_GOLDEN=1 uv run pytest` mode that
   overwrites `.out.md` with the current output — the deliberate
   "I changed behaviour intentionally" workflow.

4. **Initial capture process.** Generate the input fixtures by
   running pandoc against handpicked LaTeX excerpts from
   `fixtures/` (or the Deep-Learning book). Capture the output
   fixtures by running the current pipeline. Manually inspect each
   `.out.md` before checking in — they're the contract.

**Files touched:**
- `scripts/postprocess.py` — extract `process_text` from
  `process_file` (~30 lines refactored, no behaviour change).
- New `tests/golden/` directory with 15 .in/.out pairs.
- New `tests/test_golden.py` (~40 lines).

**Verification:**
- All 15 golden tests pass.
- Manually mutate one transform (e.g. break the citation regex);
  the relevant golden test fails with a readable diff.
- `UPDATE_GOLDEN=1` regenerates the `.out.md` files; checking the
  git diff makes the change auditable.

---

### Phase 1 — Validation + config

#### P1a — Cross-reference resolution check (2–3h, deps: P0c helpful but not required)

**Goal:** catch broken `{ref|eq|numref|prf:ref|cite}` directives at
validation time, not at downstream-build time. The single
highest-leverage item in this review.

**Approach:**

1. **Collect declared anchors from the MyST output:**
   - `(name)=` standalone-label syntax (already produced by
     `convert_standalone_labels` and the new align/multline
     anchors).
   - `:name: X` inside directives (figures, code blocks, prf
     blocks).
   - Heading auto-ids from `# Title {#X}`.
   - Section labels from `convert_section_labels` output.

2. **Collect references from the MyST output:**
   - `{ref}\`X\``, `{eq}\`X\``, `{numref}\`X\``, `{prf:ref}\`X\``,
     `{cite*}\`X\`` (where `cite*` is `cite`, `cite:t`, `cite:p`,
     `cite:author`, `cite:year`).
   - Multi-key cite forms: `{cite}\`a,b,c\`` → split on comma.

3. **Parse the bibliography .bib file** (using the existing
   `bibliography` config key + `source_dir`) to collect declared
   bib keys.

4. **Report diagnostics:**
   - Unresolved refs: `{ref}\`X\`` with no declared anchor named
     `X`. Print `file:N: unresolved {ref}\`X\``.
   - Unresolved cite keys: cite to key not in `.bib`. Print
     similarly.
   - Orphan anchors (optional, separate flag): declared but
     never referenced. Useful editorially; not gating.

5. **Wire into `validate.py`:**
   - New config flag `validate.cross_ref_resolution` (default
     `true`).
   - New config flag `validate.orphan_anchors` (default `false` —
     informational only).
   - Existing count-based check unchanged.

**Files touched:**
- `scripts/validate.py` — new `_collect_anchors`,
  `_collect_references`, `_parse_bib_keys`,
  `check_resolution` functions (~120 lines added).
- `scripts/postprocess.py` — extend `_CONFIG_SCHEMA` for the new
  `validate.*` flags.
- New tests in `tests/test_validate.py` (or extend existing).

**Verification:**
- New test: known-broken MyST (anchor named `eq-foo`, reference
  `{eq}\`eq-bar\``) produces `unresolved` diagnostic.
- New test: anchor + matching reference produces no diagnostic.
- Manually run against the Deep-Learning book output (pre-fix
  state, restored from a stashed copy if needed): confirms it
  flags exactly the 30+ broken refs from #30, #31, #33, #37.

#### P1b — Config hooks for hardcoded tables (3h, no deps)

**Goal:** let books extend three currently-hardcoded tables
without forking `postprocess.py`. Defaults unchanged; existing
configs need zero modification.

**Approach:**

1. **`cross_ref_routing`** (extends `make_ref` in
   `convert_cross_references`):

   ```yaml
   cross_ref_routing:
     - { prefix: "lst",  role: "numref" }
     - { prefix: "prog", role: "numref" }
   ```

   Default routing table stays as the Python constant inside
   `make_ref`. Config entries pre-pend to the lookup, so a book
   can override default routing too if needed.

2. **`doubled_noun_refs`** (extends `_DOUBLED_NOUN_REFS`):

   ```yaml
   doubled_noun_refs:
     - { noun: "Claim",      prefix: "claim-" }
     - { noun: "Conjecture", prefix: "conj-" }
   ```

   Append-only — defaults stay, books extend with their custom
   theorem-class nouns.

3. **`extra_natbib_variants`** (extends `_NATBIB_MARKER_ROLE`):

   ```yaml
   extra_natbib_variants:
     textcite:  { role: "cite:t", parens: false }
     autocite:  { role: "cite:p", parens: false }
     fullcite:  { role: "cite",   parens: false }
   ```

   Pairs with extending `_apply_rewrites.py` to emit the same
   bracket-marker sentinel for these biblatex variants.

4. **Module-level state, set by `apply_config`:**
   ```python
   _EXTRA_CROSS_REF_ROUTING: list[tuple[str, str]] = []
   _EXTRA_DOUBLED_NOUN_REFS: list[tuple[str, str]] = []
   _EXTRA_NATBIB_VARIANTS: dict = {}
   ```

   `apply_config` populates these from the config dict; transforms
   read them. Same pattern as `CHAPTER_TITLES` /
   `TIKZ_FIGURE_MAP`.

5. **Schema additions** in `_CONFIG_SCHEMA` for the three new keys.

**Files touched:**
- `scripts/postprocess.py` — schema + three extension points +
  `apply_config` updates (~50 lines added across file).
- `scripts/_apply_rewrites.py` — biblatex variant detection
  (~20 lines if we ship the citation half).
- New tests in `tests/test_transforms.py` covering each extension
  point (~6 tests).

**Verification:**
- New tests pass; existing tests pass unchanged (default behaviour
  preserved).
- Demo: add `lst → numref` routing to `examples/book-dp1/config.yaml`
  (book-dp1 may or may not have `lst:` labels — check first; if not,
  use a synthetic config in tests instead).

---

### Phase 2 — Shape catalogue tests

#### P2a — Shape catalogue tests for transform families (4–6h, deps: P0c useful)

**Goal:** make sibling-divergence (the #30→#37 pattern) structurally
hard to introduce.

**Approach:**

1. **Math env shape matrix.** New
   `tests/test_math_env_shapes.py`. Parametrize over:

   ```python
   ENVS = ['equation', 'align', 'multline', 'gather']
   SHAPES = [
       'no_label',
       'label_after_begin',
       'label_mid_body',
       'label_at_end',
       'label_per_row',  # only meaningful for align/gather
   ]
   ```

   20 cells (some are no-ops — `multline` "per row" is the same
   as "at end" since multline is conceptually one equation).
   Each cell asserts:
   - The expected anchor exists (`(eq-X)=` or trailing
     `$$ (eq-X)`).
   - `\label{}` does NOT appear in the output body.
   - For single-equation envs, the math content survives intact.

2. **Cite form × boundary matrix.** Extend
   `test_citation_textual_key_boundary` (already parametrized
   over 6 cases) to also cover bracketed form `[@key]`, natbib
   markers, and multi-cite — all crossed against the boundary
   set. ~24 parametrize cells.

3. **Figure shape matrix.** Cover (markdown `![cap](path)`, HTML
   `<figure>`, HTML `<figure>` with nested subfigures) ×
   (no caption, plain caption, caption with `\ref{}`, caption
   with brace-bearing macro). ~12 cells.

**Files touched:**
- New `tests/test_math_env_shapes.py` (~100 lines).
- Extend `tests/test_transforms.py::test_citation_textual_key_boundary`.
- New `tests/test_figure_shapes.py` (~80 lines).

**Verification:**
- All new tests green.
- Manually mutate `replace_math_block` (e.g., make it not handle
  trailing labels); the multline+gather cells fail. Mutate align's
  `_extract_math_labels`; the per-row cells fail across align AND
  multline AND gather. Sibling divergence is now detectable.

---

### Phase 3 — Structural refactor

#### P3a — `postprocess.py` module split (4–6h, deps: P0b + P0c)

**Goal:** reduce the 2958-line monolith to ~8 themed modules of
200–400 lines each. `process_file` becomes the only orchestration
point a contributor needs to read.

**Approach:**

1. **Create `scripts/transforms/` package** with `__init__.py`
   that re-exports the public symbols (so external imports of
   `postprocess.convert_X` continue to work).

2. **Theme the modules:**

   ```
   scripts/transforms/__init__.py
   scripts/transforms/_helpers.py    # convert_label_colons, brace-balanced helpers
   scripts/transforms/math.py        # convert_equations + helpers
   scripts/transforms/refs.py        # convert_cross_references,
                                     # strip_doubled_*, strip_footnote_refs
   scripts/transforms/figures.py     # convert_figures, convert_html_figures,
                                     # resolve_tikz_figures
   scripts/transforms/code.py        # convert_pandoc_attr_code_blocks,
                                     # resolve_listings
   scripts/transforms/cite.py        # convert_citations, decode_natbib_markers
   scripts/transforms/envs.py        # convert_environment_divs (ENV_MAP),
                                     # convert_description_lists
   scripts/transforms/frontmatter.py # add_frontmatter,
                                     # convert_section_labels,
                                     # convert_standalone_labels
   scripts/transforms/typography.py  # cleanup_typography,
                                     # ensure_blank_after_display_math,
                                     # strip_blank_lines_in_math,
                                     # join_split_inline_math
   scripts/transforms/algorithms.py  # _algpseudo_*, _algo_*,
                                     # resolve_algorithms, resolve_algorithmics
   scripts/transforms/tables.py      # convert_simple_tables
   scripts/transforms/epigraphs.py   # convert_epigraphs (small, could merge)
   ```

3. **`scripts/postprocess.py` shrinks to:**

   ```python
   #!/usr/bin/env python3
   """Orchestrator. Each transform lives in scripts/transforms/."""

   from transforms import *  # noqa: F401, F403  (test-import surface)
   from transforms.math import convert_equations, fix_text_dollar
   from transforms.refs import convert_cross_references, ...
   # ... etc

   # CHAPTER_TITLES, TIKZ_FIGURE_MAP, _CONFIG_SCHEMA stay here
   # (they're orchestration state, not per-transform state)

   def process_text(text, stem, title, *, style=None):
       # The 28 calls, same order as before.
       ...

   def process_file(input_path, output_path=None):
       ...

   def main():
       ...
   ```

4. **Execution order:** one transform-family per commit. Each
   commit is `git mv` + `from transforms.X import Y` re-export +
   `pytest`. The P0c golden tests catch any unintended behaviour
   change.

5. **Test surface preservation:** all 251 existing tests continue
   to use `from postprocess import ...` (top-level
   `tests/test_transforms.py` does `import postprocess`). Because
   `postprocess.py` re-exports every symbol from the themed
   modules, this import path remains stable. Zero test edits.

**Files touched:**
- `scripts/postprocess.py` → shrinks dramatically (from 2958 to
  ~200 lines).
- New `scripts/transforms/*.py` files.
- No test files touched.

**Verification:**
- All 251 tests pass after each per-family commit.
- All P0c golden tests pass throughout.
- `bash scripts/test.sh` exit code 0 at every commit boundary.

#### P3b — Pipeline-order dependency annotation (3h, deps: P0b)

**Goal:** transform functions declare their ordering constraints
in docstrings; the test from P0b extends to verify the declared
constraints are satisfied by `process_text`'s call sequence.

**Approach:**

1. **Annotation convention.** Add a small ordering header to
   each transform's docstring:

   ```python
   def convert_citations(text: str) -> str:
       """
       Order:
         after: convert_cross_references, decode_natbib_markers,
                convert_environment_divs
         before: resolve_listings, resolve_algorithms
       ...
       """
   ```

   Plain prose, parsed by a simple regex. Each transform declares
   the constraints relevant to it; redundant constraints (B after
   A and A before B) are OK and self-documenting.

2. **Audit lesson 008** — extract every ordering rule, attach it
   to the relevant transform. Each rule cites the lesson that
   pinned it (`# lesson 008` etc.).

3. **Extend `tests/test_pipeline_order.py`** to topologically
   verify: for every declared `after: X`, the called function X
   appears before the current in `process_text`. For every
   declared `before: Y`, Y appears after.

**Files touched:**
- Every transform function in `scripts/transforms/*.py` —
  docstring header (~5 lines per transform × ~25 transforms =
  ~125 lines of pure docstring).
- `tests/test_pipeline_order.py` — extend from P0b with the
  constraint-parsing logic (~40 lines).

**Verification:**
- Constraint parsing test runs and passes.
- Manually mutate the order in `process_text`; the test fails
  with a clear "X must be after Y" message.
- Lesson 008 audit complete: every ordering rule from the
  lesson appears as a declared constraint on some transform.

---

### Recommended execution order

1. **P0a** (15min) — coverage baseline. Cheap visibility before
   anything else.
2. **P0b** (45min) — pipeline-order assertion. Locks current order.
3. **P0c** (3–4h) — golden-file tests. The safety net everything
   downstream depends on. Includes the `process_text` extraction.
4. **P1a** (2–3h) — cross-ref resolution check. Highest-leverage
   single change in the entire review.
5. **P1b** (3h) — config hooks. Unlocks book-specific extension
   without forking.
6. **P2a** (4–6h) — shape catalogue. Locks sibling parity.
7. **P3a** (4–6h) — module split. Now safe to do because P0c
   covers cross-cutting behaviour.
8. **P3b** (3h) — ordering annotations. Builds on P0b.

**Total Phase 0 + 1 + 2 + 3:** ~22–30 hours. Naturally splits
across multiple sessions.

**Estimated chronology if executed contiguously:**
- Phase 0 — 1 working day
- Phase 1 — 1 working day
- Phase 2 — 1 working day
- Phase 3 — 1–2 working days

---

## What NOT to change

Documented here so they don't get re-litigated:

- **Regex pipeline, no LLM.** Determinism + diff-reviewability + zero
  rate-limit-on-build are non-negotiable. Confirmed by CLAUDE.md
  "settled architectural decisions" — and confirmed again here.
- **`uv` as project manager.** Lesson 010, settled.
- **Lessons catalogue lifecycle.** Open → codified, one .md per
  lesson, indexed in `LESSONS.md`. Works.
- **Hermetic tests with no pandoc shell-out.** Speed and CI
  reliability depend on it. Real-LaTeX fixtures (T2b) should
  pre-process via pandoc *once* and check in the pandoc output
  alongside the LaTeX, so the test pass itself stays pandoc-free.
- **Per-project-config-only-for-divergence.** Generic transforms in
  `postprocess.py`; project knobs in `config.yaml`. T1c extends this
  surface, doesn't violate it.
- **Pre-1.0 tagging policy.** Hold v0.1.0 until a consumer ships.
  Memory `feedback_release_tagging_policy.md` confirms this; this
  review concurs.

---

## Open questions for the maintainer

These aren't recommendations — they're decisions only the maintainer
should make:

1. **Internationalization scope.** Are non-English QuantEcon
   translations on the medium-term roadmap? If yes, the doubled-noun
   list (T1c) becomes higher priority and probably needs a
   per-language profile rather than just an extend-the-list hook.
2. **biblatex priority.** How many imminent books use biblatex vs
   natbib? If biblatex is dominant for the next few books, T1c's
   biblatex extension moves into Tier 1a urgency. The Deep-Learning
   book already mixes both.
3. **Consumer-pinning model.** Books pin via `mystmd/.tool-version`
   — to a SHA, `main`, or a future tag. Once a consumer pins to a
   SHA, breaking changes are free but visibility into "tool has
   moved on" is low. Worth deciding: do we provide a `tool-bump`
   mechanism that explicitly migrates a book's pin and re-runs
   validation, or rely on book maintainers to bump ad-hoc?
4. **Tier 2c module split.** Worth doing, but breaks any
   in-flight branch or external review. Coordinate with downstream
   book maintainers before splitting — or do it as the very first
   commit after a clean release point.
5. **Validation as gate vs warning.** Currently `validate.py` exits
   non-zero on mismatch. T1a's cross-ref check could either gate
   (consumer build fails) or warn (consumer build proceeds, prints
   diagnostics). The defaults should be loud for during-conversion
   workflows and quiet enough for repeat-builds — probably means a
   `--strict` flag (T3a).

---

## Closing observation

The single mental model worth carrying out of this review:
**count-based validation will not survive the next ten books.**
Every category-A regression in #30–#37 escaped a clean
`validate.py` run. The fix is mechanical (T1a) and within an
afternoon's work. After that's in place, the cost of every other
recommendation drops, because the feedback loop tightens from
"caught in the next book validation against a PDF" to "caught in
this book's CI run before the maintainer even sees the output."

Do T1a first. Decide on T1b and T1c in parallel. The rest can
wait.
