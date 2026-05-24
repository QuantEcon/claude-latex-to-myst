---
id: 028
title: "Custom preamble text macros (\\DeclareUrlCommand, \\newcommand wrapping \\textcolor) pandoc drops silently along with their argument"
category: preprocess
tags: [pandoc, preamble, custom-macros, declareurlcommand, newcommand, warning]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/_warn_dropped_text_macros.py
severity: medium
date: 2026-05-24
---

## Symptom

In the converted markdown, sentences contained empty spans where a
custom inline macro had been:

```
The Python notebooks still use the variable name ;
In notebook , the convergence …
emphasized terms appear in ;
```

The source LaTeX was complete:

```latex
The Python notebooks still use the variable name \tpath{rho};
In notebook \tpath{lecture_15_03_Structural_Estimation_BM.ipynb}, …
emphasized terms appear in \emphc{bold crimson};
```

Pandoc dropped `\tpath{…}` and `\emphc{…}` **along with their
argument** — leaving broken sentences scattered through the book.
The book that surfaced this used `\tpath` 160 times.

Only visible during visual review; no error, no warning.

## Cause

Pandoc handles a fixed set of text-formatting commands natively
(`\textbf`, `\textit`, `\texttt`, `\emph`, `\textsf`, `\textnormal`,
`\textsc`, `\underline`). Anything else defined in the preamble is
unknown to pandoc and gets dropped at the AST level.

Two shapes in practice:

**Shape A — `\DeclareUrlCommand` for monospace identifiers.**

```latex
\DeclareUrlCommand\tpath{\urlstyle{tt}}
```

`\DeclareUrlCommand` is a `hyperref`-defined macro pandoc has no
handler for at all. Every `\tpath{…}` use vanishes.

**Shape B — `\newcommand` wrapping non-native macros.**

```latex
\newcommand{\emphc}[1]{\textcolor{harvardcrimson}{\textbf{#1}}}
```

Pandoc can sometimes expand `\newcommand` definitions, but not when
the body uses commands it doesn't know (`\textcolor`, custom
spacing, etc.). The whole expansion fails and the macro is dropped.

The result is the same in both cases: macro and argument both gone,
no warning.

## Fix

`scripts/_warn_dropped_text_macros.py` scans the source preamble(s)
for these definitions, counts usages across chapter files, and
prints a single warning with a paste-ready `preprocess.rewrites`
block:

```
WARNING: custom text macros pandoc may drop silently:

  \tpath  — used 160× across ch_intro.tex, ch_methods.tex, …
      suggested rewrite: \tpath{…} → \texttt{…}
  \emphc  — used 1× across ch_intro.tex
      suggested rewrite: \emphc{…} → \textbf{…}

To apply, add to config.yaml under preprocess.rewrites:

    - { from: '\\tpath\{((?:\\.|[^{}])*)\}',
        to:   '\texttt{\1}' }
    - { from: '\\emphc\{((?:\\.|[^{}])*)\}',
        to:   '\textbf{\1}' }
```

This is **Level 1 — warn** from the issue proposal. The pipeline
does not automatically rewrite (Level 2) because:

- Styling is lossy — `\emphc`'s crimson colour is gone, `\tpath`'s
  URL-style `_`-breaking is gone. The user should consciously accept
  that trade vs. keeping the formatting and writing the macro out by
  hand.
- The mapping is heuristic. The warner's "suggested rewrite" guesses
  the closest pandoc-native target by inspecting the body
  (`\textcolor`+`\textbf` → `\textbf`; `\urlstyle{tt}` → `\texttt`).
  Sometimes the user knows a better one.

Wired into [scripts/preprocess.sh](../scripts/preprocess.sh) after
the per-chapter rewrites complete. Non-fatal; never blocks the
pipeline. No-op when no such macros exist or none are used.

Tests in [tests/test_preprocessors.py](../tests/test_preprocessors.py):
`test_warn_declare_url_command_detected_with_suggestion`,
`test_warn_newcommand_textcolor_textbf_suggests_textbf`,
`test_warn_newcommand_math_only_not_flagged`,
`test_warn_count_usages_skips_definitions`,
`test_warn_scan_end_to_end`, `test_warn_scan_no_macros_is_quiet`.

## How to detect (without running the warner)

Manually, in any LaTeX source dir:

```bash
# Custom URL-style monospace macros
grep -n '\\DeclareUrlCommand' *.tex
# Custom \newcommand definitions whose body uses non-pandoc commands
grep -nE '\\(re)?newcommand.*\\textcolor' *.tex
grep -nE '\\(re)?newcommand.*\\urlstyle' *.tex
```

Any hit is a candidate for the silent-drop bug. Cross-check by
greping the chapters for `\X{…}` uses; if the macro is used and not
listed in the user's `preprocess.rewrites`, the converted markdown
will be broken at every use site.

## Generalizable rule

**Pandoc's "I don't know this macro, drop it silently" failure mode
is the worst possible default for a deterministic pipeline.** A
build that silently produces broken output is strictly worse than a
build that fails loudly. Whenever the upstream tool has this mode,
the wrapper pipeline should:

1. **Detect** the silent-drop precondition (here: scan the
   preamble for custom text macros).
2. **Surface** what will be dropped before pandoc runs.
3. **Suggest** a deterministic workaround (here: a paste-ready
   `preprocess.rewrites` block that converts the custom macro to a
   pandoc-native one).
4. **Not auto-apply** until the user opts in — because the workaround
   is lossy and the user should make the loss conscious.

This is the same shape as lessons 014 (algorithm2e), 015 (minted),
022 (description envs), and the natbib bracket-marker sentinels
(lesson 020): pandoc has multiple "silently malforms this" failure
modes that need to be surfaced and worked around before pandoc
runs, not after.
