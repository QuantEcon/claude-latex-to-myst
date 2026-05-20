---
id: 008
title: "Post-processing transform order is critical and fragile"
category: post-processing
tags: [pipeline, ordering, architecture]
source_project: book-dp2
status: codified
codified_in: postprocess.py::process_file
severity: high
date: 2026-04-09
---

## Symptom

Subtle bugs where one transform destroys structures another transform needs.
Examples seen in dp2:

- Running `convert_figures` before `convert_cross_references` strips `{eq}`
  refs from figure captions.
- Running `convert_equations` before `fix_text_dollar` changes `$$` structure
  in a way that breaks `\text{$...$}` repair.
- Running `convert_citations` before `convert_environment_divs` mistakes
  `@cite_key` in theorem bodies for a citation.

## Cause

Each transform makes assumptions about what intermediate state looks like.
If an earlier transform has already rewritten that state, the later one no
longer matches.

## Fix

Fix the canonical order in `process_file` and never reorder casually. The
working order is:

```
1.  fix_text_dollar          (must be first; touches $$ structure)
2.  convert_epigraphs
3.  convert_environment_divs (restructures into fenced blocks)
4.  convert_equations        (before cross-refs so labels are extracted)
5.  convert_cross_references (before figures; captions may contain refs)
6.  convert_figures
7.  convert_html_figures
8.  resolve_tikz_figures
9.  convert_section_labels
10. convert_citations
11. convert_standalone_labels
12. join_split_inline_math
13. cleanup_typography
14. add_frontmatter           (last)
```

When adding a new transform, explicitly document its dependencies in a
comment next to the call site.

## How to detect

Hard to detect statically. If reordering produces *any* behavioral change,
the new order is wrong. Have a small fixture of pandoc output checked in
and run the full pipeline on it as a regression test.
