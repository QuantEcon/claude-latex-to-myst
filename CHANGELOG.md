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

- **`_warn_dropped_text_macros`** ([#22]): a new preprocess step that
  scans the source preamble(s) for custom text macros pandoc will
  silently drop (`\DeclareUrlCommand`, `\newcommand` bodies that wrap
  `#1` in macros pandoc doesn't know like `\textcolor`/`\urlstyle`),
  counts usages across the chapters, and prints a single warning
  with a paste-ready `preprocess.rewrites` block. Level 1 (warn) from
  the issue proposal — pipeline does not auto-rewrite because the
  conversion is lossy and the user should opt in. Surfaced converting
  a book that used `\tpath{…}` 160 times and got every occurrence
  silently dropped along with its argument. Lesson [028]. Closes [#22].
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
- **`lessons/`** — 28 catalogued pitfalls. See
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

- **`\label{}` extraction not applied to `multline` / `gather`**
  ([#37]): incompleteness from [#30]. That fix unified the
  ``align`` handlers to scan the body for any ``\label{}``, but
  ``multline`` and ``gather`` kept the original "label immediately
  after ``\begin``" assumption — and the dominant LaTeX convention
  for ``multline`` puts the label at the *end* of the body.
  Unified both envs the same way: single handler, all labels
  extracted, first label trailing, rest stacked as anchors above.
  Renamed the helper ``_extract_align_labels`` →
  ``_extract_math_labels`` since it now serves three envs.
  1 broken ``{eq}`` ref in the Deep-Learning book.
  Lesson [037]. Closes [#37].
- **Pandoc-attr fence regex stopped at the first `}` inside a quoted
  caption value** ([#35]): direct regression from the [#31]
  ``convert_pandoc_attr_code_blocks`` introduction — the attribute
  group ``[^}\n]+`` terminated at the first ``}`` from
  ``\texttt{X}`` / ``\textbf{X}`` / math etc., so any lstlisting
  with a styled caption was silently skipped. Rewrote the attribute
  group as quote-aware: ``[^}"\n]`` outside quotes OR a complete
  ``"..."`` run where ``}`` is permitted. The outer closing ``}``
  still unambiguously terminates the block. Lesson [036]. Closes
  [#35].
- **Textual `@key` citation regex swallowed trailing `:` from prose**
  ([#36]): direct regression from the [#32] widening — adding `:`
  to the boundary lookahead meant ``\citet{key}: explanation`` had
  the prose colon captured into the key. 9 sites broken in the
  Deep-Learning book. Fix encodes the asymmetric constraint
  (`:` legal *inside* the key, not at the *end*) directly in the
  capture pattern: ``[a-zA-Z][a-zA-Z0-9_:]*[a-zA-Z0-9_]``; boundary
  reverted to the pre-#32 form so `:` in prose terminates the match.
  Parametrized test now covers trailing colon, semicolon, period,
  and space across both plain and colon-bearing keys. Lesson [035].
  Closes [#36].
- **Textual `@key` citation regex truncated colon-bearing bib keys**
  ([#32]): JabRef / Mendeley / ACM-style keys (`Author:Year:Tag`)
  were captured only up to the first `:`, leaving the suffix as
  literal text after a broken `{cite:t}` role. Extended the key
  character class (and its mirroring boundary lookahead) to allow
  `:`; the bracketed multi-cite branch was already colon-tolerant.
  5 sites across 3 chapters of the Deep-Learning book. Lesson [031].
  Closes [#32].
- **Per-row `\label{}` inside multi-row `\begin{align}` lost**
  ([#30]): a labelled derivation chain (each row carries its own
  `\label{eq:X}`) survived pandoc untouched, then `convert_equations`
  wrapped the body in `\begin{aligned}` and left the labels inside —
  KaTeX silently drops them, so every `\eqref{}` to a per-row label
  resolved to nothing. Both align branches now extract every
  `\label{}` and emit each as a `(eq-X)=` anchor stacked above the
  `$$ … $$` block. Numbering collapses (all anchors target the same
  block) but cross-refs all resolve — preferable to broken refs.
  18 labels → >30 broken `{eq}` references in the Deep-Learning
  book. Lesson [032]. Closes [#30].
- **`\ref{}` inside `\caption{}` rendered as a chapter-unaware
  number** ([#33]): pandoc resolves cross-refs inside caption
  arguments during the LaTeX→Markdown step, computing the number
  from the single-chapter file pandoc sees rather than the whole
  book. `convert_html_figures.extract_caption` then stripped HTML
  wholesale, discarding the `data-reference` attribute and
  preserving the wrong pre-resolved number as plain text. Now
  converts the `<a data-reference="X">N</a>` tag to `{ref}\`X\``
  before stripping HTML, so MyST resolves with full project
  context. Re-runs `strip_doubled_noun_refs` /
  `strip_doubled_section_symbol` on the caption string locally
  (the project-level passes ran earlier in `process_file`). 10
  caption sites in the Deep-Learning book. Lesson [033]. Closes
  [#33].
- **`lstlisting` `caption=` / `label=` dropped — no anchor, no
  caption** ([#31]): pandoc handles `lstlisting` natively, emitting
  a fenced code block with a pandoc-attribute info string
  (`\`\`\` {#lst:X .python caption="…" label="lst:X"}`). MyST does
  not honour pandoc's attribute syntax — the `{…}` is treated as an
  arbitrary info string and dropped, so no anchor target is emitted
  and any `\ref{lst:X}` resolves to nothing. New transform
  `convert_pandoc_attr_code_blocks` parses the attribute block; if
  an `#id` or `caption=` is present it emits a `{code-block}`
  directive with `:name:` / `:caption:`; otherwise it strips the
  attribute block to a plain fenced code block (avoiding the
  broken-info-string render). Guarded against re-processing MyST's
  own directive fences (different whitespace shape). Lesson [034].
  Closes [#31].
- **Pipeline ordering: `convert_simple_tables` runs before
  `convert_environment_divs`** ([#27]): the GH #24 fix bounded the
  multiline-table forward scan on the `:::` fenced-div boundary, but
  `convert_environment_divs` strips `::: center` wrappers (via
  `ENV_SKIP`). In the original ordering the boundary was already gone
  by the time the table pass ran, so on books that wrap tabulars in
  `\begin{center}` (the dominant convention) the #24 fix never fired
  and adjacent tables fused again — identical symptom to the pre-#24
  bug. Reordered `process_file` so the table pass runs first; added
  `test_simple_table_in_center_survives_pipeline_ordering` that
  composes both transforms in production order so the ordering
  invariant is enforced in CI (the existing direct-call tests
  couldn't see it). Lesson [025] extended with the followup. Closes
  [#27].
- **Inline `\itemsep<dim>` on a list opener confused pandoc inside
  nested lists** ([#28]): the common manuscript shorthand
  `\begin{itemize}\itemsep1pt` (no space between env-open and the
  inline `\itemsep`) is tolerated by pandoc at top level but breaks
  when the construct is nested inside another list/description env.
  Pandoc lexes `\itemsep` as a 1-arg macro it doesn't know, drops the
  command, keeps the argument as orphan text, and falls back to
  `% Unknown environment: itemize` — corrupting the chapter for every
  following figure. `\itemsep` is a TeX low-level spacing command with
  no MyST analogue regardless, so `_apply_rewrites` now strips it
  globally as a built-in (alongside the natbib rewrites), matching
  any signed decimal dimension and an optional trailing `\\` line
  break. Pairs with [#29] to retire the local `mystmd/config.yaml`
  workaround the Deep-Learning book was carrying. Lesson [030].
  Closes [#28].
- **`_apply_description_markers` consumed `\item` markers inside nested
  itemize/enumerate** ([#29]): the flat `_ITEM_RE.finditer(body)` in
  `_split_items` matched every `\item` regardless of nesting depth, so a
  description body containing a nested `\begin{itemize}…\end{itemize}`
  had its inner `\item` lines silently replaced with `<!--DESCITEM
  term=-->` markers — leaving the nested env with zero items. Pandoc
  then dropped the empty `itemize` as `% Unknown environment: itemize`
  and the malformed output cascaded into MyST dropping every `{figure}`
  directive that followed in the chapter (6 figures in ch02 of the
  Deep-Learning book). Rewrote `_split_items` to walk a sorted timeline
  of open/close/item events and only emit a description item when the
  current nest depth is 0; inner `\item` markers pass through verbatim
  for pandoc to handle in their natural list context. Lesson [029].
  Closes [#29].
- **`convert_equations` orphan `\label{}` + DOTALL regex swallowed
  figures between equations** ([#26]): the labelled-extract pass
  required `\label{}` *immediately after* `\begin{equation}` and
  silently skipped the dominant `\begin{equation} body \label{eq:foo}
  \end{equation}` convention, leaving an orphan `\label{}` in the
  body. The catch-all `$$ … \label{} … $$` cleanup ran with `DOTALL`
  and `(.*?)`, so the engine paired the orphan label with the nearest
  prior inline `$$math$$` — sometimes 60+ lines back — and swallowed
  every paragraph, figure, and directive in between (~15 figures
  silently dropped in the book that surfaced this; one fused match
  measured at 8,127 chars). Two changes: (1) collapse the labelled/
  unlabelled equation passes into one that extracts `\label{}` from
  anywhere inside the body; (2) bound the standalone-label cleanup
  to a single line (`[^\n]*?`, no DOTALL). Lesson [024]. Closes [#26].
- **`convert_simple_tables` forward scan ran past the table region**
  ([#24]): pandoc renders `\begin{center}\begin{tabular}…` as a
  multiline_table inside a `::: center` div with an opening dash-rule
  but no closing one. The forward scan looked only for a matching
  closing rule and ran on until it found one — typically the *next*
  table's opening rule pages later — fusing the two tables and all
  intervening prose into one mangled `{list-table}`. Bound the scan
  on the fenced-div boundary (`:::` close or new `:::` open) and
  preserve that boundary in output when the scan stops on it rather
  than on a rule line. Extends lesson [019]. Lesson [025]. Closes [#24].
- **`convert_html_figures` mis-classified plain `\includegraphics`
  figures as TikZ admonitions** ([#25]): pandoc emits `<img src=…>`
  for ordinary `\includegraphics` and `<embed src=…>` for
  `\input{tikz/…}`. Pass 1 (nested subfigures) only recognised
  `<embed>`, and Pass 2 (non-nested) skipped the image-source check
  entirely and unconditionally produced an admonition — so every
  plain figure became a "TikZ — needs manual conversion" placeholder
  (10 of 88 in the book that surfaced this). Unified the regex
  (`<(?:embed|img)>`) into a shared `_figure_src_re` and mirrored
  the Pass 1 image-check into Pass 2. Lesson [026]. Closes [#25].
- **Pandoc's empty `<!-- -->`{=html} lexer-defeat separator survived
  into MyST output** ([#23]): pandoc inserts the empty raw-HTML span
  between adjacent inline tokens to keep CommonMark's lexer from
  merging them (e.g. `$\sim$\`<!-- -->\`{=html}30 s`). MyST has
  stricter tokenisation and doesn't need the separator, so it surfaced
  as raw text in rendered HTML (14 occurrences across 6 chapters in
  the book that surfaced this). New `strip_pandoc_html_separators`
  runs as the first step of `process_file` and removes the artifact
  unconditionally. Lesson [027]. Closes [#23].
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
- **`\textbf{...$math$...}` mangled by naive brace regex** ([#21]):
  the inline-formatting unwrap in both `_algpseudo_inline` (#20 path)
  and `_algo_convert_body` (algorithm2e path) used `[^}]*` to capture
  the macro argument, which stopped at the first `}` — so a
  `\textbf{[NEW: $\mathcal{Q}$ is chosen]}` body broke at the `}` of
  `\mathcal{Q}` and emitted `**[NEW: $\mathcal{Q**$ is chosen]}` with
  an unbalanced math fence and an orphan `}`. Surfaced after #20
  routed algorithmic bodies through the inline-formatter for the
  first time. New `_unwrap_text_macro` walks braces with balanced-
  depth matching and is used for `\textbf`, `\textit`, `\textnormal`,
  `\emph`, and `\navy` in both body converters. Closes [#21].
- **`algorithmic` / algpseudocode env support** ([#20]): LaTeX books
  using the `algorithmic` (algorithmicx) environment for pseudocode
  had either no support at all (raw `\STATE`, `\FOR`, `\ENDFOR`
  markers leaking into `::: algorithmic` divs) or were unreachable
  via the existing `\begin{algorithm}` preprocessor (which only
  knew the algorithm2e dialect). Two new pieces:
  - **New preprocess step** (`_apply_algorithmic_markers.py`) finds
    standalone `\begin{algorithmic}…\end{algorithmic}` blocks (e.g.
    inside a custom `definitionbox` tcolorbox wrapper) and emits
    base64-encoded `<!--ALGORITHMIC body=…-->` sentinels. Runs
    AFTER the algorithm-marker preprocessor so algorithmic blocks
    already nested inside `\begin{algorithm}` (which get encoded
    by the outer wrapper) are left alone.
  - **New native parser** (`_algpseudo_convert_body`) walks the
    algpseudocode keyword set (`\STATE`, `\FOR{}…\ENDFOR`,
    `\WHILE{}…\ENDWHILE`, `\REPEAT…\UNTIL{C}`, `\IF{}…\ELSE…\ENDIF`,
    `\LOOP…\ENDLOOP`, `\FORALL{}`, `\REQUIRE`, `\ENSURE`, `\RETURN`,
    `\COMMENT{}`, `\ELSIF{}`, etc.) with a stack-based tokeniser
    and emits nested Markdown bullets. `_algo_convert_body`
    dispatches here when it sees algpseudocode keywords or a
    `\begin{algorithmic}` wrapper, so a single `\begin{algorithm}`
    block renders correctly whether the inner pseudocode is
    algorithm2e or algorithmicx.
  - **`resolve_algorithmics`** decodes standalone markers into a
    bare bullet list (no `{prf:algorithm}` wrapper — no caption or
    label was given).
  - Native parser preserves `\UNTIL{C}` conditions, `\ELSE` branches,
    and `\LOOP` — none of which translate cleanly to algorithm2e.
    Lesson [023]. Closes [#20].
- **`description` env support** ([#19]): LaTeX `description` lists
  arrived in MyST as `::: description` divs with every `\item[Term]`
  term label silently stripped — pandoc drops them at the AST level,
  so a post-pandoc transform couldn't recover them. New preprocess
  step (`_apply_description_markers.py`) rewrites
  `\begin{description}…\end{description}` blocks into
  base64-encoded HTML-comment sentinels that pandoc passes through
  verbatim; `convert_description_lists` in postprocess decodes them
  back to MyST definition-list syntax (`Term\n: body`). Same
  sentinel pattern as algorithm2e ([014]) and minted ([015]).
  Surfaced converting an external book. Lesson [022]. Closes [#19].
- **Chapter splitter missed `\chapter[short]{long}`** ([#18]): the
  ``_apply_chapter_splits`` regex only matched ``\chapter{}`` and
  ``\chapter*{}``, so a book with even one TOC-short-title chapter
  (``\chapter[Short]{Long title}``) under-counted by one and the
  splitter errored out (``has only N-1 \chapter block(s) but config
  requires N``). Pattern now also matches the optional-argument form,
  covering all four LaTeX variants
  (with/without ``*``, with/without ``[short]``). Surfaced while
  converting an external book outside the QuantEcon org. Closes [#18].
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
[#18]: https://github.com/QuantEcon/claude-latex-to-myst/issues/18
[#19]: https://github.com/QuantEcon/claude-latex-to-myst/issues/19
[#20]: https://github.com/QuantEcon/claude-latex-to-myst/issues/20
[#21]: https://github.com/QuantEcon/claude-latex-to-myst/issues/21
[#22]: https://github.com/QuantEcon/claude-latex-to-myst/issues/22
[#23]: https://github.com/QuantEcon/claude-latex-to-myst/issues/23
[#24]: https://github.com/QuantEcon/claude-latex-to-myst/issues/24
[#25]: https://github.com/QuantEcon/claude-latex-to-myst/issues/25
[#26]: https://github.com/QuantEcon/claude-latex-to-myst/issues/26
[#27]: https://github.com/QuantEcon/claude-latex-to-myst/issues/27
[#28]: https://github.com/QuantEcon/claude-latex-to-myst/issues/28
[#29]: https://github.com/QuantEcon/claude-latex-to-myst/issues/29
[#30]: https://github.com/QuantEcon/claude-latex-to-myst/issues/30
[#31]: https://github.com/QuantEcon/claude-latex-to-myst/issues/31
[#32]: https://github.com/QuantEcon/claude-latex-to-myst/issues/32
[#33]: https://github.com/QuantEcon/claude-latex-to-myst/issues/33
[#35]: https://github.com/QuantEcon/claude-latex-to-myst/issues/35
[#36]: https://github.com/QuantEcon/claude-latex-to-myst/issues/36
[#37]: https://github.com/QuantEcon/claude-latex-to-myst/issues/37
[023]: lessons/023-algpseudocode-native-parser.md
[014]: lessons/014-algorithm2e-resolution.md
[015]: lessons/015-minted-listings-resolution.md
[021]: lessons/021-unlabeled-subfigures-silent-image-drop.md
[022]: lessons/022-description-item-labels-silently-dropped.md
[024]: lessons/024-orphan-label-dotall-regex-spans-paragraphs.md
[025]: lessons/025-multiline-table-forward-scan-needs-fenced-div-bound.md
[026]: lessons/026-pandoc-img-vs-embed-for-includegraphics.md
[027]: lessons/027-pandoc-empty-html-comment-separator-artifact.md
[028]: lessons/028-preamble-text-macros-pandoc-silently-drops.md
[029]: lessons/029-nested-list-item-markers-consumed-by-description-preprocess.md
[030]: lessons/030-inline-itemsep-on-list-opener-cascades-pandoc.md
[031]: lessons/031-textual-citation-regex-truncates-at-colon.md
[032]: lessons/032-per-row-align-labels-lost-as-anchors.md
[033]: lessons/033-pandoc-pre-resolves-ref-inside-caption-to-wrong-number.md
[034]: lessons/034-pandoc-attr-fenced-code-blocks-need-myst-directive-conversion.md
[035]: lessons/035-citation-regex-trailing-colon-swallowed-into-key.md
[036]: lessons/036-attr-fence-regex-chokes-on-braces-in-caption-values.md
[037]: lessons/037-multline-gather-label-extraction-incomplete.md

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
