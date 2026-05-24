---
id: 034
title: "Pandoc attribute fenced code blocks (from lstlisting) are not honoured by MyST — convert to {code-block} directives"
category: post-processing
tags: [pandoc, lstlisting, listings, fenced-code, cross-refs]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_pandoc_attr_code_blocks
severity: medium
date: 2026-05-25
---

## Symptom

`\begin{lstlisting}[caption={Foo}, label=lst:X]` source survives
pandoc as a fenced code block with a pandoc attribute info string:

```
``` {#lst:X .python caption="Foo" label="lst:X" language="Python"}
body
```
```

MyST treats the `{…}` as an arbitrary info string and **ignores it
entirely** — no `:name:`, no `:caption:`, no anchor target. Any
`\ref{lst:X}` elsewhere in the body becomes a `{ref}\`lst-X\``
directive that resolves to nothing because no `(lst-X)=` anchor was
ever emitted.

In the downstream Deep-Learning book: 1 occurrence
(`lst:autodiff_euler`), but the pattern is the only labelled-listing
shape pandoc emits.

## Cause

`lstlisting` is from the `listings` package and is handled by pandoc
*natively* — unlike the `minted` `\begin{listing}` environment which
the project preprocesses via `_apply_listing_markers.py`. So no
preprocess pass touches `lstlisting`; the pandoc output flows
through postprocess untouched; no transform recognised the
pandoc-attribute info-string shape; MyST dropped the attributes.

The shape pandoc emits is documented:

- `#id` — pandoc identifier (mapped from LaTeX `label=`)
- `.lang` — language class (mapped from lowercased `language=`)
- `caption="…"`, `label="…"`, `language="…"` — pandoc key-value
  attributes (`label=` and `caption=` flow through verbatim)

MyST's directive fence shape is the visually similar but
*semantically distinct* `\`\`\`{code-block} python` — same braces,
but with the directive name inside, no space between `\`\`\`` and
`{`. The two must not be confused.

## Fix

A new postprocess transform `convert_pandoc_attr_code_blocks` that:

1. Matches `^\`\`\`[ \t]+\{...\}` (pandoc shape — requires a space)
   followed by a body and a closing `\`\`\``.
2. Guards on content shape — the brace contents must contain at
   least one of `#`, `.`, or `=` to be treated as a pandoc attr
   block (MyST directive names never contain these).
3. Parses `#id`, `.class`, and `key="value"` tokens.
4. Emits a `{code-block}` directive when an `id` or `caption` is
   present (the cross-refable, captionable case):

   ````
   ```{code-block} python
   :name: lst-X
   :caption: Foo

   body
   ```
   ````

5. Strips the attribute block to a plain fenced code block when no
   `id` or `caption` is set (purely cosmetic attrs from pandoc that
   would otherwise look like a broken info string in MyST).

Pipeline placement: runs early (before `convert_simple_tables`) so
code-block bodies are claimed as structured directives before any
downstream pass might scan inside them. Most postprocess transforms
already skip fenced blocks, but ordering it early is a safety belt.

Tests in `tests/test_transforms.py`:
`test_pandoc_attr_code_block_label_becomes_name`,
`test_pandoc_attr_code_block_label_only_no_caption`,
`test_pandoc_attr_code_block_lang_only_strips_attrs`,
`test_pandoc_attr_code_block_label_with_colon_chain`,
`test_pandoc_attr_code_block_does_not_touch_myst_directive_fence`,
`test_pandoc_attr_code_block_idempotent`.

## How to detect

Grep the produced MyST for the pandoc-attr fence shape:

```bash
grep -nE '^``` +\{[#.]' mystmd/*.md
```

Any hit means a pandoc-attribute fenced block survived into the
output without being converted — `convert_pandoc_attr_code_blocks`
either didn't run or didn't match (regex variant). A clean run has
zero hits.

## Generalizable rule

**LaTeX environments that pandoc handles natively are not
automatically MyST-compatible.** `lstlisting`, `verbatim`,
`Verbatim`, `BVerbatim` all produce fenced code blocks with pandoc
attribute syntax — and MyST does not honour pandoc's attribute
syntax. Whenever the LaTeX environment has *semantic metadata*
(label, caption, language) that the user expects to flow through,
the postprocess pass must convert pandoc's attribute info-string
into a MyST directive. The minted/`\begin{listing}` path solves
this via a preprocess marker pass (lesson 015); `lstlisting`
solves it via a postprocess fenced-block transform — different
shapes, same underlying problem.
