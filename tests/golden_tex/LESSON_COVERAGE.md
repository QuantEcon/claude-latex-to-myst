# `golden_tex` ↔ lesson coverage

Phase-1 exit criterion: *every codified pandoc-quirk lesson has a
`golden_tex` reproducer, or is explicitly noted as not-`.tex`-reproducible.*
This file is that map. The `test_golden_tex_seeded` guard locks the cases
below into the corpus so they can't silently disappear.

## Lessons with a `.tex`-rooted reproducer

| Lesson | Case dir | What it locks |
|-------:|----------|---------------|
| 003 | `math_text_dollar` | `$` inside `\text{}` split out (KaTeX) |
| 006 | `math_percent_comment` | bare `%` line removed from math |
| 007 | `cref_comma_split` | `\cref{a,b}` → one `{prf:ref}` per key |
| 011 | `doubled_noun_ref` | prose noun before `{prf:ref}` stripped |
| 016 | `doubled_section_noun_ref` | `§` and prose `Section`/`Sections` before section `{ref}` stripped (#150) |
| 014 | `algorithm2e_block` | algorithm body → `{prf:algorithm}` bullets |
| 017 | `unnumbered_section_label` | `\label` not leaked into frontmatter label |
| 019 | `table_float_hline` | `\hline` header row preserved through marker path |
| 020 | `cite_natbib_variants` | citealp / citeyearpar / citep[loc] decoded |
| 022 | `description_item_labels` | `\item[Term]` labels preserved |
| 023 | `algorithm2e_block` | algpseudocode (`\STATE`/`\WHILE`) body parsed |
| 025 | `table_float_hline` | table marker path (vs simple_tables) |
| 031 | `cite_textual_colon_key` | colon-bearing bib key not truncated |
| 032 | `align_per_row_labels` | per-row `\label` in align extracted |
| 034 | `lstlisting_code_block` | lstlisting → `{code-block}` directive |
| 035 | `cite_textual_colon_key` | trailing `:` not swallowed into key |
| 037 | `multline_gather_labels` | label in gather extracted (1st trailing, rest anchors) |
| 039 | `enumerate_exercise` | fully-labelled enumerate → `{exercise}` |
| 042 | `math_thin_space_superscript` | `\,^X` gets empty base `\,{}^X` |
| 043 | `figure_caption_citation` | caption citation recovered, no key drop |
| #98 #1 | `figure_width_option` | `:width:` percentage preserved |
| #98 #2 | `figure_label_in_caption` | caption not leading-spaced / label recovered |
| #98 #3 | `figure_raw_tikzpicture_with_override_bails` | tikzpicture bail (no node-text leak) |
| #98 #4 | `figure_includegraphics_path_on_next_line` | image not dropped when path wraps |

## Lessons not cleanly `.tex`-reproducible (covered elsewhere)

These are codified but a focused `input.tex → expected.md` either can't
trigger them (pandoc strips the trigger before emit; needs an external
source file or multi-file numbering) or they are not pandoc-emission
quirks (tooling / regex-internals / MyST facts). Each names where it *is*
guarded.

| Lesson | Why not here | Guarded by |
|-------:|--------------|-----------|
| 001 | blank-line-in-`$$` arises from pandoc emission, not a focused `.tex` shape | `tests/test_transforms.py` (`strip_blank_lines_in_math`) |
| 002 | regex-safety internal (`[0,1)` false-match) | `tests/test_transforms.py` cross-ref cases |
| 004 | id-recycling is an impl detail, not a `.tex` quirk | unit tests (label generation) |
| 005 | env-skip depth — candidate future case | `tests/test_transforms.py` (env skip) |
| 008 | pipeline ordering is architectural | `tests/test_pipeline_order.py` |
| 009 | BSD-sed/portability — tooling, not conversion | n/a (CI runs the real shell) |
| 010 | `uv`/PEP-668 — tooling | CI `uv sync` step |
| 012 | blank-after-`$$` is cosmetic; emerges in every math case | observed in `math_*` cases |
| 013 | footnote-ref is a MyST limitation, not an emission quirk | n/a (documented MyST fact) |
| 015 | minted needs an external listed source file | `tests/test_preprocessors.py` (listing markers) |
| 018 | body-anchor promotion needs a heading-context fixture | `tests/test_transforms.py` |
| 021 | subfigure currently *bails* to the HTML fallback | deferred to Phase 4 (#94) — case added when marker-ized |
| 024 | orphan-label DOTALL is regex-safety internal | `tests/test_transforms.py` |
| 026 | `<embed>` vs `<img>` needs an `\input{tikz/…}` target file | `tests/test_figure_*` |
| 027 | empty-`<!-- -->` separator is a pandoc artifact scrubbed in markers | `tests/test_transforms.py` (`strip_pandoc_html_separators`) |
| 028 | preamble macro drop needs a preamble + config rewrite | `_warn_dropped_text_macros.py` + `tests/test_preprocessors.py` |
| 029 | nested-`\item`-in-description — preprocess edge | `tests/test_preprocessors.py` (description markers) |
| 030 | inline-`\itemsep` — preprocess edge | `tests/test_preprocessors.py` |
| 033 | ref-in-caption needs cross-chapter numbering (multi-file) | partially `figure_label_in_caption`; `tests/test_figure_*` |
| 036 | attr-fence-brace is regex-safety internal | `tests/test_transforms.py`; `lstlisting_code_block` exercises the path |
| 038 | module double-load is a tooling/import quirk | `tests/test_main_invocation.py` |
| 040 | nested-fence-count is a MyST emit rule | directive emitters in `tests/test_transforms.py` |
| 041 | nested-table double-enumerate is a MyST directive fact | `tests/test_tables_from_latex.py` |
| 044 | this lesson *is* the §1b differential gate | `tests/test_marker_differential.py` |
