---
id: 036
title: "Pandoc-attr fence regex stops at the first ``}`` inside a quoted caption value"
category: regex-safety
tags: [pandoc, lstlisting, code-block, regex, caption, regression]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_pandoc_attr_code_blocks
severity: medium
date: 2026-05-26
---

## Symptom

Direct regression from lesson 034 / [#31]. The new
``convert_pandoc_attr_code_blocks`` transform didn't fire when the
lstlisting caption contained a literal ``}`` — e.g.
``\texttt{Pi}`` or ``\texttt{02_Brock.ipynb}``. The pandoc-attr
fenced block then survived into MyST unconverted, rendering as
anchorless code, and ``\ref{lst:X}`` resolved to nothing.

Verified in the downstream book: ``lst:autodiff_euler`` was still
broken after #31 closed because its caption contained two
``\texttt{...}`` macros.

## Cause

The original attribute group was ``[^}\n]+`` — any char except a
literal ``}`` or newline. The first ``}`` from ``\texttt{Pi}`` ended
the group; the remainder of the attribute string then didn't match
``\}[ \t]*\n``; the whole regex failed to match; the block passed
through.

LaTeX captions routinely embed brace-bearing macros: ``\texttt``,
``\textbf``, ``\mathbb``, ``\frac``, citations, the lot. Any of them
inside a ``caption="..."`` value will hit this.

## Fix

The attribute string is structured: ``key="value"`` pairs where the
value is double-quoted. Brace chars inside ``"..."`` are part of the
value; brace chars outside the quotes are structural (one closing
``}`` terminates the attribute block).

Encode that distinction directly in the regex:

```python
fence_re = re.compile(
    r'^```[ \t]+\{'
    r'(?P<attrs>(?:[^}"\n]|"(?:[^"\\]|\\.)*")+)'
    r'\}[ \t]*\n'
    r'(?P<body>.*?)'
    r'^```\s*$',
    re.DOTALL | re.MULTILINE,
)
```

The attribute group now alternates between:

- ``[^}"\n]`` — any char other than ``}``, ``"``, or newline (the
  unquoted parts: ``#id``, ``.class``, ``key=``, whitespace), or
- ``"(?:[^"\\]|\\.)*"`` — a complete double-quoted string, where
  ``}`` is fine because we're inside the quotes; the inner pattern
  also accepts ``\\`` escape sequences so an escaped quote inside the
  value doesn't terminate the quoted span prematurely.

The closing ``}`` is matched outside the alternation, so it still
unambiguously terminates the attribute block.

Tests in `tests/test_transforms.py`:
`test_pandoc_attr_code_block_caption_with_braces_in_value`,
`test_pandoc_attr_code_block_multiple_braced_macros_in_caption`.

## Why this missed the #31 review

The #31 review traced the regex against pandoc's typical output
shape:

```
``` {#lst:demo .python caption="Demo" label="lst:demo"}
```

— a caption with plain-ASCII text. The brace-in-value case wasn't
in the test set, and the regex looked simple enough to take at face
value. The downstream book's caption with two ``\texttt{...}``
macros surfaced the gap immediately on validation.

## Generalizable rule

**Any regex that delimits a structured field with a single char must
know whether that char can appear inside the field.** ``}`` is a
delimiter at the LaTeX/pandoc-attribute level *and* a delimiter
inside LaTeX text. The two scopes nest. The minimal-effort regex
``[^}\n]+`` treats both as identical and silently fails on the
nested case. The robust form is "any char except the delimiter,
OR a complete quoted run" — the same shape used for any
quote-aware tokeniser (CSV, JSON-ish, shell-ish). Pandoc keeps
attribute values consistently double-quoted, so this is exact
rather than heuristic.

The same shape applies wherever pandoc emits a quoted attribute
value with delimiter-bearing content: ``caption=``, ``title=``,
``alt=``. If a new transform introduces an attribute-group regex,
default to the quote-aware form from day one.
