---
id: 054
title: "Under qe-v8 numbering.book mode a chapter {ref} renders \"Chapter N\", so prose \"Chapter~\\ref{ch:x}\" doubles to \"Chapter Chapter N\" — the {ref}-role doubled-noun table must be book-configurable"
category: post-processing
tags: [cross-ref, doubled-noun, chapter, numbering, book-mode, config-surface, ref]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/conversion_context.py (doubled_noun_refs role key) + scripts/transforms/refs.py::strip_doubled_noun_refs (ctx.doubled_section_noun_refs)
severity: medium
date: 2026-07-06
---

## Symptom

In a book that sets qe-v8 `numbering.book.enabled: true` with
`chapters.label: "Chapter %s"`, prose like

```latex
Readers may skim this chapter and proceed to Chapter~\ref{ch:deqn}.
```

converts to `proceed to Chapter {ref}`ch-deqn`` and **renders**
"proceed to Chapter **Chapter 2**" — the noun is printed twice. A
rendered-text sweep of the deep-learning book found **180 sites** across
all 12 chapters, including appendix section headings
(`Chapter~\ref{ch:X}: Title`), so the doubling also infects the
appendix table of contents.

Verified against the built AST: a `{ref}` to a chapter page-label resolves
to a `link` node whose rendered children are literally `Chapter 2`.

## Cause

`strip_doubled_noun_refs` (`transforms/refs.py`) strips the prose noun
before a ref that auto-renders that noun, but it had two gaps for chapters:

1. The `{prf:ref}`/`{numref}` table (`_DOUBLED_NOUN_REFS`) has a
   `('Chapter', 'c-')` entry, but chapter refs route to plain `{ref}`, not
   those roles.
2. The `{ref}`-role table (`_DOUBLED_SECTION_NOUN_REFS`) **deliberately
   omitted** Chapter, reasoning (correctly, for qe-v5) that
   `injectBookSectionDefaults` enables `numbering.heading_2`..`heading_6`
   only, so a chapter-level `{ref}` renders the chapter *title* and the
   prose noun is needed. **That assumption is stale under qe-v8
   `numbering.book`**, where the chapter ref renders "Chapter N".

And the fix couldn't be expressed at the config surface: `doubled_noun_refs`
entries fed **only** the `{prf:ref}`/`{numref}` matcher, never `{ref}`.

## Fix

Whether a chapter/section `{ref}` renders a noun depends on the book's
`myst.yml` numbering mode — which the converter can't know unilaterally —
so the durable fix makes the `{ref}`-role table **book-configurable** (the
issue's option (b), mirroring how `Algorithm`/`alg-` is already book-local
for `{prf:ref}`):

- A `doubled_noun_refs` config entry may now carry `role: ref`. Those
  entries are parsed into a new `ConversionContext.doubled_section_noun_refs`
  list (`conversion_context.from_config`); entries with no role (or
  `role: prf:ref`/`numref`) keep landing in `doubled_noun_refs` as before.
- `strip_doubled_noun_refs` iterates
  `ctx.doubled_section_noun_refs + _DOUBLED_SECTION_NOUN_REFS` in the
  `{ref}`-role loop.

A book under book-mode numbering opts in with:

```yaml
doubled_noun_refs:
  - { noun: Chapter,  prefix: ch-, role: ref }
  - { noun: Chapters, prefix: ch-, role: ref }
```

Plurals de-double correctly (only the leading noun is redundant;
`Chapters {ref}`ch-a`–{ref}`ch-b`` → "Chapter 2–Chapter 3"), the
NBSP `~`-tie is already handled by the shared `[ \xa0]+` separator, and
the `(?<!\w)` guard keeps "Subchapter" intact.

Golden case `doubled_chapter_noun_ref`; context/routing unit tests in
`test_conversion_context.py`.

## How to detect

```bash
# The doubling signature in rendered text (build the HTML, then):
grep -rE 'Chapter Chapter [0-9]' _build/**/*.json    # zero after opt-in
# Or spot the un-stripped prose noun in the markdown:
grep -rnE 'Chapters?[ \xc2\xa0]+\{ref\}`ch-' mystmd/*.md
```

## Generalizable rule

A "strip the prose noun that the ref auto-renders" table is only correct
relative to a **specific numbering mode**. When the same construct renders
a noun in one mode and a title in another (chapter `{ref}` = "Chapter N"
under `numbering.book` vs. the chapter *title* under qe-v5 heading-only
numbering), the noun/role/prefix keying can't be a hard-coded default — it
must be opt-in at the config surface, because only the book's `myst.yml`
settles which mode is in force. Prefer extending the existing config key
(a `role:` discriminator on `doubled_noun_refs`) over inventing a new one.

Related: lesson [011](011-doubled-noun-refs.md) (the original theorem-noun
doubling), lesson [016](016-section-symbol-doubled-prefix.md) (the `§`/
Section `{ref}` doubling and the qe-v5 heading-numbering premise this
revises).
