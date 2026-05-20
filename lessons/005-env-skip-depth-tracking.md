---
id: 005
title: "Skipping unsupported nested divs needs depth tracking"
category: post-processing
tags: [pandoc, divs, nesting]
source_project: book-dp2
status: codified
codified_in: postprocess.py::convert_environment_divs
severity: medium
date: 2026-05-10
---

## Symptom

Stray `minipage` content appearing in `ch_transforms.md` output, even though
the `minipage` environment was in the `ENV_SKIP` set.

## Cause

The naive skip loop scans forward to the first `:::` closer. When pandoc
emits nested divs — for example a `::::: center` block containing two
`:::: minipage` blocks — the inner `::::` closer pre-terminates the skip
loop, leaving inner content stranded in the output.

```
::::: center           ← we choose to skip this
::::  minipage         ← stops here on first :::: (wrong)
content X
::::                   ← never reached
::::  minipage
content Y
::::
:::::                  ← never reached
```

## Fix

Track depth explicitly. Increment on each opening `:{3,} <name>` line,
decrement on each bare `:{3,}` line, exit when depth returns to zero.

```python
depth = 1
while i < len(lines) and depth > 0:
    line = lines[i]
    if re.match(r'^:{3,}\s+\w+', line):
        depth += 1
    elif re.match(r'^:{3,}\s*$', line):
        depth -= 1
    i += 1
```

## How to detect

```bash
# After conversion, grep for leftover environment names that should have been skipped
grep -nE '^(center|minipage|multicols)' mystmd/*.md
```

Any match means the skip logic isn't depth-aware.
