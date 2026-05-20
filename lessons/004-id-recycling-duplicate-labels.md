---
id: 004
title: "Never use id(list) to auto-generate labels — Python recycles addresses"
category: post-processing
tags: [labels, duplicate-ids, python-gotcha]
source_project: book-dp2
status: codified
codified_in: postprocess.py::convert_environment_divs
severity: medium
date: 2026-04-09
---

## Symptom

118 `duplicate_id` errors in `myst build` output. Many exercises and theorems
share identical auto-generated labels.

## Cause

Initial implementation generated fallback labels with `f"ex-{id(body_lines)}"`
when the source had no explicit `\label`. CPython recycles memory addresses
for freed list objects, so multiple exercises processed in sequence routinely
ended up with the same `id()`.

This is a fundamental Python gotcha: **`id()` is unique only among
simultaneously-live objects.** Object lifetimes during a regex pipeline are
short; collisions are common.

## Fix

Use a deterministic per-file sequential counter combined with a chapter
prefix derived from the input filename:

```python
_exercise_counter = 0
_chapter_prefix = ''   # set by process_file from input_path.stem

def _next_exercise_label():
    global _exercise_counter
    _exercise_counter += 1
    return f'ex-{_chapter_prefix}-{_exercise_counter}'
```

Reset both at the start of every `process_file` call.

## How to detect

```bash
myst build --html 2>&1 | grep duplicate_id | wc -l
```

If this is non-zero after conversion, something is generating non-unique
labels. The culprit is almost always auto-generation.
