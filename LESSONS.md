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
| 028 | [Custom preamble text macros (\\DeclareUrlCommand, \\newcommand wrapping \\textcolor) pandoc drops silently along with their argument](lessons/028-preamble-text-macros-pandoc-silently-drops.md) | preprocess | 🟡 | codified |

## By category

- **post-processing:** 001, 004, 005, 007, 008, 011, 012, 014, 015, 016, 018, 019, 020, 021, 022, 023, 025, 026
- **regex-safety:** 002, 017, 024
- **pandoc:** 027
- **preprocess:** 028
- **katex:** 003, 006
- **myst:** 013
- **tooling:** 009, 010

## Open (gaps to close on the next book)

_None — all currently catalogued lessons are codified. New lessons will
appear here as they're captured._
