---
id: 053
title: "An lstlisting option whose value is 2+ adjacent brace groups (escapeinside={(*}{*)}) derails pandoc's option scan and leaks the whole [...] group into the code body"
category: preprocess
tags: [lstlisting, code-block, escapeinside, literate, pandoc, preprocess, option-parsing]
source_project: Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models (external)
status: codified
codified_in: scripts/_apply_lstlisting_options.py (pre-pandoc strip of multi-brace-group lstlisting options)
severity: medium
date: 2026-07-06
---

## Symptom

An `lstlisting` whose option group contains `escapeinside={(*}{*)}` leaks
the **entire** option string into the converted code block: the rendered
block's first line is the literal option text, before the real code.

```latex
\begin{lstlisting}[language=Python, basicstyle=\footnotesize\ttfamily, frame=single, numbers=none, escapeinside={(*}{*)}]
import numpy as np
\end{lstlisting}
```

converted to

````markdown
```{code-block} python
[language=Python, basicstyle=\footnotesize\ttfamily, frame=single, numbers=none, escapeinside={(*}{*)}]
import numpy as np
```
````

## Cause

Pandoc's `lstlisting` optional-argument parser reads a key's value as a
**single** `{...}` group. A value built from two or more *adjacent* brace
groups — `escapeinside={(*}{*)}` (two groups), `literate={a}{b}1` (two
groups plus a trailing token) — leaves the second group where pandoc
expects a comma or the closing `]`, so the `[...]` scan never matches its
closing bracket. Pandoc then gives up on the option group entirely and
emits it as an indented code block whose first body line is the raw
`[...]`. Verified on pandoc 3.8 (the CI pin).

The discriminator is precise: a value that is a **single** brace group
parses fine (`caption={My cap}`, `label={lst:x}`, `morekeywords={a,b}` all
convert cleanly). Only the multi-adjacent-group shape breaks it. A
non-brace delimiter form (`escapeinside=||`) also parses fine — it's the
braces specifically.

## Fix

A pre-pandoc pass, [`_apply_lstlisting_options.py`](../scripts/_apply_lstlisting_options.py),
runs a brace-/bracket-aware scan to find the true end of each
`\begin{lstlisting}[...]` group (the balancing pandoc gets wrong), splits
the options on top-level commas, and drops any option whose value's head
is two or more adjacent brace groups. Those options (`escapeinside`,
`literate`, `moredelim` …) are PDF-rendering directives with no MyST
equivalent, so removing them is loss-free — the post-pandoc
`convert_pandoc_attr_code_blocks` pass keeps `caption`/`label`/`language`
and ignores the rest anyway. Single-brace values are preserved; an
unbalanced group is left untouched (conservative bail).

Wired into `preprocess.sh` right after `_apply_pifont_glyphs.py` and into
`tests/test_golden_tex.py::_MARKER_SCRIPTS`. Golden:
`lstlisting_escapeinside`; unit tests in `test_preprocessors.py`.

## How to detect

```bash
# The signature: a bracketed option group as the first line of a code block.
grep -rnE '^\[(language|basicstyle|escapeinside|numbers)=' mystmd/*.md   # zero after fix
```

## Scope / known gap

Detection anchors on the value *head* (`key={…}{…}`), which covers the two
real-world culprits (`escapeinside`, `literate`). A `moredelim` whose
adjacent brace groups sit *after* a leading `[...]` bracket
(`moredelim=**[is][\color{red}]{`}{`}`) still leaks and is **not** handled —
no book has hit it yet. Per the graduation rule, it stays out until a
second book needs it; generalising detection to "adjacent brace groups
anywhere in the value" would handle it but widens the false-positive
surface.

## Generalizable rule

When pandoc silently mangles a LaTeX construct's *options* (not its body),
the fix belongs **pre-pandoc**: strip or normalise the offending option
into a form pandoc parses, rather than trying to un-mangle the post-pandoc
output. A brace-/bracket-aware scan — never a flat regex — is what locates
the real option-group boundary, because the whole failure is that pandoc's
own boundary detection is what broke. Same family as the marker
preprocessors (algorithms, listings, figures, tables), which extract
pandoc-hostile *structure* before it reaches the reader.

Related: lesson [034](034-pandoc-attr-fenced-code-blocks-need-myst-directive-conversion.md)
(the post-pandoc `lstlisting` → `{code-block}` conversion this feeds), and the
marker-boundary rule in `transforms/_markers.py` (bail conservatively on
shapes you can't fully model).
