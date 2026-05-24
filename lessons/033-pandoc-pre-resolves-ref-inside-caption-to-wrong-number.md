---
id: 033
title: "Pandoc pre-resolves \\ref{} inside \\caption{} to a chapter-unaware number — recover the label from data-reference"
category: post-processing
tags: [pandoc, captions, cross-refs, figures, html-figure]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_html_figures.extract_caption
severity: medium
date: 2026-05-25
---

## Symptom

A `\ref{sec:X}` inside a figure `\caption{...}` renders in the final
MyST output as a chapter-unaware number — e.g. "§1.12" or "§2" for a
section that's actually §11.12 in the book. The same `\ref{sec:X}`
in body prose resolves correctly via the `{ref}` directive.

In the downstream Deep-Learning book: 10 `\caption{...\ref{}...}`
sites; at least one (`ch11_climate.md:926`) had a visibly wrong
section number in the rendered figure caption.

## Cause

Pandoc resolves `\ref{...}` **during** the LaTeX→Markdown conversion
when it appears inside `\caption{}` — for TikZ-shaped figures it
emits the resolved number as HTML:

```html
<figcaption>...search of §<a href="#sec:pareto_carbon_tax"
data-reference-type="ref" data-reference="sec:pareto_carbon_tax">2</a>
end-to-end feasible.</figcaption>
```

The `2` is what pandoc computes from the file pandoc is processing
*alone* — in a split-per-chapter pipeline that file has no chapter
context, so it counts from "1" (the chapter heading) and assigns
"§2" or "§1.12" depending on heading depth. MyST, by contrast, has
the full project context and would resolve to "§11.12" — but it
never gets the chance, because the `\a>` tag's text is the wrong
pre-computed number.

`convert_html_figures.extract_caption` then stripped *all* HTML
indiscriminately (`re.sub(r'<[^>]+>', '', cap)`), collapsing the
`<a data-reference="...">N</a>` to just `N`. The semantic label was
discarded.

Markdown-shaped figures (`\includegraphics` → pandoc `![cap](src)`)
are unaffected — pandoc emits the resolved ref as a markdown link
`[N](#X){reference-type="ref" reference="X"}`, which the existing
`convert_cross_references` pass converts to `{ref}` correctly. The
bug was specific to the HTML-figure path.

## Fix

Inside `extract_caption`, convert the HTML ref anchor back to a MyST
`{ref}` directive *before* stripping HTML. The `data-reference`
attribute carries the original label, which MyST can resolve with
full project context:

```python
cap = re.sub(
    r'<a[^>]*data-reference="([^"]+)"[^>]*>[^<]*</a>',
    lambda m: '{ref}`' + convert_label_colons(m.group(1)) + '`',
    cap,
)
cap = re.sub(r'<[^>]+>', '', cap).strip()
# extract_caption runs after strip_doubled_noun_refs /
# strip_doubled_section_symbol in the pipeline — but the {ref}
# directives we just emitted are new, so re-run those strippers
# locally on the caption string. Both are idempotent.
cap = strip_doubled_noun_refs(cap)
cap = strip_doubled_section_symbol(cap)
return cap
```

The trailing strip-call is what removes the leading `§` before
`{ref}\`sec-X\`` — MyST/sphinx-proof auto-renders the noun, so a
literal `§` in the source would produce "§Section 11.12" (doubled)
without it. The same approach handles "Chapter Chapter X" etc. for
non-section targets.

Tests in `tests/test_transforms.py`:
`test_html_figure_caption_ref_becomes_myst_directive_not_baked_number`,
`test_html_figure_caption_ref_preserves_non_section_targets`,
`test_html_figure_caption_no_refs_unchanged_shape`.

## How to detect

The bug is invisible in pipelines that don't use book-aware
numbering. For books that do (qe-v5 `injectBookSectionDefaults`),
spot-check rendered figure captions against the PDF: any "§N" where
N is just a one- or two-digit number (no chapter prefix) is a
candidate.

Programmatic check on the produced MyST:

```bash
# Caption blocks that still embed a baked digit between § and
# end-of-cell — they should be {ref} directives instead.
grep -nE '§[ \xa0]*[0-9]+(\.[0-9]+)?[^`]' mystmd/*.md
```

## Generalizable rule

**Pandoc pre-resolves cross-references inside caption-like
attribute arguments, and the resolution is single-file scoped.**
Any LaTeX construct that nests a `\ref` / `\eqref` inside an
argument pandoc treats as text-mode (captions, `\framebox`, `\fbox`,
margin notes, etc.) will lose its chapter-aware numbering when the
source is split per chapter. The defensive posture: always preserve
the `data-reference` attribute and emit a MyST `{ref}` so MyST gets
to do the resolution with full project context. Stripping HTML
wholesale is a code smell whenever cross-refs are involved.
