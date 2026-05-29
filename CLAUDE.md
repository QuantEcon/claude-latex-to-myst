# CLAUDE.md

Instructions for Claude when working in `claude-latex-to-myst` or in a book
repo that uses this pipeline.

## What this repo is

A reusable LaTeX → MyST Markdown conversion pipeline. The hard work has been
done — see `scripts/postprocess.py`, `scripts/preprocess.sh`, `scripts/convert.sh`.
**Do not re-derive these from scratch.** Adapt them via `config.yaml`.

### Code layout

- `scripts/postprocess.py` — orchestrator. Defines `process_text` (the
  in-memory pipeline) and `process_file` (the I/O wrapper). Owns the
  module-level mutable state populated by `apply_config`: `ENV_MAP`,
  `CHAPTER_TITLES`, `TIKZ_FIGURE_MAP`, `_EXTRA_CROSS_REF_ROUTING`,
  `_EXTRA_DOUBLED_NOUN_REFS`, `_LISTING_SOURCE_BASE`, `POSTPROCESS_REWRITES`,
  the frontmatter/whitespace style flags, and the per-file exercise
  counters.
- `scripts/transforms/` — themed transform modules: `math.py`, `refs.py`,
  `cite.py`, `figures.py`, `code.py`, `envs.py`, `tables.py`,
  `tables_from_latex.py`, `typography.py`, `algorithms.py`,
  `frontmatter.py`. Each module owns one family of transforms; tests
  still import via `postprocess.convert_X` (re-exported from the top
  of `postprocess.py`).
- `scripts/_apply_*.py` — preprocess scripts that run BEFORE pandoc.
  Each rewrites a specific LaTeX construct (algorithms, listings,
  description lists, tables) into a marker comment that pandoc passes
  through verbatim; the post-pandoc pass decodes the marker back into
  the target MyST shape. Patterns: `_apply_algorithm_markers.py`,
  `_apply_listing_markers.py`, `_apply_description_markers.py`,
  `_apply_table_markers.py`. Use this pattern when pandoc's reader
  drops or mangles structure you need to preserve (lessons 014, 015,
  022, and #51 / #55 for tables).
- `scripts/transforms/_helpers.py` — shared helpers (currently just
  `convert_label_colons`). Add here when a helper is needed by ≥2 transform
  modules.

**Adding a new transform.** Drop it into the appropriate `transforms/*.py`,
add a re-import in `postprocess.py`'s import block, and a call in
`process_text` at the right ordering position (update
`tests/test_pipeline_order.py::EXPECTED_PIPELINE_ORDER` too). If the
transform needs mutable state, add it to `postprocess.py` and late-import
inside the function — that's the established pattern; module docstrings
mark this with a "State coupling" header.

## How to approach a new book conversion

1. **Read [`lessons/`](lessons/) first.** Every lesson there is a pitfall
   someone has already hit. Grep the lessons before writing new transforms.
2. **Edit `config.yaml`, not the scripts.** Chapter list, bib filename,
   custom-macro pre-rewrites, and the TikZ map are all configurable. If you
   find yourself editing `postprocess.py` for project-specific reasons, that
   reason probably belongs in config.
3. **Run the pipeline; categorize errors; fix the largest category.** See
   *Iterative error reduction* below — one regex fix usually eliminates
   dozens of build errors.
4. **Capture new lessons.** When you hit a non-obvious bug, run
   `/capture-lesson` to add it to the catalogue. Future-you (or future-Claude)
   will thank you.

## Iterative error reduction

Conversion is iterative, not one-shot. The first pipeline run on a new
book typically produces hundreds of MyST build warnings. The fast path
to "clean build" is **always** category-first, never error-by-error:

1. **Run the pipeline.** `bash scripts/convert.sh --config mystmd/config.yaml`
2. **Build the output.** `cd mystmd && myst build --html 2>&1 | tee build.log`
3. **Categorize what came out.** Group warnings by kind, not by source
   location. A typical opening shape:

   ```bash
   grep -oE '(duplicate_id|xref_not_found|math_parse|directive_unknown)' build.log \
     | sort | uniq -c | sort -rn
   ```

   Or, when the patterns aren't obvious yet, a one-off Python counter:

   ```python
   import collections, re
   counts = collections.Counter()
   for line in open('build.log'):
       m = re.search(r'(\w+_\w+)', line)
       if m:
           counts[m.group(1)] += 1
   for cat, n in counts.most_common():
       print(f'{n:5d}  {cat}')
   ```

4. **Fix the highest-count category first.** Almost always this means a
   single regex transform in `postprocess.py` (or a single new
   `config.yaml` rewrite rule), not 50 hand-edits to source files.
5. **Re-run from step 1.** Recount; the category you just fixed should
   now be gone or much smaller. Take the next-largest category.
6. **Stop when the remaining errors are genuinely per-file edge cases.**
   At that point hand-fix the markdown directly — but only at that
   point. Hand-fixing too early means losing the fix on the next re-run.

If a category is mechanically fixable and the same shape will appear in
the next book, **codify it as a lesson + a pipeline transform** rather
than as a hand-edit (per the "When to capture a lesson vs. fix the
pipeline" section below). The lesson catalogue exists so the same hour
of debugging never happens twice.

## Genuinely generic vs project-specific

| Generic (rarely edited) | Project-specific (in config or overrides) |
|-------------------------|-------------------------------------------|
| `ENV_MAP` defaults (theorem, lemma, etc.) | Chapter list & per-stem `frontmatter_style` |
| All transform functions in `postprocess.py` | `CHAPTER_TITLES` (frontmatter titles) |
| KaTeX compatibility fixes | Bibliography filename |
| Cross-ref / citation / figure regex | `preprocess.rewrites`/`strip` (LaTeX-side fixes) |
| Blank-line-in-math handling | `postprocess.rewrites` (editorial Markdown fixes) |
| Pipeline ordering | `preprocess.split` (multi-chapter source files) |
| Natbib variant decoding | `TIKZ_FIGURE_MAP` / `TIKZCD_INLINE_MAP` |

If a transform feels too book-specific, it probably belongs in a project
overrides file, not in `postprocess.py`.

## When to capture a lesson vs. fix the pipeline

- **Capture as lesson + leave pipeline alone:** rare edge case, project-specific
  workaround, KaTeX/MyST behavior worth documenting but not worth automating.
- **Capture as lesson + codify in pipeline:** affects ≥2 projects, mechanically
  fixable, would be missed if not automated. Mark the lesson `status: codified`
  and reference the fix location.
- **The bar for codifying:** "would someone hit this on the next book?" If yes,
  fix it in the pipeline now; the cost of the regex is far less than the cost
  of re-debugging it in 6 months.

## Don't

- Don't rewrite `postprocess.py` from scratch. Read it, adapt it.
- Don't add LLM calls to the pipeline — it must be deterministic and re-runnable.
- Don't commit `mystmd/tmp/` or `_build/` from any consuming book repo.
- Don't promote a lesson from `open` to `codified` without actually adding the
  fix to the pipeline and verifying.

## Settled architectural decisions

Don't re-litigate these without checking. Each was resolved deliberately:

- **Per-project config + generic transforms.** Chapter list, custom-macro
  rewrites, TikZ overrides live in `config.yaml` / `tikz_overrides.py`.
  Transforms live in `postprocess.py`. If something feels "too dp1-specific"
  or "too dp2-specific" inside `postprocess.py`, it probably belongs in
  config. Editorial decisions the tool can't infer from LaTeX (e.g.
  promoting `**Bold heading**` to `## H2` only in specific chapters)
  go in `config.postprocess.rewrites`, not in `postprocess.py`.
- **Book-specific *programmatic* edge cases live book-side, governed by a
  graduation rule.** Declarative fixes go in `config.yaml`
  (`preprocess.rewrites`/`strip`/`split`, `postprocess.rewrites`,
  `extra_environments`, `cross_ref_routing`). When an edge case needs
  *code* and only one book hits it, it goes in that book's
  `project_overrides.py` (the generalized successor to `tikz_overrides.py`
  — a book-side file with a **closed** set of extension points: data maps,
  extra rewrites, and one optional named post-hook (`POST_CONVERT`)). **The rule:** one book
  needs it → book-side override; a **second** book needs it → it graduates
  into the generic pipeline with a lesson + a golden case. This makes the
  over-/under-specialization tradeoff a *location* decision with a counting
  rule, keeping `postprocess.py` generic by construction. It is **not** a
  plugin framework (no registration, no arbitrary lifecycle/ordering) — a
  closed override file with documented insertion points. The mechanism is
  built on the `ConversionContext` from
  [phase 3](notes/design/phase-3-conversion-context.md) (overrides
  contribute to the context, never mutate module globals); design in
  [phase 5](notes/design/phase-5-book-overrides.md).
- **Route every fix by repo tier.** Three repos can hold a change; pick
  deliberately, because the tier decides *where* it's committed and whether
  it's a code change at all.
  - **Tier 1 — `claude-latex-to-myst` (the converter).** Genuine conversion
    bugs and transforms that generalize across books are fixed here (the bulk
    of the work), each with a golden case. Prefer this whenever the tool *can*
    emit correct, supported MyST.
  - **Tier 2 — a consuming book repo (`book-dp1`/`book-dp2`/…).** One-book
    editorial polish, a hand-curated file, or a book-only `config.yaml`
    rewrite goes to that book's **`mystmd-conversion` branch only** (never its
    default branch), or an **issue** on the book repo. This is the
    book-overrides graduation rule's "one book → book-side" tier; a gitignored
    `fixtures/<book>/` copy is for testing, **not** a book-side fix.
  - **Tier 3 — `QuantEcon/mystmd` (the publisher).** An **unsupported MyST
    feature / rendering incompatibility** (the tool emits correct, spec-valid
    MyST that mystmd can't publish) is an **issue only** — never a workaround
    here that degrades output. Record the affected fixture as documented drift.

  Decision test when torn between tiers 1 and 3: **malformed MyST ⇒ tier 1
  (fix the converter); valid-but-unrendered ⇒ tier 3 (file upstream).**
- **`uv` is the project manager.** Not pip, not conda, not raw venv. Per
  lesson [010](lessons/010-pep-668-system-python.md).
- **No Perl in the pipeline.** Per lesson [009](lessons/009-bsd-sed-mapfile-portability.md).
  Both algorithm and listing preprocessors are Python ports of dp1's Perl
  originals (`scripts/_apply_algorithm_markers.py`,
  `scripts/_apply_listing_markers.py`).
- **No LLM calls inside the pipeline.** It must be deterministic and
  re-runnable. LLM-driven cleanup happens in the user's editor session,
  not in `convert.sh`.
- **Lessons catalogue: one .md per lesson with frontmatter.** New lessons
  via `/capture-lesson`. Lifecycle: `open` → `codified` once the fix is in
  the pipeline. Lessons are never deleted.
- **Reports format — and which reports live here.** A report that documents
  *durable, tool-level* learnings — what a parity investigation revealed,
  what worked/didn't, and which **pipeline change** it motivated — belongs
  committed in `reports/`. A *per-run or per-book* artifact — the ongoing
  drift ledger for one consumer book, a session handover, scratch parity
  output — does **not**: it stays local or travels to the consumer repo
  (e.g. the book's `mystmd-conversion` branch), per the user's standing
  preference. Rule of thumb: if it motivates a commit *to this repo*, commit
  the report here; if it tracks the state of *one book's conversion*, keep
  it with that book. When unsure, write it and ask "commit, or keep local?"
- **Fixture-based verification.** Parity tests run against local copies of
  sibling book repos under `fixtures/` (gitignored, populated by
  `scripts/setup_fixtures.sh`). Never run the pipeline directly inside
  `../book-dp1` or `../book-dp2` — those may have in-progress branches
  you'd disturb.
- **Fence-aware transforms use a fence-stack state machine, not regex
  pairing of openers and closers.** Any transform that needs to know
  whether a line is inside a fenced code block / inline-code span /
  content directive walks the text line-by-line, maintaining
  `[(tick_count, kind), …]` on a stack. Closers are identified by the
  stack (a bare `` ``` `` of ≥ the top's tick count pops), never by a
  second regex match. Stash/restore tricks for "code vs content"
  regions are also rejected — a single in-place scan keeps content-loss
  classes (marker-leakage, restore-order bugs) structurally impossible.
  Established by `fix_spacing_superscript` (math.py) after four
  iterations of regex-pairing bugs (#84, #85, #86, #87); see lesson
  [042](lessons/042-katex-thin-space-superscript-needs-empty-base.md)
  for the rationale.
- **The pandoc/marker boundary is explicit (Phase 2).** *Pandoc owns
  inline prose, paragraph/inline math, native inline citations
  (`\cite`/`\citet`/`\citep`), and cross-ref plumbing (the
  `data-reference` recovery path). Everything structural — floats,
  tabulars, algorithms, listings, description/enumerate lists — is
  extracted to a marker pre-pandoc and decoded post-pandoc. New
  structural constructs follow the marker pattern; do not add a new
  post-pandoc HTML-scraping path.* The shared scaffolding for the
  constructs whose cells need pandoc conversion (figure, table) lives once
  in [`transforms/_markers.py`](scripts/transforms/_markers.py)
  (`pandoc_batch_convert`, `encode_payload`/`decode_payload`,
  `reassemble`) — **plain functions, not a `MarkerPlugin` class** (the win
  is deduplication, not extensibility). A marker preprocessor's
  "should I marker-ize this block?" decision must be **purely syntactic
  and conservative**: bail (return `None`) on any shape it can't fully
  model, because it runs pre-pandoc and cannot see post-pandoc config
  (`TIKZ_FIGURE_MAP`, `ENV_MAP`, routing) — the #98 #3 lesson. The audited
  per-construct bail predicates are documented at the top of
  `transforms/_markers.py`. Retiring the post-pandoc HTML fallbacks (one
  path per construct) is the Phase-4 payoff; the boundary is locked now so
  it stops moving by accretion.

## Working-style conventions

- **Verify before committing.** Run the relevant parity check from
  `reports/README.md`. If the diff doesn't match documented drift,
  something has changed unexpectedly.
- **Capture lessons with `/capture-lesson`.** The point of the catalogue
  is cumulative learning across many books; please feed it.
- **When closing an open lesson**, flip its status from `open` to
  `codified`, fill in `codified_in:`, and update the index entry in
  `LESSONS.md`. Don't delete the lesson.
- **The user prefers terse responses** with concrete file paths, line
  numbers, and clear scope estimates. Don't over-explain; do tell them
  honestly when something is bigger than initially scoped.
- **Git user is `Matt McKay <mamckay@gmail.com>`.** Commits in this repo
  use `-c user.name=... -c user.email=...` flags rather than config;
  continue that pattern.
