---
id: 029
title: "_apply_description_markers consumed \\item markers inside nested itemize/enumerate, cascading into dropped figures"
category: preprocess
tags: [pandoc, description, itemize, enumerate, nesting, depth-tracking, figure-drop]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/_apply_description_markers.py
severity: high
date: 2026-05-24
---

## Symptom

A description body containing a nested itemize/enumerate ended up
broken in the converted markdown — the nested list emitted as
`% Unknown environment: itemize` plus orphan paragraphs — and **every
`{figure}` directive that followed in the same chapter was silently
dropped at MyST build time** (6 of 11 figures in ch02 of the
Deep-Learning book).

The downstream artefact was figure drops; the actual corruption was
several hundred lines earlier in the preprocessed `.tex`.

## Cause

`scripts/_apply_description_markers.py` rewrites
`\begin{description}…\end{description}` blocks into HTML-comment
marker form so pandoc preserves the `\item[Term]` labels (which it
would otherwise drop, GH #19). The original `_split_items` used a
flat regex scan:

```python
matches = list(_ITEM_RE.finditer(body))
```

`finditer` returned **every** `\item` in the body, regardless of
nesting depth. When the body contained a nested
`\begin{itemize}…\end{itemize}` (a standard LaTeX pattern), the inner
`\item` lines were also treated as description items and got
replaced with `<!--DESCITEM term=-->` markers, leaving the nested
itemize with zero items.

Pandoc then encountered `\begin{itemize}` immediately followed by
plain text (no `\item`), failed to recognise it as a list, emitted
`% Unknown environment: itemize`, and dropped the marker. The
malformed `::: itemize` fenced div that pandoc produced as fallback
corrupted block structure for the rest of the chapter; MyST's parser
silently dropped subsequent `{figure}` directives.

## Fix

Walk the body as a sorted timeline of `open`/`close`/`item` events
and only emit a description item when the current nest depth is 0.
Inner `\item` markers pass through verbatim for pandoc to handle in
their natural list context. Implementation in
[scripts/_apply_description_markers.py](../scripts/_apply_description_markers.py):

```python
_NEST_OPEN = re.compile(r'\\begin\{(?:itemize|enumerate|description)\}')
_NEST_CLOSE = re.compile(r'\\end\{(?:itemize|enumerate|description)\}')

def _split_items(body):
    events = []
    for m in _NEST_OPEN.finditer(body):  events.append((m.start(), 'open', m))
    for m in _NEST_CLOSE.finditer(body): events.append((m.start(), 'close', m))
    for m in _ITEM_RE.finditer(body):    events.append((m.start(), 'item', m))
    events.sort(key=lambda e: e[0])
    # … emit only when depth == 0
```

Tests in [tests/test_preprocessors.py](../tests/test_preprocessors.py):
`test_description_marker_preserves_nested_itemize`,
`test_description_marker_preserves_nested_enumerate`.

## How to detect

The corruption is visible in the preprocessed `.tex` (under
`mystmd/tmp/`) — search for `\begin{itemize}` lines that are *not*
followed by any `\item` line before the matching `\end{itemize}`.
Any such block will produce a `% Unknown environment` artefact and
likely drop downstream figures.

Easy check in any consuming book repo after a pipeline run:

```bash
grep -n '% Unknown environment' mystmd/*.md
```

A clean build should have zero hits.

## Generalizable rule

**Preprocess regexes that walk LaTeX bodies must be nesting-aware.**
Flat `finditer` is the wrong default whenever the marker being
matched (`\item`, `\label`, `\caption`, …) can legally appear inside
a different environment of the same family. The bound-scan fix in
lesson [025] (multiline-table forward scan) is the same shape; so is
[024] (orphan-label DOTALL regex spanning paragraphs).

When in doubt, structure the scan as a depth-tracked event stream
rather than as a flat match list. The cost is ~20 lines; the
upside is that the transform stops silently corrupting nested cases.

## Why MyST drops the figures (cascade mechanism)

The pandoc fallback for an unknown environment is to emit it as a
fenced div: `::: itemize\n…body…\n:::`. That fenced div is
syntactically valid markdown but its contents (orphan paragraphs
where `\item` lines used to be) break the block-context invariants
MyST's parser relies on to attach captions and labels to following
`{figure}` directives. The figures themselves survive into the
`.md` but MyST's rendering pass drops them as unattachable.

This explains why the visible symptom (missing figures) is several
sections after the actual corruption: the cascade affects everything
downstream of the malformed fenced div, not just adjacent content.
