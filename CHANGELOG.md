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
- **Mid-line hypertarget marker in proof bodies** ([#4]): pandoc
  renders `\begin{proof}[Proof of ...]\label{p:foo}` with the
  `[]{#p:foo label="p:foo"}` marker between the opener and the
  proof body — a position none of the existing three patterns in
  `convert_environment_divs` matched. Added a 4th pattern that
  catches mid-line markers, strips them, and promotes the label
  to `:label:` on the directive (with `convert_label_colons`
  kebab-casing). For `\begin{proof}\label{p:foo}` (bare opener
  with label), the residual `*Proof.*` is also stripped so
  sphinx-proof's auto-rendered opener doesn't double up. Closes
  [#4].
- **Doubled plural noun before `{prf:ref}`** ([#5]): prose like
  `Chapters {prf:ref}` followed by multi-target refs left the leading
  plural intact (`strip_doubled_noun_refs` only knew singular forms),
  rendering as "Chapters Chapter 5 and Chapter 7" — sphinx-proof
  doubles the noun on the first ref. Added plural forms to
  `_DOUBLED_NOUN_REFS` (Chapters, Theorems, Lemmas, Algorithms,
  Exercises, Propositions, Corollaries, Assumptions, Remarks). The
  prefix-match guard applies to plurals the same as singulars.
  Multi-target shapes (`X and Y`, `X--Y`, lists with `,`) don't need
  extra handling: only the leading plural-noun token is redundant.
  Fresh dp1 output drops to zero doubled-plural sites (committed dp1
  via its legacy pipeline still has 9 — that's the deliberate
  improvement drift the migration parity report will note).
  Closes [#5].
- **`tikz_overrides.py` replacements broke under Python 3.13** ([#7]):
  `resolve_tikz_figures` passed `entry['replacement']` as a regex
  replacement string. Python 3.13 hardened the parser to reject
  unknown backslash escapes (`\h`, `\P`, etc.) as `re.PatternError`,
  where 3.9-3.12 had only warned. Authors naturally write LaTeX
  (`\hat`, `\Phi`, `\beta`) in their override entries, so this
  blocked every Python 3.13 invocation. Replacement is now wrapped
  in a lambda so `re.sub` treats it as a literal string — escapes
  are no longer parsed at all. Backreferences (`\1`, `\g<name>`)
  are no longer supported in this code path; no current consumer
  uses them. Closes [#7].
- **`strip_blank_lines_in_math` regex over-matched across inline
  `$$ … $$` and unrelated prose** ([#12]): the [#11] regex used
  ``\$\$\n(.*?)\n\$\$`` without anchoring the opening ``$$`` to a
  line start, so a bullet ending with an inline-closing ``$$``
  (e.g. ``- text $$x$$\n``) was matched as a block-math opener and
  the non-greedy ``(.*?)`` extended across the following bullets /
  prose until it found the next real ``\n$$``, collapsing every
  blank line in between. Anchored the opener with
  ``^\$\$\n`` under ``re.MULTILINE | re.DOTALL`` — an inline
  closing ``$$`` is never at line start so it can't be misread as
  an opener. Verified on dp2 fixture: 2 mis-collapsed sites in
  ch_egs.md restored to proper paragraph separation; dp1's #11 fix
  still resolved (zero whitespace-only lines in any display-math
  block across both books). Closes [#12].
- **Display math blocks emit trailing blank line → MyST hard error**
  ([#11]): pandoc preserves LaTeX source whitespace verbatim, and
  ``cleanup_typography`` strips ``\qedhere`` AFTER ``convert_equations``
  runs. The result is a whitespace-only line just before the closing
  ``$$`` (the preserved indentation of the line ``\qedhere`` lived
  on), which MyST treats as an empty math node and rejects with
  ``No input for math node``. Added ``strip_blank_lines_in_math``
  to collapse internal blank lines in ``$$ … $$`` blocks and strip
  the body. Wired into ``process_file`` immediately after
  ``cleanup_typography`` so the run-order dependency is explicit.
  Verified on dp1 fixture: one hard error becomes zero; no
  whitespace-only lines remain in any display-math block across the
  fresh output. Closes [#11].
- **Multi-label environments leak orphan inline anchors** ([#10]):
  LaTeX writers sometimes attach more than one ``\label{}`` to a
  single environment (``\begin{Exercise}\label{a}\label{b}``) so the
  block can be cross-referenced under multiple identifiers. The
  original anchor-extraction loop in ``convert_environment_divs``
  overwrote ``label`` on each match, so only the LAST anchor was
  promoted and earlier ones survived as inline ``[]{#X label="X"}``
  artifacts at the start of the body — broken cross-refs in MyST.
  Refactored to a ``findall`` + ``sub`` approach (matches dp1's
  legacy structure): first anchor becomes ``:label:`` on the
  directive; subsequent anchors are emitted as sibling
  ``{div}`` blocks above the directive, each becoming its own valid
  cross-ref target. Also extended ``convert_standalone_labels`` to
  strip residual mid-line orphan anchors that survive both passes
  (typically ``\footnote{\label{fn:foo}…}`` artifacts — MyST
  footnotes are addressed via ``[^N]``, so the label has no MyST
  destination). Fresh dp1 output: zero orphan anchors remain across
  three previously-broken sites (Exercise w/ two labels, Proposition
  w/ two labels, footnote w/ label). Closes [#10].
- **Full-word `algo:` / `eg:` label prefixes routed to `{ref}`
  instead of `{prf:ref}`** ([#9]): the routing tuple in
  `convert_cross_references` had abbreviated prefixes (`alg:`, `ex:`)
  that didn't match dp1/dp2's actual source labels (`algo:foo` for
  algorithms, `eg:foo` for examples). Both fell through to `{ref}`,
  which resolves to the directive's caption text — so 30 dp1
  algorithm refs and 66 example refs rendered the full caption
  inline instead of "Algorithm N" / "Example N". Added `'algo:'`,
  `'algo-'`, `'eg:'`, `'eg-'` to the `{prf:ref}` branch. Also added
  `('Example', 'eg-')` / `('Examples', 'eg-')` to
  `_DOUBLED_NOUN_REFS` so prose like `Example {prf:ref}\`eg-foo\``
  dedupes. The `eg-` case is a pre-existing bug shared by dp1's
  legacy pipeline — fix lands as a quality improvement at the same
  time. Closes [#9].
- **`list-*` cross-refs and "Listing Program N" doubled noun** ([#8]):
  two coupled bugs in code-block listing references.
  `convert_cross_references` routed `list:` / `list-` labels to
  `{ref}`, which resolves to the caption text (so MyST dumped the
  entire caption inline). Routes to `{numref}` now — same rationale
  as `algo-` → `{prf:ref}` for `prf:algorithm`. And
  `strip_doubled_noun_refs` didn't know about "Listing" / "Program"
  noun forms; the broader regex change in this commit also lets it
  match `{numref}` refs (previously only `{prf:ref}`), so prose like
  `Listing {numref}\`list-foo\`` now de-doubles cleanly. Fresh dp1
  output: 45 list-refs routed correctly, zero doubled "Listing
  Program N" sites. Closes [#8].
- **Unlabeled subfigures silently dropped images** ([#17]): a
  `\begin{figure}` containing multiple `\begin{subfigure}` blocks
  where the subfigures had no individual `\label{}` collapsed into a
  single `{figure}` directive — only the first subfigure's image
  survived. Pandoc emits each subfigure as `<embed src="…">` inside a
  nested HTML `<figure>` with no `id`; the old
  `convert_html_figures.replace_nested` ignored `<embed src>` and
  always produced an admonition placeholder, then the unlabeled
  placeholders for inners 2+ hit the "orphaned sub-panel — skip"
  branch in `resolve_tikz_figures` and vanished. Fix: detect
  `<embed src>` and emit a real `{figure}` directive directly using
  the embed source path (bypassing the TikZ-placeholder round trip),
  and auto-generate `{outer-label}-{a,b,…}` names for unlabeled
  inners so each subfigure gets a distinct, cross-refable label. The
  TikZ path (`\input{tikz/…}` with no `<embed>`) is unchanged.
  Double-masked until [#15] was fixed — the old validator's
  figure-blind counting reported a clean `10/10` while the rendered
  output was missing an image. Lesson [021]. Closes [#17].
- **`validate.py` false-positive mismatches** ([#14], [#15], [#16]):
  three independent count blind spots in `scripts/validate.py` that
  produced spurious `!` markers and diluted the validator's signal.
  - **Commented-out LaTeX envs counted** ([#14]): `count_latex` now
    strips whole-line `%` comments before counting, so a deliberately
    commented `\begin{lemma}` no longer bumps the theorems column.
    Mid-line trailing comments (`\begin{lemma} % TODO`) are preserved
    so the live env still counts.
  - **Figures column ignored subfigures** ([#15]): a `\begin{figure}`
    containing N `\begin{subfigure}` blocks emits N `{figure}`
    directives on the MyST side (outer wrapper discarded), but the
    old LaTeX-side regex counted only the wrapper. New
    `_count_figures_latex` walks each figure block and contributes
    `max(subfigures, 1)`. (Reporter's diagnosis attributed the
    discrepancy to `\input{tikz/...}` resolution; verified against
    dp2 fixture that subfigures are the actual cause.)
  - **MyST equation count missed labeled-close fences** ([#16]):
    labeled blocks close with `$$ (eq-foo)`, which the bare-fence
    regex (`^\$\$\s*$`) didn't match. `count_myst` now sums bare and
    labeled-close fences before `// 2`, restoring labeled blocks to
    the equation count. Fixed a ~25% under-count on every chapter
    using labeled equations.
  - Adds `tests/test_validate.py` (previously zero coverage). On the
    dp2 fixture, `theorems` and `figures` columns are now 100% clean;
    remaining `!` markers are genuine off-by-one discrepancies the
    validator is supposed to surface.
- **Natbib citations with locator args silently dropped key** ([#13]):
  `\citep[p.~351]{key}` (and the other 5 natbib variants with one or
  two `[…]` optional args) slipped past the preprocess rewrite, which
  required `{` to follow the command name directly. Pandoc then
  emitted `[@key, p.~351]`, and the downstream multi-cite regex
  couldn't terminate inside that bracket group, producing an empty
  `{cite}` role. `_NATBIB_REWRITES` now matches up to two optional
  `[…]` groups before `{key}` and discards them (MyST's `{cite:*}`
  roles have no locator-suffix syntax). One known occurrence in
  book-dp1 (`ch_rdps.tex:3381`) restored. Lesson 020 updated.
  Closes [#13].

[#3]: https://github.com/QuantEcon/claude-latex-to-myst/issues/3
[#4]: https://github.com/QuantEcon/claude-latex-to-myst/issues/4
[#5]: https://github.com/QuantEcon/claude-latex-to-myst/issues/5
[#7]: https://github.com/QuantEcon/claude-latex-to-myst/issues/7
[#8]: https://github.com/QuantEcon/claude-latex-to-myst/issues/8
[#9]: https://github.com/QuantEcon/claude-latex-to-myst/issues/9
[#10]: https://github.com/QuantEcon/claude-latex-to-myst/issues/10
[#11]: https://github.com/QuantEcon/claude-latex-to-myst/issues/11
[#12]: https://github.com/QuantEcon/claude-latex-to-myst/issues/12
[#13]: https://github.com/QuantEcon/claude-latex-to-myst/issues/13
[#14]: https://github.com/QuantEcon/claude-latex-to-myst/issues/14
[#15]: https://github.com/QuantEcon/claude-latex-to-myst/issues/15
[#16]: https://github.com/QuantEcon/claude-latex-to-myst/issues/16
[#17]: https://github.com/QuantEcon/claude-latex-to-myst/issues/17
[021]: lessons/021-unlabeled-subfigures-silent-image-drop.md

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
