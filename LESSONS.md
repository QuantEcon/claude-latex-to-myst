# Lessons Index

Pitfalls learned across LaTeX → MyST conversions. See [`lessons/README.md`](lessons/README.md)
for schema and lifecycle. Add new lessons with `/capture-lesson`.

Severity legend: 🔴 high · 🟡 medium · 🟢 low

| ID  | Title | Category | Severity | Status |
|----:|-------|----------|----------|--------|
| 001 | [Blank lines inside $$ math blocks silently terminate them](lessons/001-blank-lines-in-math-blocks.md) | post-processing | 🔴 | codified |
| 002 | [Cross-ref regex consumes equation blocks via [0,1) bracket false-match](lessons/002-cross-ref-regex-eats-equations.md) | regex-safety | 🔴 | codified |
| 003 | [KaTeX cannot parse $ inside \\text{...}](lessons/003-text-dollar-katex-incompat.md) | katex | 🔴 | codified |
| 004 | [Never use id(list) to auto-generate labels](lessons/004-id-recycling-duplicate-labels.md) | post-processing | 🟡 | codified |
| 005 | [Skipping unsupported nested divs needs depth tracking](lessons/005-env-skip-depth-tracking.md) | post-processing | 🟡 | codified |
| 006 | [LaTeX % comments inside math blocks break KaTeX](lessons/006-percent-comments-in-math.md) | katex | 🟢 | codified |
| 007 | [\\cref{a,b,c} becomes a single broken pandoc link](lessons/007-cref-comma-split.md) | post-processing | 🟡 | codified |
| 008 | [Post-processing transform order is critical and fragile](lessons/008-pipeline-ordering.md) | post-processing | 🔴 | codified |
| 009 | [BSD sed and bash 3.2 break the preprocess pipeline on macOS](lessons/009-bsd-sed-mapfile-portability.md) | tooling | 🟡 | codified |
| 010 | [Don't rely on system Python — adopt uv so the pipeline manages its own interpreter](lessons/010-pep-668-system-python.md) | tooling | 🟢 | codified |
| 011 | [Strip prose noun before {prf:ref} — sphinx-proof auto-renders it](lessons/011-doubled-noun-refs.md) | post-processing | 🟡 | codified |
| 012 | [Insert blank line after closing $$ for readability](lessons/012-blank-after-display-math.md) | post-processing | 🟢 | codified |
| 013 | [MyST cannot resolve {ref}`fn-name` to footnote anchors](lessons/013-footnote-refs-unresolvable.md) | myst | 🟢 | codified |
| 014 | [algorithm2e bodies need a custom parser — pandoc destroys their structure](lessons/014-algorithm2e-resolution.md) | post-processing | 🔴 | codified |
| 015 | [Minted source listings need preprocessor + source-file inlining](lessons/015-minted-listings-resolution.md) | post-processing | 🟡 | codified |
| 016 | [§ Section: qe-v5 section labels double the prefix in §\\ref{...} prose](lessons/016-section-symbol-doubled-prefix.md) | post-processing | 🟡 | codified |
| 017 | [Pandoc class attributes leak into MyST labels — capture only the first whitespace-delimited token](lessons/017-pandoc-class-attrs-leak-into-labels.md) | regex-safety | 🔴 | codified |
| 018 | [Promoting a body anchor to chapter label needs a non-heading guard — or it steals the first section's id](lessons/018-greedy-explicit-label-promotion.md) | post-processing | 🔴 | codified |
| 019 | [Pandoc simple_tables vs multiline_tables — blank-line presence flips row-parsing logic](lessons/019-simple-vs-multiline-tables.md) | post-processing | 🔴 | codified |
| 020 | [Natbib variants pandoc can't distinguish need bracket-marker sentinels — and the decode pass must run before cross-refs](lessons/020-natbib-bracket-markers-precede-cross-refs.md) | post-processing | 🔴 | codified |
| 021 | [Unlabeled subfigures inside a labeled figure silently drop all but the first image](lessons/021-unlabeled-subfigures-silent-image-drop.md) | post-processing | 🔴 | codified |
| 022 | [Pandoc silently drops \\item[Term] labels in description envs — preprocess to sentinel markers](lessons/022-description-item-labels-silently-dropped.md) | post-processing | 🔴 | codified |
| 023 | [algpseudocode bodies need their own native parser — algorithm2e translation is lossy](lessons/023-algpseudocode-native-parser.md) | post-processing | 🟡 | codified |
| 024 | [Orphan \\label{} + DOTALL catch-all spans paragraphs and swallows figures between equations](lessons/024-orphan-label-dotall-regex-spans-paragraphs.md) | regex-safety | 🔴 | codified |
| 025 | [Multiline-table forward scan needs the ::: fenced-div boundary or it eats the next table](lessons/025-multiline-table-forward-scan-needs-fenced-div-bound.md) | post-processing | 🔴 | codified |
| 026 | [Pandoc emits `<img>` for \\includegraphics and `<embed>` for \\input{tikz/…} — both must be recognised as figure sources](lessons/026-pandoc-img-vs-embed-for-includegraphics.md) | post-processing | 🟡 | codified |
| 027 | [Pandoc's empty `<!-- -->`{=html} lexer-defeat separator survives into rendered HTML](lessons/027-pandoc-empty-html-comment-separator-artifact.md) | pandoc | 🟢 | codified |
| 028 | [Custom preamble + package-imported text macros (\\DeclareUrlCommand, \\newcommand wrapping \\textcolor, \\ding, \\faIcon) pandoc drops silently along with their argument](lessons/028-preamble-text-macros-pandoc-silently-drops.md) | preprocess | 🟡 | codified |
| 029 | [Nested \\item markers inside a description body consumed by the description preprocess — cascades into dropped figures](lessons/029-nested-list-item-markers-consumed-by-description-preprocess.md) | preprocess | 🔴 | codified |
| 030 | [Inline \\itemsep&lt;dim&gt; on a list opener cascades into 'Unknown environment' when nested](lessons/030-inline-itemsep-on-list-opener-cascades-pandoc.md) | preprocess | 🟡 | codified |
| 031 | [Textual @key citation regex truncates at the first `:` — JabRef/Mendeley keys broken](lessons/031-textual-citation-regex-truncates-at-colon.md) | regex-safety | 🟡 | codified |
| 032 | [Per-row \\label{} inside multi-row \\begin{align} lost — extract to anchors above the block](lessons/032-per-row-align-labels-lost-as-anchors.md) | post-processing | 🔴 | codified |
| 033 | [Pandoc pre-resolves \\ref{} inside \\caption{} to a chapter-unaware number — recover the label from data-reference](lessons/033-pandoc-pre-resolves-ref-inside-caption-to-wrong-number.md) | post-processing | 🟡 | codified |
| 034 | [Pandoc attribute fenced code blocks (from lstlisting) are not honoured by MyST — convert to {code-block} directives](lessons/034-pandoc-attr-fenced-code-blocks-need-myst-directive-conversion.md) | post-processing | 🟡 | codified |
| 035 | [Citation regex trailing-`:` swallowed into key after the #32 widening](lessons/035-citation-regex-trailing-colon-swallowed-into-key.md) | regex-safety | 🟡 | codified |
| 036 | [Pandoc-attr fence regex stops at the first `}` inside a quoted caption value](lessons/036-attr-fence-regex-chokes-on-braces-in-caption-values.md) | regex-safety | 🟡 | codified |
| 037 | [`\label{}` extraction not applied to `multline` / `gather` (incompleteness from #30)](lessons/037-multline-gather-label-extraction-incomplete.md) | post-processing | 🟢 | codified |
| 038 | [Late-import of `postprocess` from transform modules loads a second copy when run as `__main__`](lessons/038-postprocess-main-module-double-load.md) | tooling | 🔴 | superseded (P3) |
| 039 | [Enumerate-exercise preprocessor: flat \\item scan AND non-greedy block regex both break on nested lists inside an exercise](lessons/039-enumerate-exercise-markers-nested-list-depth-and-block-pairing.md) | preprocess | 🔴 | codified |
| 040 | [Nested fences resolve by same-character count (k+1) — directive emitters must outrank any code fence in their body](lessons/040-myst-nested-fence-count-rule.md) | myst | 🟡 | codified |
| 041 | [A {list-table} nested in a {table} double-enumerates — suppress the inner with :enumerated: false](lessons/041-nested-table-directive-double-enumerates.md) | myst | 🟡 | codified |
| 042 | [KaTeX errors on `\\,^X` (superscript right after thin space) — insert an empty base `\\,{}^X`](lessons/042-katex-thin-space-superscript-needs-empty-base.md) | katex | 🟡 | codified |
| 043 | [Pandoc figure-caption emit drops citations and minipage sub-captions — recover from HTML attributes and sibling divs](lessons/043-pandoc-figure-caption-content-loss.md) | post-processing | 🟡 | codified |
| 044 | [Migrating a construct fallback→marker re-implements a parser that starts incomplete — lock it with a .tex-rooted differential gate, not counts](lessons/044-marker-migration-needs-differential-tex-gate.md) | preprocess | 🔴 | codified |
| 045 | [Pandoc's HTML figcaption flattens caption math for tikzpicture figures — extract the caption from source instead](lessons/045-tikzpicture-figcaption-math-flattened-by-pandoc-html.md) | post-processing | 🔴 | codified |
| 046 | [Structural parity is not render parity — only a real `myst build` catches emission bugs the text can't show](lessons/046-structural-parity-is-not-render-parity.md) | validation | 🔴 | codified |
| 047 | [pandoc's smart writer is load-bearing for HTML-comment markers — `-t markdown-smart` corrupts every `<!--MARKER-->`; dash conversion must be post-pandoc](lessons/047-markdown-smart-writer-breaks-html-comment-markers.md) | pandoc | 🔴 | codified |
| 048 | [Auto-mapping `\\ding{N}`→Unicode must run before marker extraction — once a cell's `\\ding` is base64'd into a table/figure marker, the batch pandoc pass drops it again](lessons/048-pifont-glyph-substitution-precedes-marker-extraction.md) | preprocess | 🔴 | codified |
| 049 | [multicols two-column layout needs a MyST `{grid}` — pandoc mangles literal `:::` markup, so reproduce columns via the marker pattern (one cell per column, split column-first)](lessons/049-multicols-paired-layout-needs-grid.md) | post-processing | 🟡 | codified |
| 050 | [fence-walking math/typography passes must treat `{prf:*}` content directives as transparent, not opaque code fences — else dashes/inline-math in theorem/proof titles and bodies are silently skipped](lessons/050-fence-walkers-must-descend-content-directive-bodies.md) | post-processing | 🟡 | codified |
| 051 | [pandoc drops \\item[label] optional args on itemize too, not just enumerate/description — flatten any fully-labelled list to labelled paragraphs](lessons/051-custom-item-labels-dropped-on-itemize-too.md) | preprocess | 🟡 | codified |
| 052 | [textual @key citation regex must reject an @ glued to a word char — else emails and URLs (`mailto:`, `\url`) become bogus citations](lessons/052-textual-cite-regex-must-reject-email-at-sign.md) | regex-safety | 🟡 | codified |

## By category

- **post-processing:** 001, 004, 005, 007, 008, 011, 012, 014, 015, 016, 018, 019, 020, 021, 022, 023, 025, 026, 032, 033, 034, 037, 043, 045, 049, 050
- **regex-safety:** 002, 017, 024, 031, 035, 036, 052
- **pandoc:** 027, 047
- **preprocess:** 028, 029, 030, 039, 044, 048, 051
- **katex:** 003, 006, 042
- **myst:** 013, 040, 041
- **tooling:** 009, 010, 038
- **validation:** 046

## By axis: pandoc-quirk vs permanent (Phase 4 re-tagging)

A second classification, orthogonal to category, that makes catalogue
*growth* interpretable (Phase 4 §4). **A rising quirk-count means the
pandoc/marker boundary is leaking; a rising permanent-count is just normal
coverage.**

- **pandoc-emission quirk** — a workaround for what pandoc *emits* for a
  construct. These *shrink* as constructs move onto the marker path (the
  marker bypasses pandoc for that construct), then survive only as a
  `golden_tex` lock: 007, 014, 015, 016, 017, 019, 020, 021, 022, 023, 026,
  027, 028, 029, 030, 031, 032, 033, 034, 035, 036, 037, 043, 045, 048, 051.
- **permanent** — a fact about MyST / KaTeX / sphinx-proof rendering, a
  property of our own transforms/architecture, or tooling. Not pandoc's
  fault; won't disappear by marker-izing anything: 001, 002, 003, 004, 005,
  006, 008, 009, 010, 011, 012, 013, 018, 024, 025, 038 (superseded), 039,
  040, 041, 042, 044, 046, 047 (a property of the marker round-trip,
  not of any one construct's emission), 049 (MyST has no multicols
  primitive — a layout-mapping decision, not a pandoc emission quirk),
  050 (a property of our own fence-walking transforms — content directives
  must be transparent, not opaque), 052 (our own textual-`@key` cite regex
  over-matched emails/URLs — pandoc emits the `@` correctly, so not a quirk).

## Open (gaps to close on the next book)

_None — all currently catalogued lessons are codified. New lessons will
appear here as they're captured._
