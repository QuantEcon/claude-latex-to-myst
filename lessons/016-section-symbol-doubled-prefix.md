---
id: 016
title: "§ Section: qe-v5 section labels double the prefix in §\\ref{...} prose"
category: post-processing
tags: [cross-references, sphinx-proof, qe-v5, section-labels, doubled-prefix]
source_project: book-dp2 (qe-v5 Parts adoption test)
status: codified
codified_in: scripts/postprocess.py::strip_doubled_section_symbol
severity: medium
date: 2026-05-20
---

## Symptom

After adopting qe-v5 mystmd (PR [QuantEcon/mystmd#26](https://github.com/QuantEcon/mystmd/pull/26))
and enabling `numbering.book.enabled` for dp2, prose like:

```latex
…the firm problem of \S\ref{s:fpintro}, the finite MDP of \S\ref{s:mdps}…
```

renders as:

```
…the firm problem of § Section 1.1, the finite MDP of § Section 1.2…
```

— with a redundant `§` glyph before the auto-rendered "Section X.Y". The
author wrote `\S\ref{...}` (LaTeX shorthand: literal section glyph + a
raw reference number), expecting "§ 1.1". qe-v5 now auto-prefixes the
ref with "Section", so the prose contains both the manual `§` and the
auto-rendered "Section".

In dp2 this affects ~110 places across all chapters (every `\S\ref{s:...}`,
`\S\ref{ss:...}`, `\S\ref{sss:...}` callsite). The pattern is identical in
shape to lesson [011](011-doubled-noun-refs.md) but for section symbols
rather than theorem-style nouns.

A second variant: `§ Paragraph</a>` for refs to heading_5 / heading_6 in
some places — qe-v5's section labels render the noun based on the heading
depth, and dp2 has some sub-sub-subsections.

## Cause

1. LaTeX writers ubiquitously prefix `\S` (or `§` directly, or `Section~`)
   before `\ref{ss:foo}` because in raw LaTeX `\ref` returns just the
   counter (`1.1`), without any noun. The `\S` provides the noun visually.
2. Pandoc preserves `\S` verbatim as U+00A7 (`§`).
3. After our cross-reference converter runs, the LaTeX becomes
   `§{ref}`s-fpintro`` (or `§\xa0{ref}\``…``).
4. Before qe-v5 this rendered as "§ 1.1" — fine, matched author intent.
5. After qe-v5 with book-mode enabled, `injectBookSectionDefaults` turns on
   `numbering.heading_2.enabled` (and heading_3/4/5/6) for chapter and
   appendix pages. Cross-refs to those headings render via the section
   label format, producing "Section 1.1" (or "Paragraph" for deeper
   depths), so the prose now reads "§ Section 1.1".

This is fundamentally the same shape as lesson 011 ("Theorem {prf:ref}" →
"Theorem Theorem 1.2") — a noun the author wrote manually duplicates a
noun the framework now auto-renders.

## Codified implementation

Implemented as `strip_doubled_section_symbol` in `postprocess.py`,
following the shape proposed below. Module-level prefix list
`_DOUBLED_SECTION_SYMBOL_PREFIXES = ('s-', 'ss-', 'sss-', 'sec-')`
guards against stripping `§` before non-section refs. Runs in
`process_file` immediately after `strip_doubled_noun_refs`, sharing the
"operates on already-converted MyST refs" placement.

Verified against dp2: the `§{ref}` pattern (with any space/NBSP between)
dropped from 471 occurrences in the regenerated output to 0. The 13
remaining `§` occurrences are all legitimate external section refs (e.g.,
"§10.2 of {cite}`sargent2025dynamic`") and correctly preserved.

## Fix as proposed (now codified)

Extend the doubled-prefix strip in `postprocess.py` to handle `§` (and
optionally `§ ` / `§\s+`) before a `{ref}` whose label points to a
section-style target. Section labels in dp1/dp2 use prefixes `s-`, `ss-`,
`sss-`, and `sec-`. A reasonable transform:

```python
_DOUBLED_SECTION_SYMBOL_PREFIXES = ('s-', 'ss-', 'sss-', 'sec-')

def strip_doubled_section_symbol(text: str) -> str:
    """Drop a literal § (or §\\xa0) before a {ref} that auto-renders as
    'Section X.Y' under qe-v5 book-mode heading labels."""
    pat = re.compile(
        r'(?<!\w)§[ \xa0]*'                          # literal § + optional space/NBSP
        r'(\{ref\}`(?:' + '|'.join(map(re.escape, _DOUBLED_SECTION_SYMBOL_PREFIXES))
        + r')[^`]+`)'
    )
    return pat.sub(r'\1', text)
```

Could go in the same transform pass as `strip_doubled_noun_refs` (sits
after `convert_cross_references` so the `{ref}` syntax is already in MyST
form).

**Alternative considered:** strip the `Section` *prefix* in rendered output
rather than the author's `§`. Rejected because:
- The label is applied by mystmd at HTML render time, not in our markdown
  output — we'd have to fight the framework.
- Other places that legitimately want "Section X.Y" (no author-side `§`)
  would lose their label.
- Authors are the source of the duplication; their manual `§` is the
  correct thing to strip.

## Scoping decisions resolved at codification

- **Prefix-matched, not unconditional.** Strips only when the ref label
  starts with one of `_DOUBLED_SECTION_SYMBOL_PREFIXES` — avoids
  over-stripping `§` before non-target refs.
- **Current prefix list.** `s-`, `ss-`, `sss-`, `sec-` (sections), plus
  `eg-` (examples). `eg-` was added after the dp2 application surfaced
  one `\S\ref{eg:foo}` — an author-side semantic mismatch (`\S` before
  an example label) that produced "§ Example X.Y" under qe-v5. New
  prefixes added on demand; not preemptively (YAGNI).
- **"Paragraph" variant.** Not separately handled; if it surfaces with a
  label-prefix not in the current list, extend the same constant rather
  than adding another function.
- **dp1 adoption.** dp1 predates qe-v5; transform is a no-op there until
  dp1 adopts qe-v5 book-mode, at which point it activates automatically.

## How to detect

```bash
# Count remaining "§ Section" / "§ Paragraph" in built HTML
grep -oE '§\s*(Section|Paragraph)[\s<]' mystmd/_build/html/**/index.html | wc -l
```

Should be 0 after the transform lands. dp2's regenerated mystmd has 0;
committed dp2 mystmd (pre-transform) has 471.

## Reference (qe-v5 source)

- `packages/myst-cli/src/process/mdast.ts::injectBookSectionDefaults` —
  the function that enables `heading_2.enabled` (and 3..6) on chapter and
  appendix pages.
- `packages/myst-transforms/src/enumerate.ts` — applies the heading label
  format when resolving cross-references.
