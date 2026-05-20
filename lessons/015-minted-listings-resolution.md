---
id: 015
title: "Minted source listings need preprocessor + source-file inlining"
category: post-processing
tags: [listings, minted, source-code]
source_project: book-dp1 (parity test, gap identified)
status: codified
codified_in: scripts/_apply_listing_markers.py + postprocess.py::resolve_listings
severity: medium
date: 2026-05-20
---

## Symptom

Books using `\begin{listing}` + `\inputminted{lang}{path}` to embed source
code (with line ranges, captions, and `{numref}`-able labels) lose all
structure in conversion. Our current config-driven preprocess turns
`\inputminted` into `\par\textit{Listing: see \texttt{path}}` — a flat
italic placeholder with no caption, no label, no source content.

Cross-references to listings (`Listing {ref}`list-foo``) then dangle.

## Cause

A minted listing in LaTeX looks like:

```latex
\begin{listing}
  \caption{\label{list:s_approx} Successive approximation}
  \inputminted[firstline=3, lastline=20]{julia}{../source_code_jl/s_approx.jl}
\end{listing}
```

This carries metadata (label, caption, language, source path, line range)
that pandoc has no idea what to do with. Without preprocessing, all of it
is lost.

## Fix (gap — not yet codified)

dp1's approach has two parts:

1. **Preprocess** (`_rewrite_listings.pl`): walks the .tex source, finds
   `\begin{listing}...\end{listing}` blocks, extracts label/caption/lang/path/range,
   and emits an HTML-comment marker:

   ```html
   <!--LISTING-START name=list-s_approx lang=julia path=../source_code_jl/s_approx.jl first=3 last=20-->
   Successive approximation
   <!--LISTING-END-->
   ```

2. **Postprocess** (`resolve_listings`): finds the markers, reads the
   referenced source file, slices `first..last`, and emits a MyST
   `code-block` directive:

   ````markdown
   ```{code-block} julia
   :name: list-s_approx
   :caption: Successive approximation
   :linenos:

   <source lines 3-20 inlined here>
   ```
   ````

   The directive supports `{numref}`list-s_approx`` for cross-references.

## Codified implementation

Ported from dp1 in two pieces, both Python (no Perl, per lesson #009):

1. **`scripts/_apply_listing_markers.py`** — replaces the dp1 Perl
   preprocessor. Run inside `preprocess.sh` after `_apply_rewrites.py`,
   before pandoc. Walks the `.tex` source, parses
   `\inputminted[opts]{lang}{path}` (extracting `firstline=`/`lastline=`
   from the opts) and the trailing `\caption{\label{...} ...}`, then
   emits a `<!--LISTING-START name=... lang=... path=... first=... last=... -->
   caption\n<!--LISTING-END-->` block per listing.

2. **`postprocess.py::resolve_listings`** — finds the markers (tolerating
   pandoc's `\<...\>` escaping), reads the referenced source file relative
   to `_LISTING_SOURCE_BASE`, slices `first..last`, and emits a MyST
   `code-block` directive with `:name:`, `:caption:`, `:linenos:`. Missing
   source files produce a TODO comment in the body rather than failing
   the build. Wired into `process_file` AFTER `convert_citations` and
   `convert_standalone_labels` — running it later avoids letting
   transforms like the inline-citation regex eat Julia-style `@views`
   macros inside the inlined source.

## New config option: `source_code_base`

Defaults to `source_dir`. Override when the source code lives outside the
LaTeX source tree (uncommon). For dp1-style layouts where
`\inputminted{julia}{../source_code_jl/foo.jl}` appears in a tex file
inside `book/`, the default resolves correctly.

## Pipeline-ordering bug surfaced

The first verification run had `@views` (a Julia macro) being converted
into `{cite:t}`views`` by `convert_citations` because `resolve_listings`
was running before `convert_citations`. Fix: move both `resolve_listings`
and `resolve_algorithms` to LATE in the pipeline (after citations and
standalone labels) so source-code bodies are inlined into the document
only after all prose transforms have already run. Matches dp1's order.

Verified byte-identical to dp1's committed output across all five
chapters with `\begin{listing}` blocks (ch_intro × 6, ch_mcs × 5,
ch_mdps × 7, ch_val × 2, ch_ctime × 1; 21 listings total).

## How to detect a regression

```bash
grep -E 'Listing: see \\texttt|source not found' mystmd/ch_*.md
```

Any matches indicate listings that fell through to a placeholder. The
first pattern catches the legacy bare-`\inputminted` rewrite; the second
catches listings whose source file we couldn't read.

## Reference implementation (historical)

- `book-dp1/mystmd/scripts/_rewrite_listings.pl` (44 lines, Perl) — replaced
- `book-dp1/mystmd/scripts/postprocess.py::resolve_listings` (~80 lines) — ported
