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

### Fixed — "Table Table N" doubled-noun refs (#131)

`strip_doubled_noun_refs` now ships `Table`/`Tables` defaults for the
`tab-` and `tbl-` label prefixes (mirroring the Figure `f-`/`fig-` pair),
so prose like `Table~\ref{tab:…}` no longer renders as "Table Table N".
Previously this required a per-book `doubled_noun_refs:` config entry
(62 sites in the Deep-Learning book).

### Added — render-gate build smoke test (lesson 046)

Five PR #103-series bugs were invisible to every structural gate and only
surfaced in a real `myst build` (lesson 046: *structural parity is not render
parity*). New `scripts/build_smoke.py` overlays a fixture's `regen/*.md` onto
a temp copy of its worked-on `mystmd/`, builds, normalizes the `⚠️`/`⛔`
lines, and diffs against a committed per-book baseline
(`tests/baselines/build-<book>.txt`; dp1's is **empty** — zero warnings is
the pinned contract). Wired into the harness as opt-in **signal (D)**:
`validate_fixture.sh <book> --build`. Skips cleanly when `myst` is absent.

### Fixed — blockify tail re-scan + `{math}`-aware counting (parity-run findings)

Found by the post-merge dp1/dp2/DL parity run over #114–#120:

- **`_blockify_math_directives` re-scans closer tails** (#113 follow-up). Two
  starred displays with prose between, glued onto one pandoc line
  (`--wrap=none` + LaTeX `%` continuation), left the second block's opening
  fence mid-line — broken MyST (3 instances in dp1 ch_intro, 4 in appB). The
  tail after a closing fence is now re-scanned for the next opener.
- **`validate.py` counts `{math}` directives as equations.** Starred envs no
  longer emit `$$` pairs, so the count gate read every one as a drop.
- **Baselines refreshed**: 6 entries improved toward parity (dp1 ch_fps
  equations/figures now exact; dp2 ch_approx_learning + ch_math_foundations
  exact, ch_transforms −2→−1; DL ch06 +2 cross-refs = the two ch06
  algorithm-box `\eqref`s from #106 now converting).

### Fixed — algorithm2e rendering + inline-macro leaks (book-dp1 audit, #109 / #106)

- **Uncaptioned algorithm2e floats render unnumbered** (#109). algorithm2e
  numbers only captioned floats; the converter auto-labelled every block, so
  the two uncaptioned blocks in dp1 ch_intro took numbers and pushed the one
  real algorithm from 1.1 to 1.3. The marker now carries a `numbered` flag and
  `resolve_algorithms` emits `:nonumber:` for uncaptioned blocks and stops
  minting an *auto*-label for them (an explicit `\label{}`, if the author wrote
  one, is still preserved as a target).
- **Loops emit `do … end`** (#109). `\While{C}{B}` / `\For{…}{…}` (both the
  algorithm2e braced form and the algpseudocode `\WHILE…\ENDWHILE` form) now
  render `while C do … end` instead of `while C:` with no terminator.
- **Soft-wrapped steps stay one bullet** (#109). A single `\;`-terminated step
  split across source lines was emitted as two bullets; the line-join now keeps
  it one, while `\KwIn`/`\KwOut`/`\Return` (no `\;`) stay separate.
- **`\tcp{…}` comments converted** (#109) to `(-- …)` instead of leaking; stray
  `%` line-comments dropped.
- **Inline `\eqref` / `\texttt` no longer leak** inside algorithm bodies (#106).
  The body is base64'd pre-pandoc so it never reached the prose cross-ref/code
  passes — both dialects now convert `\eqref{eq:x}` → `` {eq}`eq-x` `` and
  `\texttt{x}` → `` `x` `` in-place.

  *Known limitation:* algorithm lines render as a bullet list, not the PDF's
  continuous line numbers (#109 item 3) — MyST nested ordered lists restart
  numbering per level, so cross-level line numbering isn't expressible; left as
  a rendering gap.

### Fixed — starred display equations stay unnumbered (book-dp1 audit, #113)

Starred LaTeX envs (`equation*` / `align*` / `gather*` / `multline*`) are
unnumbered, but the converter emitted a bare `$$…$$` which mystmd **numbers**
under book-wide numbering (`numbering: book: true`) — confirmed against myst
v1.9.1: a label-less `$$` is assigned an `enumerator`. In book-dp1 ch_intro
this turned the final equation number from the PDF's (1.34) into (1.61).
`convert_equations` now emits starred envs as a `{math}` directive with
`:enumerated: false` (no number, no counter advance); non-starred `equation`
keeps the bare `$$` form (numbered, matching LaTeX). A block-separation pass
hoists the directive onto its own block when pandoc's `--wrap=none` abuts it
to surrounding prose. **Output change**: every starred display equation across
consuming books re-emits as a `{math}` directive — re-pin fixture snapshots
after a reviewed diff.

### Fixed — theorem/proof optional `[title]` (book-dp1 audit, #112)

Pandoc **drops** the optional argument of a `\begin{theorem}[Title]` it can't
resolve (no matching `\newtheorem`), and renders `\begin{proof}[Proof of …]`
*inline* — which then duplicates sphinx-proof's auto heading. New pre-pandoc
pass `_apply_prf_title_markers.py` moves the optional title into a
`<!--PRFTITLE-START-->…<!--PRFTITLE-END-->` marker (the title text between the
delimiters is still pandoc-converted, so `\ref`/math in a title survive);
`transforms.envs.convert_environment_divs` lifts it onto the `{prf:*}`
directive argument. Removing the `[...]` also stops the proof title rendering
inline, so the heading is no longer doubled.

### Fixed — multicols count leak; tabular-cell refs confirmed (book-dp1 audit, #111 / #107 gap 2)

- **`multicols` column count no longer leaks** (#111). `\begin{multicols}{2}`
  had pandoc render the mandatory `{2}` argument as a stray `2` paragraph at
  the top of the (column-less) MyST output. The count is stripped pre-pandoc
  (`multicols` is already skipped post-pandoc); MyST has no multi-column
  primitive so the count carries no downstream meaning.
- **Cross-refs inside `tabular` cells convert correctly** (#107 gap 2) — both
  the `\begin{table}` marker path and a bare `tabular` emit `{ref}` /
  `{prf:ref}` roles for `\ref` / `\S\ref` in cells. Verified already-correct
  against the current pipeline and locked with a regression golden.

  *Not addressed (MyST/CommonMark limitations, tier-3 candidates):* custom
  `\item[(a)]` enumerate labels (pandoc drops the optional label; MyST has no
  custom ordered-list marker) and the `enumitem` `\setlist[…]{label=(\roman*)}`
  roman style (CommonMark ordered lists can't carry roman markers). #111 stays
  open for these.

### Fixed — legacy font declarations + `\texttt{{@}…}` (book-dp1 audit, #107 / #105)

Two pre-pandoc normalisations in `_apply_rewrites.py`:
- **Legacy declaration font forms** `{\sc …}` / `{\sf …}` (and `{\bf}` / `{\it}`
  / `{\tt}`) → `\textsc{…}` etc. (#107 gap 1). Pandoc handles the command form
  natively but silently drops the formatting from the declaration form, so
  `{\sc iid}` emerged as lowercase `iid`. Balanced-brace rewrite preserves
  nested markup.
- **`\texttt{{@}foo}` → `\texttt{@foo}`** (#105). The `{@}` brace group (an
  author idiom to stop `@` reading as a citation key) made pandoc emit two
  adjacent code spans (`` `@``foo` ``). Flattens non-command grouping braces
  inside a `\texttt` argument; a real command argument (`\textbf{keep}`) is
  left intact.

### Fixed — extensionless `\includegraphics` resolves to the copied raster (#104)

`\includegraphics{fig/foo}` with **no extension** (valid LaTeX — graphicx
probes extensions) emitted an unresolvable `{figure} fig/foo` even though the
copy step wrote `figures/foo.png`. `ConversionContext.from_config` now scans
the source `figures_dir` into a stem→filename map (`figure_ext_map`, prefers
web-renderable formats, pdf last); the new `_helpers.complete_image_path`
completes an extensionless include to `figures/foo.png`. Paths that already
carry an extension, or have no matching source file, are untouched.

### Fixed — cross-reference parity (book-dp1 audit, #108 / #110)

- **Multiple consecutive `\label{}` on a heading no longer orphans the
  secondary labels** (#108). `\subsection{T}\label{ss:a}\label{sss:b}` had
  pandoc fold only the first label into the heading id and emit the rest as a
  leading span on the next paragraph, which the strip path dropped — a
  `{ref}` to the orphan resolved to a paragraph node and rendered
  "Paragraph". New `hoist_consecutive_heading_labels` transform stacks every
  label as a `(name)=` anchor above the heading so all resolve to the section
  number.
- **Doubled noun stripped for `{numref}`-routed figure refs and `\S\ref`
  appendix refs** (#110). `Figure~\ref{f:x}` rendered "Figure Figure N" (the
  prose noun plus the `{numref}` auto-noun); `Appendix~\S\ref{c:areal}`
  rendered "Appendix §Appendix A". `strip_doubled_noun_refs` now covers
  Figure/Figures (`f-`/`fig-`) and Appendix/Appendices (`c-`), and swallows
  an optional intervening `§`.

### Changed — Phase 6: Deep-Learning parity pass — tikz figure-caption math (architecture evolution 6/6)

Exercises the new architecture on the book furthest from parity, to prove it
generalizes across all three books. Intentionally changes DL output (snapshot
re-pinned after a reviewed equal-or-better diff); dp1/dp2 byte-identical.

- **Figure-caption math preserved for `tikzpicture` figures** (lesson 045).
  DL's 78 inline-tikz figures bail the marker path (so the `TIKZ_FIGURE_MAP`
  SVG applies), which sent the caption through pandoc's HTML figcaption —
  flattening `$\theta_0$` → unicode `θ0`. Now the float is marker-ized
  *caption-only*: the `\begin{tikzpicture}…\end{tikzpicture}` region is
  stripped first (no node-text scoop — #98 #3 holds), the caption + label +
  legitimate `{\footnotesize}` sub-panel captions are extracted and
  batch-converted (math intact), and `_emit_figure` resolves the SVG via the
  override path. Locked by `golden_tex/tikz_figure_caption_math`.
- **Result:** DL parity diff vs the worked-on baseline fell **166 → 20 lines**
  (7 of 12 chapters now byte-identical). Remaining lines are documented drift
  (`:width:` additions that are *more* source-faithful; tikz node-text labels
  that belong in the SVG).
- **`validate.py` is now marker-aware** (`count_latex` counts `<!--FIGURE-->`
  markers — decoded for subfigure panels — and `[[CITE…]]` natbib markers).
  The apparent DL citation (`61/130`) / figure (`10/11`) "gaps" were
  *measurement artifacts*: for `preprocess.split` books validate reads the
  preprocessed tmp file where those constructs are already markers. After the
  fix appA_glossary citations go `1/20 → 20/20`, ch02 figures `10/11 → 11/11`,
  ch01 citations `61 → 111` (residual = multi-key `\citet{a,b}` → 2 roles,
  inherent). dp1/dp2 read pristine source (no markers) → counts unchanged.
  See `notes/design/phase-6-dl-parity.md`.

### Added — Phase 5: book-side project_overrides + graduation rule (architecture evolution 5/5)

Behavior-preserving (snapshot byte-identical ×3) — gives book-specific
*programmatic* edge cases a home that is neither a re-run-fragile hand-edit
nor over-specialization in `postprocess.py`.

- **`load_overrides` reads a closed `project_overrides.py` surface** into the
  `ConversionContext`: `TIKZ_FIGURE_MAP` / `TIKZCD_INLINE_MAP` (as before),
  `EXTRA_REWRITES` (`[(pattern, repl) | (pattern, repl, stems), …]`, compiled
  and appended to `ctx.postprocess_rewrites`), and one optional
  `POST_CONVERT(text, stem, ctx)` hook (held on `ctx.post_convert`, run once
  at a single documented point at the end of `process_text`). Reads present
  attributes, ignores the rest — **not** a plugin framework (no registration,
  no ordering, one named hook).
- **`project_overrides:` config key** (preferred); `tikz_overrides:` retained
  as an alias for one release (same filename-agnostic loader).
- Overrides **contribute** to the context; they never mutate module globals
  (the Phase-3 invariant). `POST_CONVERT` must be fence-aware/conservative —
  golden case `post_convert_fence_aware` + `tests/test_project_overrides.py`
  prove it runs and leaves a fenced code block untouched.
- Graduation rule (one book → override; second book → pipeline + lesson +
  golden case) already documented in CLAUDE.md.

### Changed — Phase 4: surface reduction + subfigure markers + decision records (architecture evolution 4/5)

The one phase that intentionally changes output (snapshot re-pinned after a
reviewed, equal-or-better diff via the §1b differential gate).

- **#94 subfigure markers** — a `\begin{figure}` whose every
  `\begin{subfigure}` panel is a plain `\includegraphics` is now marker-ized
  (one `{figure}` per panel; outer label → first panel, `-b`/`-c` suffix for
  later unlabelled panels). Panels that aren't plain `\includegraphics`
  (e.g. dp1's `\scalebox{\input{…pdf_t}}`) bail to the HTML path
  (conservatism). An outer-label `TIKZ_FIGURE_MAP` override still wins
  (composite-image case, dp1 `f-du` → `du.svg`) — the check moved
  post-pandoc into `_emit_figure`, where the map is visible. Fidelity win:
  panel-caption math (`$\alpha=0.7$`) is preserved, vs the old fallback
  flattening it to unicode. Locked by `golden_tex/subfigure_includegraphics`.
- **No custom AST decision record** + **HTML-fallback reassessment** in
  CLAUDE.md: `convert_html_figures` is *retained* (not removed) because the
  `\begin{tikzpicture}` (#98 #3) and scalebox/input-subfigure bails route
  through it for the post-pandoc override. Revised goal: one path per
  *fully-modelled* construct, fallback kept for the bail set.
- **Lessons re-tagged** quirk-vs-permanent (LESSONS.md "By axis").

### Changed — Phase 3: ConversionContext state threading (architecture evolution 3/5)

Behavior-preserving (snapshot byte-identical ×3) removal of the module-level
mutable globals that made the post-pandoc pipeline non-reentrant and were the
root cause of lesson 038.

- **`scripts/conversion_context.py`** — `ConversionContext` (config-derived
  run state) + `FileCounters` (per-file exercise numbering) + `from_config`
  (the pure-constructor successor to the old `apply_config` parsing) +
  `default` + a `current_context()` / `set_current_context()` registry.
- **`postprocess.apply_config`** is now a thin wrapper: validate → build ctx
  → register → return it. `process_text(…, ctx=…)` threads the context; the
  six stateful transform families (typography, refs, code, frontmatter,
  envs, figures/figures_from_latex) read `ctx` instead of `import
  postprocess`. `math`/`cite` stayed pure.
- **Module globals + the lesson-038 `sys.modules` alias are gone.** A
  backward-compat module proxy at the bottom of `postprocess.py` forwards the
  legacy `postprocess.ENV_MAP` / `TIKZ_FIGURE_MAP` / … names to the current
  context (test-compat shim) so the ~600 unit tests were untouched.
- **Reentrant:** `tests/test_conversion_context.py` converts two books (two
  contexts) in one process with no bleed and proves per-file counters reset.
  Lesson 038 marked `superseded`.

### Changed — Phase 2: marker shared base + hybrid boundary (architecture evolution 2/5)

Pure refactor (snapshot byte-identical ×3) consolidating the duplicated
marker scaffolding the figure and table preprocessors re-implemented.

- **`scripts/transforms/_markers.py`** — the shared base, once:
  `pandoc_batch_convert` (the single `<!--CELL_N-->`-sentinel batch pandoc
  call, with an optional `paren_guard` for figure sub-captions and the
  `` `<!-- -->`{=html} `` adjacency scrub), `encode_payload`/`decode_payload`
  (the base64+JSON marker codec), and `reassemble` (blank-line-wrapped,
  source-order stream rebuild). **Plain functions, no `MarkerPlugin` class.**
- `_apply_figure_markers.py` and `_apply_table_markers.py` now import the
  base; `figures_from_latex`/`tables_from_latex` `encode_marker`/`decode_marker`
  delegate to the shared codec.
- **Bail-predicate audit** documented at the top of `_markers.py`
  (figure: subfigure / raw tikzpicture / multi-image; table: longtable
  routing + fall-through). Default stance: bail unless fully modelled.
- **CLAUDE.md** now states the pandoc/marker boundary explicitly (a
  "Settled architectural decisions" entry) so it stops moving by accretion;
  retiring the HTML fallbacks is the Phase-4 payoff.

### Added — Phase 1: validation gate + CI (architecture evolution 1/5)

The keystone safety net for the architecture-evolution work. A `.tex`-rooted
gate that would have caught #96 and the four #98 regressions pre-merge.

- **CI workflow** (`.github/workflows/test.yml`) — runs on every push *and*
  PR (push coverage guards the phase commits before the single end-PR
  exists), pins pandoc to the exact local version, runs the full suite
  (unit + `tests/golden` + `tests/golden_tex` + the §1b differential gate).
  A second, label-gated, non-blocking job (`fixture-check`) clones the
  consumer books and diffs `validate.py` counts against committed baselines.
- **`tests/golden_tex/` seeded from the lesson catalogue** — 16 new
  `.tex → .md` reproducers covering the codified pandoc-quirk lessons
  (tables/figures/citations/refs/math/algorithms/listings); coverage map in
  `tests/golden_tex/LESSON_COVERAGE.md`, locked by `test_golden_tex_seeded`.
- **§1b differential migration gate** (`tests/test_marker_differential.py`)
  — runs *both* the fallback (HTML) and marker paths over a corpus of real
  figure blocks and asserts the marker path is equal-or-better (feature-based,
  not byte-based). The scaffold Phase 4 uses to prove the subfigure migration
  before retiring the fallback. (Lesson 044.)
- **Per-book count baseline** (`scripts/count_baseline.py`,
  `tests/baselines/*.json`) — reuses `validate.py`'s counting primitives to
  emit/check a tiny committed JSON of per-chapter counts + resolution totals
  per fixture; catches whole-book *drops* the byte-diff tiers don't.

### Fixed — figure-marker parser completeness ([#98])

A regen of all three consumer books against the figure-marker work
(#95/#97) surfaced four shipped regressions — none visible to `validate.py`
counts (a figure still counts as a figure), all caught only by diffing the
regenerated `.md` against the committed baselines. Each is now fixed in the
pipeline and locked by a `tests/golden_tex/` case:

- **`:width:` restored** — `FigureSpec` gains a `width` field;
  `_convert_includegraphics_width` reproduces pandoc's conversion
  (`0.95\textwidth` → `95%`, bare `\textwidth` → `100%`). 31 figures in dp2.
- **Leading-space captions fixed** — `parse_figure_block` strips a `\label{}`
  embedded in `\caption{\label{} …}` (the label is already captured as
  `:name:`), so pandoc no longer emits a `[]{#…}` span + stray leading space.
  66 captions in dp2.
- **Raw `\begin{tikzpicture}` figures bail to the post-pandoc path** — a
  syntactic bail (mirroring the `subfigure` bail) so `resolve_tikz_figures`
  can apply the consumer's `TIKZ_FIGURE_MAP` SVG. Stops `{\footnotesize}`
  tikz node labels leaking as sub-captions (dp2 `f-coase_*`) and restores
  78/88 inline-tikz figures in `book-dp-deep-learning` (the #96 class).
- **Image no longer dropped when the path is on the next line** —
  `_INCLUDEGRAPHICS_RE` allows `\s*` between `[opts]` and `{path}`
  (dp1 `f-finite_lq_1`, wrapped in `\scalebox`).
- **`decode_natbib_markers` tolerates unescaped brackets** — the tikz bail
  re-routed `\citep`-bearing captions through pandoc's HTML emission, which
  leaves `[[CITEP:X]]` unescaped (vs the marker path's `\[\[…\]\]`); the
  decoder now matches both, re-closing #92 for the bailed path.

### Added — testing infrastructure

- **`.tex`-rooted golden tier** (`tests/golden_tex/`, Phase-1 down payment):
  a harness that runs the whole pipeline (preprocess marker scripts → pandoc
  → `process_text`) against a hand-authored `input.tex` and byte-diffs the
  committed `expected.md`. Seeded with the four #98 reproducers — the gate
  that would have caught them pre-merge. See lesson 044 and
  `notes/design/phase-1-validation-gate.md`.
- **`deep-learning` target in `scripts/setup_fixtures.sh`** + a `regen/`
  config for the DL fixture (separate `output_dir`, reuses the rendered
  `tikz_overrides.py` map) so it follows the dp1/dp2 regen pattern.

### Added — pipeline transforms

- **Directive fences widen to outrank nested code blocks** ([#79]):
  a shared `transforms/_helpers.outer_fence` helper sizes a directive's
  backtick fence to one tick longer than the deepest code fence in its
  body (min three), so a ```` ```python ```` block inside an exercise,
  solution, proof, or algorithm no longer closes the directive early
  (the CommonMark same-character nesting rule, lesson 040). Applied to
  `convert_environment_divs` (`{exercise}`/`{solution}`/`{prf:*}`) and
  `{prf:algorithm}`, alongside the `resolve_exercise_markers` use shipped
  with [#69]. Pragmatic scope: only fences already present when the
  directive is emitted are counted; a figure/listing/algorithm injected
  into a directive body by a *later* pipeline stage is not yet handled
  (tracked as future work).
- **`\item\label{ex:...}` enumerate → `{exercise}` directive marker
  pipeline** ([#69]): exercise labels written as
  ``\begin{enumerate}\item\label{ex:chN:M} ...\end{enumerate}`` (the
  dominant textbook convention) were silently dropped by pandoc —
  ``\label{}`` has no place in pandoc's enumerate AST, so any later
  ``{prf:ref}`ex-chN-M`` (typically a solutions-appendix back-link)
  dangled. Surfaced in book-dp-deep-learning's R7 pass: 87 exercise
  labels in source, 96 unresolved ``{prf:ref}`` in the build log.
  New ``scripts/_apply_enumerate_markers.py`` (wired into Stage 1 of
  ``preprocess.sh`` after ``_apply_description_markers.py``)
  rewrites fully-``ex:``-labelled enumerates into pairs of
  ``<!--EXERCISE-START label=ex-X-->`` / ``<!--EXERCISE-END-->``
  markers and dissolves the list wrapper. Post-pandoc,
  ``resolve_exercise_markers`` (new, in ``transforms/envs.py``)
  decodes each pair into a ``{exercise}`` directive with
  ``:label: ex-X`` — semantically aligned with the project's
  existing ``\begin{Exercise}`` env handling so ``ex-`` cross-refs
  route through the same ``prf:ref`` path. Conservative trigger:
  only enumerates where every ``\item`` carries an ``ex:``-prefixed
  ``\label{}`` are rewritten; mixed and non-exercise lists fall
  through to pandoc unchanged. Item splitting and block pairing are
  depth-aware: a multi-part exercise whose statement nests an
  ``itemize`` / ``enumerate`` (its sub-``\item`` are unlabelled and a
  nested ``enumerate``'s ``\end`` would otherwise close the outer block
  early) is still rewritten, with the nested list carried intact inside
  the parent exercise body. The emitted directive fence widens to
  outrank any code fence in the exercise body (a nested ```` ```python ````
  block yields a four-backtick ``````` ````{exercise} ``````` wrapper),
  matching the lecture-source convention so the inner fence can't close
  the directive early.
- **`\begin{longtable}` extraction in the marker preprocessor**
  ([#54], follow-on to [#51] / [#55]): multi-page tables from the
  ``longtable`` package now run through the same structural-extraction
  path as ``\begin{table}`` floats. Differences from the regular
  ``\begin{table}`` case: ``longtable`` is its OWN float container
  (caption + label sit inside the env, typically on the first row
  before ``\\``), the colspec is the sole arg (no width spec like
  ``tabularx``), and PDF-pagination directives
  (``\endfirsthead`` / ``\endhead`` / ``\endfoot`` /
  ``\endlastfoot``) delimit repeated continuation-page header /
  footer rows. MyST renders a longtable as a single block, so the
  pagination boilerplate is stripped — only the pre-``\endfirsthead``
  header and the post-``\endlastfoot`` body survive. Simpler shapes
  (no pagination markers) fall back to the same first-section-is-header
  rule convention used for regular tabulars. Closes [#54].
- **Unified tabular extraction via marker preprocessor** ([#55],
  follow-up to [#51]): ``_apply_table_markers.py`` now extracts EVERY
  ``\\begin{tabular}`` variant in source ``.tex`` — not just those
  inside ``\\begin{table}`` floats. Three shapes are now discovered:
  (a) ``\\begin{table}`` floats (existing); (b) ``\\begin{center}``
  blocks containing a tabular (the common-symbols-style notation-list
  and ch06_ha_youngs histogram shapes); (c) bare ``\\begin{tabular}``
  not inside any wrapper. Tabular-family variants
  ``\\begin{tabular*}`` / ``\\begin{tabularx}`` / ``\\begin{tabulary}``
  are recognised — parser handles their 2-arg signature
  ``{width}{colspec}``. ``\\begin{tabu}`` is intentionally NOT in
  the recognised set because its syntax is too variable
  (``\\begin{tabu}{cols}``, ``\\begin{tabu} to <len> {cols}``,
  ``\\begin{tabu} spread <len> {cols}`` — the ``to``/``spread``
  prefix can't be skipped via balanced-brace extraction). Tabu
  blocks fall through to the pandoc-output path; add a dedicated
  handler if a consumer needs it. Tabulars whose ancestor stack
  contains a math env (``equation``, ``align``, ``array``, ...),
  Beamer slide env (``frame``, ``columns``, ``block``), TikZ
  diagram (``tikzpicture``), figure-family env (``figure``,
  ``subfigure``, ``minipage``), or custom box env are SKIPPED via
  ``_has_skip_ancestor`` — content remains as raw LaTeX for pandoc
  to handle. ``convert_simple_tables`` is now a safety-net fallback;
  it is no longer reached by any production input across the three
  test corpora. Retirement tracked under #55's Phase 4. Closes [#55].
- **`_apply_table_markers` + `resolve_table_markers`** ([#51]): bypass
  pandoc's lossy LaTeX-tabular reader for `\begin{table}` floats.
  Pandoc's reader collapses all interior `\hline`/`\midrule`
  separators in `simple_tables` format — the LaTeX-side header row
  identity is lost before pandoc produces output. The new
  preprocessor scans the source `.tex` for `\begin{table}` blocks,
  parses the tabular structure directly (where `\hline` boundaries
  survive), batches the cell content through pandoc once per file
  for inline-LaTeX → markdown conversion, and replaces the block
  with a base64-encoded HTML-comment marker. The post-pandoc
  `resolve_table_markers` decodes the markers and emits MyST
  `{table}` directives with proper header/body splits. Same shape
  as the existing `_apply_listing_markers` / `_apply_algorithm_markers`
  patterns (lesson 014, 015). Closes #51 (R3 from PR #41) and the
  dp2 `{list-table}` fallback regression for captioned zero-header
  tables. `convert_simple_tables` continues to handle
  `\begin{center}\begin{tabular}` shapes (no float wrapper) via
  pandoc's output.
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
- **`convert_simple_tables`** ([d6dcbe7], extended in [#34]): pandoc
  `simple_tables` and `multiline_tables` of any column count (2+)
  become MyST `{list-table}` directives. Captions migrate to the
  directive's `:caption:` option. An interior dash-rule with the same
  column count as the opener is treated as a header/body separator
  and emits `:header-rows: 1`. Closes FIX Issue 1 / lesson 019 and
  [#34].
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

- **Package-imported text macros detected by `_warn_dropped_text_macros`**
  ([#50], extends [#22]): the dropped-text-macro warner now flags
  ``\ding{N}`` (from ``pifont``), ``\faIcon{X}`` (from ``fontawesome``),
  ``\checkmark`` (from ``amssymb``) and similar package-imported text
  macros pandoc silently drops along with their argument. Detection is
  by-name against a curated registry; for ``\ding`` known glyph numbers
  (51, 52, 55, 56, 108, 109) come with suggested unicode replacements
  (``✓``, ``✔``, ``✗``, ``✘``, …) so the warning's paste-ready
  ``preprocess.rewrites`` block needs no editing. Unknown ``\ding``
  numbers or ``\faIcon`` icons are listed for manual fill-in. Same UX
  contract as #22 — one warning per book run, opt-in by design. New
  entries can be added to ``_PACKAGE_DROP_REGISTRY`` as books surface
  them. Surfaced converting book-dp2's ``ch_adps.tex`` where 10×
  ``\ding{51}`` in a captioned 4-column convergence table were silently
  emptied by pandoc.
- **`regen: false`** ([#63]) on `chapters[]` / `extra_files[]` entries.
  Opts a stem out of the regen flow entirely — `convert.sh` skips
  pre-process + pandoc + postprocess and leaves any curated copy in
  `output_dir` untouched. Closes the audit gap where the previous
  workaround was to silently drop the stem from `extra_files:` (which
  works mechanically but hides intent — a future maintainer has no
  signal that `common_symbols.md` is part of the book and was
  deliberately curated outside the regen flow). The stem is logged
  once in the convert banner and once in the Stage 1 preprocess
  output. Passing the stem on the convert.sh CLI bypasses the gate
  for stages 2+ (the escape hatch for an occasional force-regen).
  Validation still folds the file's anchors into the cross-reference
  pool but skips per-chapter LaTeX↔MyST counts for it (curated and
  source diverge by design). Surfaced by book-dp1's `common_symbols`
  re-curation (book-dp1#347 + commit d5e3254).
- **`cross_ref_routing:`** (P1b) extends `make_ref`'s label-prefix →
  MyST role mapping. Books that use `lst:` instead of `list:` for
  listings (or similar idiosyncratic conventions) no longer need to
  fork `postprocess.py`. String form expands to both colon- and
  hyphen-bearing variants; list form passes through verbatim.
- **`doubled_noun_refs:`** (P1b) extends `_DOUBLED_NOUN_REFS` for
  books with custom theorem-class nouns (`Claim`, `Conjecture`,
  `Fact`, etc.). Defaults still apply.
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
- **Cross-reference resolution check** (P1a): the project-wide pool
  of declared anchors is matched against every `{ref|eq|numref|
  prf:ref}` directive; declared bib keys are matched against every
  `{cite*}` directive. Catches the regression class of #30, #31,
  #33, #35, #37 — name-mismatches where counts pass but the
  rendered output silently breaks. Opt out with
  `validate.cross_ref_resolution: false`.
- **Directive-type compatibility check** (P1a-prime, prompted by
  [#38]): for every resolved cross-reference, the role must match
  the routing-role for the target label's prefix. ``{ref}`eq-foo``
  flagged as needing ``{eq}``; ``{ref}`alg-young`` flagged as
  needing ``{prf:ref}``; etc. Opt out with
  `validate.cross_ref_type_compatibility: false`. ``main()`` calls
  ``apply_config`` up-front so per-book ``cross_ref_routing:``
  overrides apply.
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
- **`GETTING-STARTED.md`** (PR [#58]) — a short workflow-oriented
  guide for newcomers running their first conversion in
  collaboration with Claude Code. Complements the reference-style
  README: covers the collaboration model (who does what), a first-
  conversion walkthrough, the iterative loop, when to capture a
  lesson vs. codify it, and the worktree pattern for parallel work.
  Linked from the top of the README so it's the obvious entry
  point for new readers.

### Added — tooling

- **`uv` as the project manager** ([e73d8a4]) — pins Python via
  `.python-version`, manages deps via `pyproject.toml` + `uv.lock`.
  No PEP 668 dance, no system Python required. Lesson 010.
- **`scripts/setup_fixtures.sh`** ([066807e]) — bootstraps local
  copies of sibling book repos under `fixtures/` (gitignored) so
  parity tests never touch in-progress branches in `../book-dp1` /
  `../book-dp2`.
- **`scripts/test.sh`** ([cc17444]) — runs the pytest suite. 96
  tests at 0.1.0; 383 after the P0–P2 quality pass.
- **`pytest-cov` coverage** (P0a) — informational baseline (~69%
  total, 70% on `postprocess.py`). No minimum enforced. Override
  with `--no-cov` for fast iteration.
- **Pipeline-order assertion test** (P0b, `tests/test_pipeline_order.py`)
  — locks the canonical `process_text` call sequence against a
  checked-in constant. Codifies lesson 008; reorders must be
  explicit.
- **Golden-file end-to-end tests** (P0c, `tests/golden/`, `tests/
  test_golden.py`) — 12 pandoc-output fixtures run through the full
  pipeline and compared byte-for-byte against checked-in expected
  output. `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py`
  re-captures the outputs for intentional behaviour changes.
- **Shape catalogue tests** (P2a) — three parametrized files cover
  every (env × shape) cell for math envs, every (cite-form × boundary
  × key-type) cell, and every (figure-shape × caption-variant) cell.
  A bug in one sibling handler now fails tests against all siblings.
  Closes the discipline gap that produced the #30 → #37 and #32 →
  #36 regression chains.

### Changed

- **`postprocess.py` split into themed transform modules** (P3a):
  the 2958-line monolith is now a 640-line orchestrator that imports
  from `scripts/transforms/{math,refs,cite,figures,code,envs,
  tables,typography,algorithms,frontmatter,_helpers}.py`. Each
  module is 100–600 lines. Public symbols are re-exported from
  `postprocess` so the import surface (`postprocess.convert_X`)
  stays stable — no test edits required. Mutable module-level state
  (`CHAPTER_TITLES`, `ENV_MAP`, `TIKZ_FIGURE_MAP`, the various
  `_EXTRA_*` config-extension lists, etc.) stays on `postprocess` as
  the single source of truth; transform modules late-import it
  inside functions when they need state.
- **Pipeline ordering** ([223bd12]): `resolve_listings` and
  `resolve_algorithms` now run AFTER `convert_citations` so inlined
  source code isn't mangled (e.g. Julia `@views` was being eaten as
  a textual cite). Lesson 015.
- **`convert_simple_tables` extended to N columns** ([#34]): tables
  with 3+ columns are now converted (previously left as raw pandoc
  dash-rule text). Adds header-row detection from interior
  dash-rules; closing-rule match requires the same column count as
  the opener so adjacent tables of different shapes can't fuse. The
  surveyed downstream impact was ~37 previously-unconverted tables
  in a single book (`Deep_Learning_for_Solving_And_Estimating_
  Dynamic_Economic_Models`). Alignment encoding from dash-rule
  widths is deliberately NOT included — `{list-table}` defaults
  cover the prose-heavy book cases. The captioned-table emit now
  wraps a markdown pipe-table inside a `{table}` directive (rather
  than nesting `{list-table}` inside `{table}`) — pipe tables aren't
  directives, so the inner table no longer consumes a phantom
  table-enumerator slot. Cross-references via `{numref}` resolve
  with sequential `Table N.1, N.2, N.3, …` enumeration rather than
  the off-by-one `N.1, N.3, N.5, …` pattern. When the source `\label`
  produces a `::: {#tab:foo}` fence, the `:name:` directive option
  is emitted on the table and the wrapping fence is suppressed — so
  `convert_environment_divs` doesn't emit a competing `(tab-foo)=`
  standalone anchor, eliminating the `duplicate label` warning that
  fired on every captioned table at build time.
  `_collect_header_above` and the forward scan now recognise
  pandoc's broad-single-group `\toprule`/`\bottomrule` shape
  (≥10-dash rules with no column separators) — these were
  previously absorbed into the header block as content, producing
  cells like `------ **Brock-Mirman**` in `\begin{table}` tables
  that lacked per-column rules. Surfaced by the Deep-Learning book's
  `tab-bm_vs_irbc` and identical no-borders shapes.

### Fixed

- **Figure-marker preprocessor restores `TIKZ_FIGURE_MAP` integration**
  ([#96], regression from [#95]): the Phase 1 marker preprocessor
  closed the four caption-content-loss bugs ([#89], [#90], [#92], [#93])
  but its `resolve_figure_markers` did NOT consult per-project
  `TIKZ_FIGURE_MAP` — so the 78 figures in book-dp-deep-learning that
  use inline `\begin{tikzpicture}` bodies + `tikz_overrides.py` lost
  their image source and emitted as text-only `{admonition} Figure`.
  Built JSON image-node count crashed from 88 → 10 in R14 fast-forward,
  forcing a revert to the prior pin. Resolution: `_emit_figure` now
  late-imports `postprocess.TIKZ_FIGURE_MAP` and looks up `spec.name`
  before falling back to admonition. When a mapping exists, emit
  `{figure} <mapped_path>` directly (with the map's `caption_override`
  if set) — preserving the legacy `convert_html_figures` →
  `resolve_tikz_figures` semantics in the new path. End-to-end
  validated against book-dp-deep-learning: image-node count back to
  88/88, all four #95-fixed issues still closed, 0 KaTeX/cite/xref
  errors. 5 new unit tests for the integration. Lesson [043] updated.
  Generalisable rule the failure exposed: when a rebuild replaces a
  transform chain, **every integration** the old chain consumed must
  be preserved, not just the bug shapes being closed.
- **Figure-marker preprocessor (Phase 1) closes the pandoc-figure-HTML
  emission bug class** ([#89], [#90], [#92], [#93]): four figure-
  caption / sub-caption content-loss bugs surfaced in DL R12–R13 — the
  empty `<span class="citation">` from `\citet` (#89), `<div
  class="minipage">` from sub-captions (#90), unescaped `[[CITEP:X]]`
  inside `<figcaption>` (#92), and bare `{\footnotesize ...}` between
  `\end{tikzpicture}` and `\caption{}` (#93). Three of those landed
  as targeted patches in `convert_html_figures` ([#91]) but the
  trajectory matched `fix_spacing_superscript` exactly: more bugs in
  the same code path within a single sprint, each a different pandoc-
  HTML-emission quirk. Resolution: mirror the table-marker pattern
  ([#51] / [#55]). `_apply_figure_markers.py` extracts `\begin{figure}`
  floats pre-pandoc into `<!--FIGURE payload=BASE64-->` HTML-comment
  markers, batch-converts the caption + sub-captions through pandoc
  once (escaping brackets so `decode_natbib_markers` finds the natbib
  markers — the key #92 fix), and stores the spec.
  `resolve_figure_markers` decodes post-pandoc into `{figure}`
  directives. Pandoc never sees the figure body, so its HTML emission
  quirks can't drop or mangle anything — the whole bug class is closed
  structurally. Phase 1 scope: single-figure shapes (one
  `\includegraphics` or `\input{tikz/...}`, no `\begin{subfigure}`);
  subfigure handling stays on `convert_html_figures` as fallback,
  tracked for Phase 2 in #94. The pre-pandoc batch defensively prefixes
  each cell with `~` (LaTeX nbsp) so pandoc doesn't mis-interpret a
  leading `(a)` as inline math `\(a\)` — a known pandoc quirk that
  bites sub-captions like `(a) the unit ball`. 21 new tests + all 570
  existing tests pass. Lesson [043] updated with the architectural
  postscript.
- **Figure captions lost `\citet` / `\citep` cites and `\begin{minipage}`
  sub-captions** ([#89], [#90]): two distinct content-loss bugs on the
  same code path in `convert_html_figures`. (1) Pandoc emits a cite
  inside a figure caption as an empty `<span class="citation"
  data-cites="X"></span>` — the key lives in the attribute, the span
  has no text content, so the generic HTML-tag strip dropped both
  span and key. Fix: convert the citation span to pandoc `@X` markdown
  *before* the tag strip; `convert_citations` later resolves to
  `{cite:t}\`X\``. Multi-cite (`data-cites="a b"`) → `[@a; @b]`. NB:
  pandoc collapses `\citet`/`\citep`/`\citep[loc]` to the same
  empty-span form so variant info is lost — only the key is
  recoverable. 8 instances in book-dp-deep-learning R12. (2) Pandoc
  preserves `\begin{minipage}` content as `<div class="minipage">`
  siblings of `<figcaption>` inside `<figure>`; the previous emit
  only extracted `<figcaption>` and discarded the rest, losing per-
  panel `(a)/(b)` labels and verification-arithmetic blocks. Fix:
  `extract_minipage_subcaptions` gathers all such divs and folds
  their text into the caption in source order ahead of the main
  figcaption. 5 instances in the same book (4 ch02 + 1 ch06). Both
  fixes share a new `_html_caption_to_myst` helper. Lesson [043].
- **`fix_spacing_superscript` rebuilt as a line-based state machine —
  closes a recurring bug class** ([#87], follow-on to [#85] / [#86]):
  the prior regex-based stash/restore architecture had been patched
  three times ([#84] / [#85] / [#86]) and still had two latent bugs.
  (1) **Phantom-fence pairing**: a content directive's closing
  `` ``` `` was matched by the plain-fence regex as a new opener and
  paired with the next bare `` ``` ``, swallowing the prose between
  two `{figure}` blocks (KaTeX errors return for that prose). (2)
  **Content-loss**: a `{code-block}` between two content directives
  was stashed first as `\x00FSS0\x00`; a subsequent phantom-fence
  region included that marker; forward-order restore exposed `FSS0`
  as literal text in the rendered output — the code listing was
  silently dropped (found in book-dp-deep-learning ch03_irbc R10, the
  Fischer–Burmeister listing). Resolution: replace the multi-pass
  regex stash with a single line-based scan that maintains a fence
  stack `[(tick_count, kind), …]`. Closers are identified by *state*
  (a bare `` ``` `` of ≥ the top's tick count pops), not by another
  regex match — so phantom pairing is structurally impossible. There
  is no stash/restore step at all, so the marker-leak content-loss
  class is also structurally impossible. Existing 559 tests pass
  unmodified; 3 new regression tests for both #87 bugs and the
  content-directive-wrapping-code case. End-to-end myst build of the
  reproducer: 0 KaTeX errors, code-block intact, no marker leak. The
  fence-stack state-machine pattern is now codified in CLAUDE.md's
  "Settled architectural decisions" as the template for any future
  fence-aware transform in this repo.
- **`fix_spacing_superscript` missed math inside `{table}` cells (and
  other base64-encoded marker bodies)** ([#85], follow-on to [#45]):
  the original transform ran early in the pipeline, before
  `resolve_table_markers` / `resolve_algorithms` / etc. decode the
  HTML-comment markers their preprocessors emit. The cell math was
  base64-hidden at that point, so the rewrite never reached it — 2 of
  the 8 originally-affected sites in book-dp-deep-learning's
  ch11_climate (inside a `{table}`) remained broken. Resolution: move
  `fix_spacing_superscript` to run **after** every marker decoder
  (right after `resolve_algorithmics`), and add a `(?!\{)` lookahead to
  the fenced-code stash so MyST directive fences (`​```{table}`, etc.)
  aren't treated as code blocks at the new late position. End-to-end
  verified against myst 1.9.1: the issue's reproducer goes from 3
  KaTeX "unknown type" errors to 0. Lesson [042] updated.
- **`\,^X` breaks KaTeX with "unknown type: 'internal'"** ([#45]): an
  inline superscript directly after a thin space — most commonly
  `3\,^\circ\mathrm{C}` (degrees Celsius), but the break is general
  (`\,^*`, `\,^\dagger`, `\,^\top`, …) — errors in KaTeX because it
  tries to superscript the `\,` spacing node itself. New
  `fix_spacing_superscript` (math.py, wired after `fix_text_dollar`)
  inserts an explicit empty base, `\,^X` → `\,{}^X`, so the superscript
  attaches to an empty group; visually identical, idempotent. The
  workaround the issue suggested (`\,\!^`) was verified to **still
  error** against myst 1.9.1 — only the empty-base group works. 8 sites
  in book-dp-deep-learning's ch11_climate. Lesson [042].
- **Captioned 0/2+-header tables drifted later `{numref}`s** ([#52]):
  a captioned table with 0 or 2+ header rows is emitted as a `{table}`
  wrapping a `{list-table}` (the caption stays a role-safe body
  paragraph). mystmd counted *both* directives as enumerable `table`
  containers, so the inner one claimed a phantom `tab-N.M` slot and
  every later table's number drifted by one (visible "Table 6.7, 6.9,
  no 6.8"). The nested `{list-table}` now carries `:enumerated: false`
  so only the outer `{table}` is numbered; a standalone (unwrapped)
  list-table still keeps its own number. Applied in both `emit_myst`
  (marker path) and `convert_simple_tables` (pandoc-output path).
  Verified against mystmd 1.9.1 by building the AST and counting
  containers. Lesson [041].
- **Plain `\cite[loc]{key}` dropped the key** ([#74], sister of [#13]):
  the locator-aware natbib rewrite covered `\citep`/`\citealp`/etc. but
  not plain `\cite`, which was deliberately left for pandoc's native
  path. That path is correct for `\cite{key}` but not
  `\cite[p.~351]{key}` — pandoc emits `[@key, p.~351]` and the
  downstream regex loses the key, rendering an empty `` {cite}`` `` role
  (silent: the validator's count tolerance hid it; only the rendered
  HTML showed the gap). Added a `\cite` rewrite **gated on the presence
  of a locator** (`_NATBIB_OPT_REQUIRED`), decoding `[[CITE:key]]` →
  `{cite}` like the no-locator path; `\cite\b` leaves
  `\citep`/`\citet` untouched and `CITE` is decoded last to avoid its
  prefix colliding with `CITEP`. One site in book-dp2. Lesson [020].
- **Per-row labels and `\tag*{}` collide in multi-row align** ([#70],
  also resolves [#46]): a ``\begin{align}`` body with 2+ per-row
  ``\label{}`` calls was previously emitted as one ``$$ \begin{aligned}
  ... \end{aligned} $$`` block with N ``(name)=`` anchors stacked above
  it. MyST collapses consecutive ``(name)=`` lines to ONE anchor and
  renames the rest, so only the first label survived — any
  ``{eq}`eq-X`` to a non-first label dangled. Same env shape with 2+
  per-row ``\tag*{}`` calls triggered KaTeX's ``Multiple \tag`` error
  because ``aligned`` accepts at most one tag. Surfaced in
  book-dp-deep-learning's R7 pass (15 collision cases across 5
  chapters with 10 dangling refs; 1 ``Multiple \tag`` site in
  ch11_climate's IAM-loss block). Resolution: ``_align_needs_split``
  triggers a per-row split when the body has 2+ labels or 2+ tags;
  ``_emit_split_align`` writes one ``$$...$$`` block per row, each
  with its own trailing label. The ``&`` column alignment is replaced
  with whitespace (cosmetic loss accepted in exchange for working
  cross-refs and KaTeX rendering); the 0/1-label case still uses
  ``aligned`` so non-colliding shapes preserve their LaTeX
  presentation. Lesson 032 updated to reflect the corrected
  trade-off — the previous "stacked anchors preserve every
  cross-ref" framing was based on incomplete understanding of MyST
  anchor semantics.
- **`convert_pandoc_attr_code_blocks` doubles backslashes in lstlisting
  captions** ([#71]): pandoc serialises ``\`` and ``"`` inside a quoted
  attribute value as ``\\`` and ``\"`` respectively. The resolver's
  ``parse_attrs`` stripped the outer quotes but didn't decode those
  escapes, so a source caption like
  ``\begin{lstlisting}[caption={$s \in (0,1)$ via \emph{sigmoid}}]``
  arrived in MyST as ``:caption: $s \\in (0,1)$ via \\emph{sigmoid}`` —
  KaTeX then rendered the doubled ``\\`` inside math mode as the
  "function with no arguments" error and the caption failed to render.
  Surfaced in book-dp-deep-learning's R7 pass (1 affected listing in
  ch02_deqns). Resolution adds a ``re.sub(r'\\(.)', r'\1', val[1:-1])``
  pass after the quote-strip, decoding pandoc's escape syntax back to
  the literal characters the caption originally carried. Two pre-existing
  tests had been masking the bug by using single-backslash inputs that
  don't match pandoc's actual output — updated to the doubled form
  pandoc emits, plus two new regression tests for the inline-math and
  embedded-quote cases.
- **`validate.py` silently no-ops on `preprocess.split:` books** ([#68]):
  the per-chapter loop resolved each stem's source ``.tex`` against
  ``source_dir`` only. Books that consolidate chapters in a monolithic
  source and use ``preprocess.split:`` to fan out per-stem ``.tex``
  files into ``tmp_dir`` failed every ``tex.exists()`` check, hit a
  silent ``continue`` for every iteration, never incremented any
  counter, and still printed "All counts match. All cross-references
  resolve and are well-typed." at the end. The contradiction with
  ``myst build`` warnings surfaced in book-dp-deep-learning's R7 pass.
  book-dp1 was equally affected via its consolidated-appendix split.
  Resolution adds a ``tmp_dir`` fallback for the source ``.tex``
  lookup (the splitter writes per-stem files there by Stage 1, so
  they're guaranteed present by Stage 6), swaps the silent
  ``continue`` for an explicit ``WARN: {stem}.tex not found in
  source_dir or tmp_dir`` on stderr, and adds a vacuous-pass guard:
  if every chapter was skipped before its counts could be checked,
  validate exits non-zero with an ``ERROR: no chapters were
  validated`` message rather than the cheery success line. Both the
  silent skip and the vacuous-pass message are regression-tested
  via subprocess end-to-end against synthetic configs.
- **`validate.py` citation counter symmetry** ([#67]): both
  `count_latex` and `count_myst` now match the full natbib /
  ``{cite:*}`` family the pipeline already round-trips. The LaTeX
  side was ``\cite[pt]?{`` — catching only ``\cite`` / ``\citet`` /
  ``\citep`` and missing ``\citealp`` / ``\citealt`` /
  ``\citeauthor`` / ``\citeyear`` / ``\citeyearpar``. The MyST side
  was ``{cite(?::t)?}`` — catching only ``{cite}`` / ``{cite:t}``
  and missing ``{cite:p}`` / ``{cite:author}`` / ``{cite:year}``.
  The two asymmetries created opposite phantom mismatches: every
  ``\citep`` under-counted on the MyST side (the symptom in #67's
  dp1 reproducer — four chapters reporting "off by one"), while
  every ``\citealp`` / ``\citealt`` over-counted on the MyST side
  (silently cancelling the ``\citep`` undercount in dp2 and DL).
  Widened to ``\cite[a-z]*{`` and ``{cite(?::[a-z]+)?}`` so each
  natbib variant is counted on both sides and the totals line up
  for any conversion the pipeline correctly performs. Cosmetic
  only — no conversion defect was hidden by the bug; just a
  noisier validation report.
- **`\begin{center}\textbf{Title}\par\begin{tabular}` orphan + list-of-lists**
  ([#59]): the bold-paragraph-as-title-surrogate shape inside a
  `\begin{center}` block (no `\begin{table}` float, no `\caption{}`)
  produced a `{list-table}` triggering `list-table directive must
  have a list of lists` at build time, plus an orphaned bold
  paragraph floating above the rendered table. Resolved together
  with [#55] — `parse_table_block` now scans the prelude before
  `\begin{tabular}` for `\textbf{X}\par\smallskip?` immediately
  followed by only whitespace + font-size commands +
  `\renewcommand` config commands. When matched (and there's no
  explicit `\caption{}`), `X` becomes a synthetic caption. The
  whole `\begin{center}` block is then substituted with a marker
  that emits a proper `{table}` directive with the title as
  caption. Last remaining case from [#47] (Mode 3). Closes [#59].
- **Nested subfigures bypassed `TIKZ_FIGURE_MAP` composite override**
  ([#49]): `\begin{figure}` blocks containing `\begin{subfigure}` shapes
  whose outer label had an entry in `TIKZ_FIGURE_MAP` (consumer-side
  composite SVG/PDF that represents multiple subfigures combined) were
  being split into per-subfigure `{figure}` directives — bypassing
  the override path entirely. Three downstream symptoms: (1)
  per-subfigure `{figure}` directives pointed at xfig-rewritten PDFs
  that didn't exist on disk; (2) the composite override was never
  consulted because `resolve_tikz_figures` only acts on admonition
  placeholders, not `{figure}` directives; (3) the outer caption was
  dropped entirely. Regression introduced by [#17]'s
  unlabeled-subfigure handling, which made subfigures emit `{figure}`
  directly. Fix: composite-override fast path in `replace_nested` —
  when `outer_label in TIKZ_FIGURE_MAP`, emit a single admonition
  with the outer label + outer caption (let `resolve_tikz_figures`
  substitute the composite). Existing per-subfigure logic is the
  fallback for the common case. Outer caption now reuses
  `extract_caption` via synthetic `<figcaption>` tags so HTML-entity
  decode and ref-routing apply uniformly. Verified end-to-end against
  book-dp1's `f-du`. Closes [#49].
- **Transform-side late-import of `postprocess` loaded a second module
  copy under script invocation, silently dropping every config
  extension and override** ([#42], P3a regression): the P3a refactor
  moved transforms into ``scripts/transforms/*.py`` modules that read
  module-level state (``TIKZ_FIGURE_MAP``, ``ENV_MAP``,
  ``CHAPTER_TITLES``, the ``_EXTRA_*`` config-extension lists,
  ``POSTPROCESS_REWRITES``, per-stem frontmatter / whitespace flags)
  via late ``import postprocess`` inside their functions. When
  ``convert.sh`` runs ``python3 postprocess.py``, Python loads the
  module under the name ``__main__`` — and ``main()``'s mutations to
  ``TIKZ_FIGURE_MAP`` etc. land in the ``__main__`` namespace. The
  late-import inside the transform then triggered a *second* load of
  the file under the name ``postprocess``, returning a fresh module
  with the defaults frozen and every override invisible. Most visible
  symptom: every consumer book using ``tikz_overrides.py`` had **0
  of N figures resolved** (88/88 broken in the Deep-Learning book —
  zero error output, just placeholder admonitions in the rendered
  HTML). Same shape silently affected ``extra_environments:``,
  ``cross_ref_routing:``, ``doubled_noun_refs:``, custom chapter
  titles, and ``postprocess.rewrites:``. Three-line fix at the top of
  ``postprocess.py``: when running as ``__main__``, alias
  ``sys.modules['postprocess']`` to the current module so every
  late-import resolves to the same instance. Existing tests are
  invisible to the bug because they ``import postprocess`` directly
  (so it loads under the name ``postprocess`` from the start); new
  ``tests/test_main_invocation.py`` shells out via ``subprocess`` to
  exercise the ``__main__`` path. Lesson [038]. Closes [#42].
- **2-col tables with header rule mangled inside `::: center`**
  ([#34], side effect of the N-col rewrite): pandoc's
  `simple_tables`-with-header shape (top rule + header row +
  separator rule + body + closing rule) was being parsed as if the
  top rule opened a 1-row table containing just the header, then
  the separator was retried as a fresh opener, producing a cascade
  of fragmented partial conversions. The N-col rewrite handles the
  three-rule shape end-to-end and peels trailing caption-shape
  blocks so a caption inside the fenced-div doesn't inflate the
  block count.
- **Algorithm `\label{}` as sibling of `\caption{}` not preserved**
  ([#39]): the algorithm preprocessor recognised
  ``\caption{\label{algo:foo} Title}`` but not the dominant LaTeX
  shape ``\caption{Title}\n\label{alg:foo}`` (sibling). Sibling
  labels fell through to an auto-generated name and every body
  ``\ref{alg:X}`` was broken (3 sites in the Deep-Learning book).
  ``_extract_caption`` now scans three positions: inside the caption,
  after it (sibling), or anywhere in the body before it. Audited
  ``_apply_algorithmic_markers.py`` — that preprocessor has no
  caption/label layer so it's unaffected.
- **Algorithm `\caption{} \label{} \begin{algorithmic} ... body`
  layout dropped the label** ([#43], [#39] follow-up): the [#39]
  fix's strict trailing-only scan early-bailed once non-whitespace
  followed the closing brace of ``\caption{}``, dropping the
  sibling label and falling back to an auto-generated name. But
  the dominant LaTeX layout is caption+label BEFORE the
  ``\begin{algorithmic}`` body (mirroring how figures/tables are
  laid out), and every algorithm in the Deep-Learning book uses
  that shape — every body ``\ref{alg:X}`` was broken. Refactored
  ``_extract_caption`` to scan ``post_caption`` first (the new
  layout), then ``pre_caption`` (the older layout from [#39]).
  Subsumes the [#39] fix while preserving every existing test
  case. Closes [#43].
- **`\label{}` inside `\begin{align*}` emitted inline anchor that
  fused with preceding prose** ([#48]): pandoc joins display-math
  blocks to the prose line above with no blank line separator. The
  anchor-form emission used by ``replace_unlabeled_align`` (and
  the extra-anchor stacks in ``replace_labeled_align`` /
  ``replace_math_block`` for ``multline``/``gather``) returned
  ``{anchors}\n{block}`` — no blank line before the anchor, so MyST
  parsed ``prose if and only if (eq-vgctp)=`` as one paragraph,
  rendered the anchor as literal text, and lost the cross-ref
  target. Wrapped every anchor emission in ``\n\n…\n\n`` so the
  anchor is always a block-level construct regardless of pandoc's
  upstream whitespace. Re-captured the ``math_align_per_row_labels``
  golden, which was previously pinning the buggy fused output.
  Closes [#48].
- **HTML entities inside caption math** ([#40]): pandoc HTML-encodes
  ``<`` / ``>`` / ``&`` inside ``<figcaption>``. Inside prose the
  browser decodes them; inside ``$...$`` KaTeX sees the entity as
  literal chars and fails to parse (``$\mu+I&gt;0$`` → KaTeX parse
  error). ``extract_caption`` now runs ``html.unescape`` on the
  whole caption — idempotent on plain text, source-readable, PDF-
  build-safe. Closes [#40].
- **Caption refs to typed targets emitted generic `{ref}`** ([#38]):
  the [#33] caption-ref converter emitted ``{ref}`` for every
  pandoc-resolved ref. MyST cannot resolve ``{ref}`` to equation
  anchors (``$$ ... $$ (eq-X)``), figure anchors, or
  ``{prf:algorithm}`` directives — those need ``{eq}`` /
  ``{numref}`` / ``{prf:ref}`` respectively. 12 broken caption refs
  in the Deep-Learning book. ``extract_caption`` now dispatches by
  label prefix via ``routing_role`` (refactored out of
  ``convert_cross_references.make_ref`` as a module-level helper
  in ``transforms/refs.py`` — single source of truth for label
  taxonomy across body and caption refs). Closes [#38].
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
[#34]: https://github.com/QuantEcon/claude-latex-to-myst/issues/34
[#35]: https://github.com/QuantEcon/claude-latex-to-myst/issues/35
[#36]: https://github.com/QuantEcon/claude-latex-to-myst/issues/36
[#37]: https://github.com/QuantEcon/claude-latex-to-myst/issues/37
[#38]: https://github.com/QuantEcon/claude-latex-to-myst/issues/38
[#39]: https://github.com/QuantEcon/claude-latex-to-myst/issues/39
[#40]: https://github.com/QuantEcon/claude-latex-to-myst/issues/40
[#42]: https://github.com/QuantEcon/claude-latex-to-myst/issues/42
[#43]: https://github.com/QuantEcon/claude-latex-to-myst/issues/43
[#45]: https://github.com/QuantEcon/claude-latex-to-myst/issues/45
[#47]: https://github.com/QuantEcon/claude-latex-to-myst/issues/47
[#48]: https://github.com/QuantEcon/claude-latex-to-myst/issues/48
[#46]: https://github.com/QuantEcon/claude-latex-to-myst/issues/46
[#49]: https://github.com/QuantEcon/claude-latex-to-myst/issues/49
[#50]: https://github.com/QuantEcon/claude-latex-to-myst/issues/50
[#51]: https://github.com/QuantEcon/claude-latex-to-myst/issues/51
[#52]: https://github.com/QuantEcon/claude-latex-to-myst/issues/52
[#54]: https://github.com/QuantEcon/claude-latex-to-myst/issues/54
[#55]: https://github.com/QuantEcon/claude-latex-to-myst/issues/55
[#58]: https://github.com/QuantEcon/claude-latex-to-myst/pull/58
[#59]: https://github.com/QuantEcon/claude-latex-to-myst/issues/59
[#60]: https://github.com/QuantEcon/claude-latex-to-myst/pull/60
[#62]: https://github.com/QuantEcon/claude-latex-to-myst/pull/62
[#63]: https://github.com/QuantEcon/claude-latex-to-myst/issues/63
[#67]: https://github.com/QuantEcon/claude-latex-to-myst/issues/67
[#68]: https://github.com/QuantEcon/claude-latex-to-myst/issues/68
[#69]: https://github.com/QuantEcon/claude-latex-to-myst/issues/69
[#70]: https://github.com/QuantEcon/claude-latex-to-myst/issues/70
[#71]: https://github.com/QuantEcon/claude-latex-to-myst/issues/71
[#74]: https://github.com/QuantEcon/claude-latex-to-myst/issues/74
[#79]: https://github.com/QuantEcon/claude-latex-to-myst/issues/79
[#85]: https://github.com/QuantEcon/claude-latex-to-myst/issues/85
[#87]: https://github.com/QuantEcon/claude-latex-to-myst/issues/87
[#89]: https://github.com/QuantEcon/claude-latex-to-myst/issues/89
[#90]: https://github.com/QuantEcon/claude-latex-to-myst/issues/90
[#91]: https://github.com/QuantEcon/claude-latex-to-myst/pull/91
[#92]: https://github.com/QuantEcon/claude-latex-to-myst/issues/92
[#93]: https://github.com/QuantEcon/claude-latex-to-myst/issues/93
[#95]: https://github.com/QuantEcon/claude-latex-to-myst/pull/95
[#96]: https://github.com/QuantEcon/claude-latex-to-myst/issues/96
[#98]: https://github.com/QuantEcon/claude-latex-to-myst/issues/98
[020]: lessons/020-natbib-bracket-markers-precede-cross-refs.md
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
[038]: lessons/038-postprocess-main-module-double-load.md
[041]: lessons/041-nested-table-directive-double-enumerates.md
[042]: lessons/042-katex-thin-space-superscript-needs-empty-base.md
[043]: lessons/043-pandoc-figure-caption-content-loss.md

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
