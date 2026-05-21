# Changelog

All notable changes to `claude-latex-to-myst` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Books pin the tool with `mystmd/.tool-version` — pointing at a tag once
one exists, `main` for "always latest" (the current recommendation while
the project is pre-release), or a SHA for fully-reproducible pinning.

## [Unreleased]

No tagged releases yet. The first tag (`v0.1.0`) is held back until at
least one downstream book repo (`book-dp1`, `book-dp2`) is in production
on this pipeline — tagging earlier would freeze a contract that consumers
haven't validated. Everything below is on `main` and available now.

### Added — pipeline transforms

- **`convert_simple_tables`** ([d6dcbe7]): pandoc 2-column `simple_tables`
  (the common glossary shape) become MyST `{list-table}` directives.
  3+ column tables pass through untouched. Captions migrate to the
  directive's `:caption:` option. Handles both `simple_tables` (one row
  per line) and `multiline_tables` (blank-line-separated rows).
  Closes FIX Issue 1 / lesson 019.
- **Class-attribute stripping in `convert_section_labels`** ([5a17cb6]):
  pandoc's `# Title {#slug .unnumbered}` attribute blocks no longer leak
  class tokens into MyST labels. Lesson 017.
- **Explicit `\label{}` preference in `add_frontmatter`** ([5a17cb6]):
  when a chapter has both a heading auto-id and an explicit body
  `\label{}`, the explicit label wins as the frontmatter `label:`.
  Guarded so a following section anchor isn't accidentally promoted.
  Lesson 018.
- **`decode_natbib_markers`** ([9870687]): natbib variants pandoc collapses
  ambiguously (`\citep`, `\citealp`, `\citealt`, `\citeauthor`,
  `\citeyear`, `\citeyearpar`) are now rewritten in preprocess to
  bracket-marker sentinels and decoded post-pandoc to the right
  `{cite:*}` role. Closes FIX Issue 3 / lesson 020.
- **Pandoc `[-@key]` (suppress-author) decoding** ([9870687]): renders
  as `{cite:year}` rather than being eaten by the textual `@key` regex.
- **Algorithm2e support** (`_apply_algorithm_markers.py` +
  `resolve_algorithms`) — ported from dp1's Perl original to Python.
  All algorithm blocks become `{prf:algorithm}` directives.
  Lesson 014.
- **Minted source listings support** (`_apply_listing_markers.py` +
  `resolve_listings`) — ports `\begin{listing}…\inputminted…` to
  `{code-block}` directives with `:name:` and `:caption:`. Adds
  `source_code_base:` config option. Lesson 015.
- **`strip_doubled_section_symbol`** — drops `§` before `{ref}` to a
  section-style label (qe-v5 book-mode auto-renders the prefix).
  Lesson 016.

### Added — config-driven features

- **Per-file `frontmatter_style:` override** ([9bdd1f0]) on `chapters[]`
  and `extra_files[]` entries. Books that mix standalone and absorbed
  styles (dp1: numbered chapters standalone + front-matter absorbed)
  no longer need separate runs.
- **`postprocess.rewrites:` config section** ([edc7040]): book-specific
  Markdown rewrites with optional `stems:` scoping, run after all
  generic transforms but before validation. Closes the gap where
  editorial decisions the tool can't infer from LaTeX (e.g. promoting
  `**Bold heading**` to `## H2` in a specific file) were lost on every
  regen.
- **`preprocess.split:` config section** ([e7b65dc]): consolidated
  multi-chapter source files (e.g. dp1's `book/appendix.tex` with
  three `\chapter{}` blocks) are split at chapter boundaries before
  per-stem preprocessing. `skip_extra: true` discards trailing
  chapters not listed in `into:`.
- **`frontmatter_style:`** ([8ab7556]) — global choice between
  `absorbed` (YAML block, default) and `standalone` (body `(label)=` +
  `# Heading`, dp1 style).
- **`whitespace_compression:`** ([8ab7556]) — `readable` (default) vs
  `compact` (collapses blanks between adjacent directives).
- **`extra_environments:` / `skip_environments:`** ([066807e]) — extend
  the default ENV_MAP / div-skip set without touching `postprocess.py`.

### Added — validation

- **Structural validation** (`scripts/validate.py`, [cc17444]) —
  counts equations, theorems, figures, cross-refs, citations in
  source vs. output. Reports per-chapter mismatches.
- **`validate.broken_inline_math`** ([af44cb5]) — flags inline math
  whose continuation line opens with `>` (silently parsed as a
  blockquote marker by MyST). Folds in book-dp1's standalone
  `_find_broken_math.py`.
- **Config schema validator** ([cc17444]) — rejects unknown keys and
  bad types with typo hints.

### Added — consumer-side workflow

- **Vendored book wrapper** (`scripts/templates/book-convert.sh`,
  [0a1e3b0]): a ~90-line shell wrapper that books ship in their own
  `mystmd/convert.sh`. It clones the tool into `_tools/` at the version
  pinned in `.tool-version`, fast-forwards on each run, and delegates
  to the shared pipeline. Books never depend on a sibling clone.
  Override hooks: `CLAUDE_LATEX_TO_MYST_URL`,
  `CLAUDE_LATEX_TO_MYST_TOOLS`.
- **`scripts/new-book.sh`** ([0a1e3b0]) — scaffolds a book's `mystmd/`
  directory with `config.yaml`, the wrapper, and a default
  `.tool-version`. Appends `_tools/` to the book repo's `.gitignore`.
- **Book-side post-conversion steps** ([e7ccd7b]): the wrapper no
  longer uses `exec` to delegate. Books can append project-specific
  steps (TikZ rendering, llms.txt generation, custom validators)
  after the delegation line; the whole flow runs from one
  `bash mystmd/convert.sh` invocation.

### Added — examples and docs

- **`examples/book-dp1/`** ([8ab7556]) and **`examples/book-dp2/`**
  ([1e2dc1a]) reference configurations.
- **`reports/`** — parity reports per book (`book-dp2-parity.md`,
  `book-dp1-parity.md`); see [reports/README.md](reports/README.md).
- **`lessons/`** — 20 catalogued pitfalls. See
  [LESSONS.md](LESSONS.md) for the index and
  [lessons/README.md](lessons/README.md) for the schema.
- **Iterative-error-reduction workflow** documented in
  [CLAUDE.md](CLAUDE.md) — category-first, never error-by-error.

### Added — tooling

- **`uv` as the project manager** ([e73d8a4]) — pins Python via
  `.python-version`, manages deps via `pyproject.toml` + `uv.lock`.
  No PEP 668 dance, no system Python required. Lesson 010.
- **`scripts/setup_fixtures.sh`** ([066807e]) — bootstraps local
  copies of sibling book repos under `fixtures/` (gitignored) so
  parity tests never touch in-progress branches in `../book-dp1` /
  `../book-dp2`.
- **`scripts/test.sh`** ([cc17444]) — runs the pytest suite. 96
  tests at 0.1.0.

### Changed

- **Pipeline ordering** ([223bd12]): `resolve_listings` and
  `resolve_algorithms` now run AFTER `convert_citations` so inlined
  source code isn't mangled (e.g. Julia `@views` was being eaten as
  a textual cite). Lesson 015.

### Fixed

- **`convert_equations` regex bug** ([9118518]) — surfaced during the
  algorithm port; previously labelled `equation*` blocks were
  mishandled. See lesson 014's "side bug" section.
- **`§ Section X.Y` doubled prefix** ([8ab7556]) — dp2's qe-v5 book
  mode auto-renders "Section X.Y" for heading refs, which collided
  with the author's manual `\S\ref{}`. 471 dp2 occurrences → 0.
  Lesson 016.
- **Algorithm2e edge cases** ([315e8f2]) — commented-out
  `\begin{algorithm}` blocks no longer rewritten; `\textnormal{}`
  inside algorithm bodies preserved; unbraced `\Return` accepted.
- **Duplicate `# Title` after frontmatter** ([#3]): when `\chapter{X}`
  in source has no `\label{}`, pandoc emits a bare `# X` that
  `add_frontmatter` couldn't absorb (its regex required an anchor).
  Combined with a config-supplied `title: X` this rendered two
  identical headings in a row. `add_frontmatter` now strips a bare
  body H1 when it exactly matches the configured title; mismatched
  titles (author wrote two distinct things) are left alone. Closes
  [#3].

[#3]: https://github.com/QuantEcon/claude-latex-to-myst/issues/3

### Settled architectural decisions

- **No LLM calls inside the pipeline.** Determinism and
  re-runnability are non-negotiable; LLM-driven cleanup happens in
  the editor session, not in `convert.sh`.
- **No Perl in the pipeline** ([9118518], [223bd12]) — both
  algorithm and listing preprocessors are Python ports. Lesson 009.
- **No system Python** — see lesson 010 / `uv` adoption.
- **Per-project config + generic transforms** — chapter list,
  custom-macro rewrites, TikZ overrides live in `config.yaml` /
  `tikz_overrides.py`; transforms live in `postprocess.py`.
- **Fixture-based verification** — never run the pipeline directly
  inside a sibling book repo.
- **Lessons never deleted** — `open` → `codified` lifecycle;
  superseded lessons get marked, not removed.

### Known issues / deferred

- **GH issue [#1](https://github.com/QuantEcon/claude-latex-to-myst/issues/1)** —
  LaTeX `---`/`--` to Unicode em/en-dash. Real but cosmetic; full
  scope analysed in the issue. Not blocking dp1 adoption.

[Unreleased]: https://github.com/QuantEcon/claude-latex-to-myst/commits/main

[e7b65dc]: https://github.com/QuantEcon/claude-latex-to-myst/commit/e7b65dc
[edc7040]: https://github.com/QuantEcon/claude-latex-to-myst/commit/edc7040
[af44cb5]: https://github.com/QuantEcon/claude-latex-to-myst/commit/af44cb5
[e7ccd7b]: https://github.com/QuantEcon/claude-latex-to-myst/commit/e7ccd7b
[9bdd1f0]: https://github.com/QuantEcon/claude-latex-to-myst/commit/9bdd1f0
[9870687]: https://github.com/QuantEcon/claude-latex-to-myst/commit/9870687
[d6dcbe7]: https://github.com/QuantEcon/claude-latex-to-myst/commit/d6dcbe7
[5a17cb6]: https://github.com/QuantEcon/claude-latex-to-myst/commit/5a17cb6
[315e8f2]: https://github.com/QuantEcon/claude-latex-to-myst/commit/315e8f2
[0a1e3b0]: https://github.com/QuantEcon/claude-latex-to-myst/commit/0a1e3b0
[cc17444]: https://github.com/QuantEcon/claude-latex-to-myst/commit/cc17444
[066807e]: https://github.com/QuantEcon/claude-latex-to-myst/commit/066807e
[8ab7556]: https://github.com/QuantEcon/claude-latex-to-myst/commit/8ab7556
[223bd12]: https://github.com/QuantEcon/claude-latex-to-myst/commit/223bd12
[9118518]: https://github.com/QuantEcon/claude-latex-to-myst/commit/9118518
[1e2dc1a]: https://github.com/QuantEcon/claude-latex-to-myst/commit/1e2dc1a
[e73d8a4]: https://github.com/QuantEcon/claude-latex-to-myst/commit/e73d8a4
