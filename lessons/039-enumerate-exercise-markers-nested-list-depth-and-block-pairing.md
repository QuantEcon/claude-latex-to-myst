---
id: 039
title: "Enumerate-exercise preprocessor: flat \\item scan AND non-greedy block regex both break on nested lists inside an exercise"
category: preprocess
tags: [pandoc, enumerate, exercise, itemize, nesting, depth-tracking, block-pairing, regex-safety]
source_project: book-dp-deep-learning (R7), follow-on to #69
status: codified
codified_in: scripts/_apply_enumerate_markers.py::parse_enum_items, scripts/_apply_enumerate_markers.py::_iter_top_level_enumerates
severity: high
date: 2026-05-28
---

## Symptom

`_apply_enumerate_markers.py` (the #69 fix that turns
`\begin{enumerate}\item\label{ex:...}` lists into `{exercise}`
directives) emitted **zero** EXERCISE markers for any exercise whose
statement nested a sub-list — e.g. a multi-part exercise:

```latex
\begin{enumerate}
\item\label{ex:ch1:1} Consider the following cases:
  \begin{itemize}
  \item first sub-point
  \item second sub-point
  \end{itemize}
\item\label{ex:ch1:2} A simpler exercise.
\end{enumerate}
```

The whole block fell through to pandoc unchanged, so the top-level
`ex:` labels were dropped and any `{prf:ref}` back-link dangled — i.e.
the original #69 bug persisted, undetected, for the single most common
textbook exercise shape (a stem with bulleted or `(a)/(b)` sub-parts).

## Cause

Two independent layers, both nesting-blind:

1. **Item split (the same bug as [029]).** `parse_enum_items` found
   item boundaries with a flat `re.finditer(r'\\item\b', body)`. That
   returns *every* `\item`, including the unlabelled ones inside a
   nested `itemize`/`enumerate`. Those nested items have no
   `\label{ex:...}`, so the "every item is `ex:`-labelled" guard failed
   and the function returned `None`, disqualifying the block.

2. **Block pairing (new, specific to enumerate).** Even with the item
   split fixed, `process_text` matched the outer block with a single
   non-greedy regex:

   ```python
   re.compile(r'\\begin\{enumerate\}(?:\[[^\]]*\])?(.*?)\\end\{enumerate\}', re.DOTALL)
   ```

   When a sub-part list is itself an `enumerate` (`(a)/(b)` is usually
   written as a nested `enumerate`), the `.*?` stops at the **inner**
   `\end{enumerate}`, so the captured body is truncated and the wrapper
   pairing is wrong. A non-greedy regex cannot balance same-named
   nested delimiters — only depth counting can.

Layer 2 is why this lesson is distinct from [029]: the description
preprocessor never hit it because a `\begin{description}` body almost
never nests another `description`, so its non-greedy
`\begin{description}…\end{description}` regex was good enough. Exercise
lists nest the *same* `enumerate` env routinely, so block pairing has
to balance.

## Fix

**Layer 1** — depth-aware item split (mirrors
[`_apply_description_markers._split_items`](../scripts/_apply_description_markers.py)):
walk a sorted `open`/`close`/`item` event stream and treat only depth-0
`\item` as exercise boundaries. Nested-list items ride along inside
their parent exercise's content.

**Layer 2** — depth-balanced block finder
`_iter_top_level_enumerates` replaces the non-greedy regex. It pairs
`\begin{enumerate}` / `\end{enumerate}` by depth counting and yields
only the **outermost** blocks:

```python
def _iter_top_level_enumerates(text):
    events = sorted(
        [(m.start(), m.end(), 'open')  for m in _ENUM_OPEN_RE.finditer(text)]
        + [(m.start(), m.end(), 'close') for m in _ENUM_CLOSE_RE.finditer(text)]
    )
    depth = 0
    block_start = body_start = None
    for start, end, kind in events:
        if kind == 'open':
            if depth == 0:
                block_start, body_start = start, end
            depth += 1
        else:
            if depth == 0:
                continue            # stray \end — ignore, don't crash
            depth -= 1
            if depth == 0:
                yield (block_start, body_start, start, end)
```

`process_text` walks these spans and rebuilds the string, leaving
skipped (mixed / commented) blocks verbatim.

Tests in [tests/test_preprocessors.py](../tests/test_preprocessors.py):
`test_enum_marker_preserves_nested_itemize_in_exercise`,
`test_enum_marker_preserves_nested_enumerate_subparts`,
`test_enum_parse_ignores_nested_item_boundaries`. Round-trips through
pandoc to a clean `{exercise}` directive with the nested list intact.

## How to detect

A `.tex` source has fully-`ex:`-labelled exercises but the converted
`.md` has no `{exercise}` directives (or fewer than the label count):

```bash
# labels in source vs. exercise directives produced
grep -c '\\item\\label{ex:' chapter.tex
grep -c '^```{exercise}'    mystmd/chapter.md
```

A shortfall means a block was skipped — most likely a nested-list
exercise hitting one of the two layers above.

## Generalizable rule

Reinforces [029]: **preprocess scans that walk LaTeX bodies must be
nesting-aware** — flat `finditer` is the wrong default whenever the
matched token can appear inside a same-family env. This lesson adds a
second axis: **when the env being extracted can nest *itself*, the
block-delimiter match must also balance by depth, not lean on a
non-greedy `.*?`.** Item-splitting and block-pairing are two separate
places nesting bites; fixing one without the other only half-solves it.
See also [025] (bound-scan), [024] (DOTALL spanning paragraphs).
