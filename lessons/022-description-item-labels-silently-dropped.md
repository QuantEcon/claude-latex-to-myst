---
id: 022
title: "Pandoc silently drops \\item[Term] labels in description envs — preprocess to sentinel markers"
category: post-processing
tags: [description-list, definition-list, pandoc, silent-data-loss, sentinel-markers]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/_apply_description_markers.py + scripts/postprocess.py::convert_description_lists
severity: high
date: 2026-05-22
---

## Symptom

LaTeX `description` lists arrived in MyST as `::: description` divs
with every `\item[Term]` term label silently stripped — only the
definition bodies survived. The term/definition pairing, which is the
entire point of the construct, was lost.

In the first external-book conversion (DL for DSGE) this affected
three description blocks in the body plus the entire Glossary
appendix, which became a paragraph soup of definitions with no terms
attached.

## Cause

Pandoc's LaTeX reader collapses `\begin{description}\item[T] body…`
into a `Div(class="description")` containing only the body paragraphs.
The term labels do not appear in the pandoc native AST at all:

```text
$ pandoc desc.tex -f latex -t native
[ Div ( "" , [ "description" ] , [] )
    [ Para [ Str "Some" , Space , Str "equations..." ] ]
]
```

Because the labels are dropped *before* the markdown writer runs, no
post-pandoc regex can recover them. The fix has to intercept before
pandoc sees the file.

## Fix

Same sentinel-marker pattern as algorithm2e (lesson 014) and minted
listings (lesson 015):

### 1. Preprocess: rewrite the env into HTML-comment markers

`scripts/_apply_description_markers.py` rewrites each
`\begin{description}…\end{description}` block into:

```text
<!--DESCRIPTION-START-->

<!--DESCITEM term=BASE64TERM-->

body for item 1...

<!--DESCITEM term=BASE64TERM-->

body for item 2...

<!--DESCRIPTION-END-->
```

The term label is base64-encoded so it can contain arbitrary
characters (`]`, `{}`, inline math, em-dashes) without the marker
parser needing to know about LaTeX escaping. Pandoc preserves HTML
comments as `\<!--…--\>` (same escaping it applies to natbib bracket
markers and algorithm markers), so the markers reach the postprocess
stage intact.

### 2. Postprocess: decode markers to MyST def-list syntax

`scripts/postprocess.py::convert_description_lists` finds each
`DESCRIPTION-START…DESCRIPTION-END` block, splits it on `DESCITEM`
markers, decodes the base64 term, and emits:

```markdown
Term1
: Body for item 1.

Term2
: Body for item 2.
```

This is MyST's standard definition-list syntax (markdown-extra
flavour), rendered as a proper `<dl>` in HTML.

## Scope decisions

- **Optional `\begin{description}[opts]` arguments are stripped.**
  These are LaTeX-side formatting options (`itemsep=3pt`,
  `leftmargin=1.4em`) with no MyST analogue.
- **`\item` without `[…]` becomes a plain paragraph**, matching the
  LaTeX rendering (no term).
- **Term parser uses simple `[^\]]+`.** A term containing a literal
  `]` (e.g. `\item[$x \in [0,1]$]`) truncates at the first `]`. This
  is acceptable: such terms are vanishingly rare, and the rest of the
  bracket content flows into the body where it's visible to the
  author for hand-correction. A balanced-bracket parser would add
  ~30 lines of code to handle a case that hasn't been observed in
  the wild.
- **Skips commented-out blocks.** Same guard as the algorithm and
  listing preprocessors (`_starts_in_comment`).

## How to detect

```bash
# Pre-fix: ::: description divs in output, no def-list syntax.
grep -rE '^::: description' mystmd/*.md

# Post-fix: definition-list syntax appears, no description divs.
grep -rE '^: ' mystmd/*.md      # at least one match per affected chapter
grep -rE '^::: description' mystmd/*.md  # zero matches

# Sanity: marker residue (would indicate a pipeline-ordering bug
# where convert_description_lists ran before its inputs were ready).
grep -rE 'DESCITEM|DESCRIPTION-(START|END)' mystmd/*.md  # zero
```

## Generalizable rule

Whenever a pandoc target collapses a LaTeX construct in a lossy way,
preprocess the source into HTML-comment sentinels that pandoc passes
through verbatim, then decode post-pandoc. The pattern has now been
applied to four constructs:

- algorithm2e blocks (lesson [014](014-algorithm2e-resolution.md))
- minted source listings (lesson [015](015-minted-listings-resolution.md))
- natbib variants pandoc collapses ambiguously (lesson [020](020-natbib-bracket-markers-precede-cross-refs.md))
- description envs (this lesson)

For terms or labels that may contain arbitrary characters,
base64-encode them inside the marker — it keeps the marker grammar
trivial (`[A-Za-z0-9+/=]*`) regardless of the source content.

Related: lesson [008](008-pipeline-ordering.md) (transform order).
