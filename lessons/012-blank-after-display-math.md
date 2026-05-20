---
id: 012
title: "Insert blank line after closing $$ for readability"
category: post-processing
tags: [equations, formatting, source-readability]
source_project: book-dp1 (parity test)
status: codified
codified_in: postprocess.py::ensure_blank_after_display_math
severity: low
date: 2026-05-20
---

## Symptom

Pandoc emits display math directly attached to the following prose:

```markdown
$$
\sum_{i=1}^n x_i
$$
Next sentence starts here.
```

This is valid CommonMark and renders fine, but the source is hard to read
and some renderers attach the next paragraph too tightly visually.

## Cause

Pandoc doesn't insert a paragraph break after `\end{equation}`. The
markdown is correct but ugly.

## Fix

`ensure_blank_after_display_math` walks the document, tracks whether we're
inside a `$$` block, and inserts a blank line after the closing delimiter
when the next line is non-empty.

```python
is_dm_delim = (
    stripped == '$$'
    or stripped.startswith('$$ ')        # closing with " (eq-label)"
    or stripped.startswith('$$(')        # closing with "(eq-label)" no space
)
if is_dm_delim:
    was_open = in_math_block
    in_math_block = not in_math_block
    out.append(line)
    if was_open and i + 1 < len(lines) and lines[i + 1].strip() != '':
        out.append('')
```

**Pipeline order matters:** run this *before* `cleanup_typography` so the
trailing `\n{4,}` cap collapses any over-additions. Running it after the
cleanup pass means blank lines accumulate unbounded.

## Caveat

This is a *cosmetic* transform that adds blank lines. Re-running the
pipeline after adding it will produce diffs from previously-committed
output — pure `+ \n` additions, no semantic change. Acceptable but worth
flagging when integrating into an existing book conversion.
