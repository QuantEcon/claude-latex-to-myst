---
id: 015
title: "Minted source listings need preprocessor + source-file inlining"
category: post-processing
tags: [listings, minted, source-code, gap]
source_project: book-dp1 (parity test, gap identified)
status: open
codified_in: TODO — see book-dp1/mystmd/scripts/postprocess.py::resolve_listings for reference
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

## Why this is "open" not "codified"

- The Perl preprocessor (~44 lines) would need to be rewritten in Python
  per lesson #009.
- The postprocessor needs filesystem access to read source files — adds
  the `source_code_dir` concept to the tool.
- Many books don't use minted — when present, it's a clear failure that
  the user can diagnose immediately (placeholder text in output where code
  should be).

Estimated 1–2 hours of work. Lower priority than algorithms (#014) because
the placeholder is more obviously broken (users will notice and ask) and
the workaround (manually paste the code into a `code-block` directive) is
simple.

## Reference implementation

- `book-dp1/mystmd/scripts/_rewrite_listings.pl` (44 lines, Perl)
- `book-dp1/mystmd/scripts/postprocess.py::resolve_listings` (~80 lines)

## How to detect

```bash
grep -E 'Listing: see \\texttt' mystmd/ch_*.md | head -5
```

Any matches indicate listings that fell through to the placeholder.
