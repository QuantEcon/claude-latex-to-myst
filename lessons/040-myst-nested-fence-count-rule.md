---
id: 040
title: "Nested fences resolve by same-character count (k+1) — directive emitters must outrank any code fence in their body"
category: myst
tags: [myst, commonmark, fenced-blocks, directives, code-block, backticks, colon-fence, nesting]
source_project: book-dp-deep-learning (#69 / #78 follow-on)
status: codified
codified_in: scripts/transforms/envs.py::_outer_fence (resolve_exercise_markers); generalisation tracked in #79
severity: medium
date: 2026-05-28
---

## Symptom

A MyST directive emitted with a fixed three-backtick fence renders only
up to the *first* fenced code block in its body; everything after that
block leaks out as raw markdown (the directive looks "half-rendered").
E.g. an `{exercise}` containing a ```` ```python ```` solution sketch:
the inner ``` closes the exercise early.

## Cause

CommonMark/MyST resolve nested fences purely by **count, among fences of
the same character**:

- A fenced block opens with ≥3 identical fence chars (`` ` `` *or* `~`)
  and closes at the next line with ≥ that many of the **same** char.
- To nest, the outer fence must be **strictly longer** than the deepest
  same-character fence inside it (the "k+1" rule: longest inner run + 1).
- Backticks, tildes, and MyST's colon (`:::`) directive fences are
  **independent** — each only has to outrank nested fences of its own
  type. A `~~~` block or a `:::{note}` inside a ```` ``` ````-fenced
  directive never collides; only a backtick fence does.

So a backtick-fenced directive whose body contains a backtick code block
(both default to 3) collides; a colon-fenced directive, or a body using
only tilde/colon fences, does not.

## Fix

Compute the directive fence from its content rather than hardcoding three
backticks. `scripts/transforms/envs.py::_outer_fence` scans the body for
the longest backtick run at a line start and returns one tick longer
(min three):

```python
_FENCE_LINE_RE = re.compile(r'[ \t]*(`{3,})')

def _outer_fence(content: str) -> str:
    inner = max((len(m.group(1)) for line in content.splitlines()
                 if (m := _FENCE_LINE_RE.match(line))), default=0)
    return '`' * max(3, inner + 1)
```

It composes bottom-up — `code(3) ⊂ note(4) ⊂ exercise(5)` — provided the
body's fence counts are final before the outer emitter runs (true for
`resolve_exercise_markers`, whose body is already-final pandoc markdown).
Tildes are deliberately *not* scanned: they can't close a backtick fence.

Currently wired into `resolve_exercise_markers` only (PR #78). Every
other backtick-directive emitter (`convert_environment_divs` for
`\begin{Exercise}`/`{solution}`/`{prf:*}`, `{prf:algorithm}`, `{figure}`,
`{list-table}`) still hardcodes three ticks — generalising `_outer_fence`
to all of them is tracked in **#79**.

## Why not colon-fence the prose directives instead

The doc-endorsed alternative is to emit prose directives as `:::` colon
fences, which never collide with backtick code blocks. Rejected for this
project: the lecture house style uses backtick exercise blocks that widen
to four ticks, and colon fences fail to render on non-MyST previews
(e.g. Positron). Recorded so it isn't reopened.

## How to detect

A directive renders truncated at its first code block. Mechanically, scan
emitted markdown for a directive opener whose fence length is ≤ a fence
length appearing before its matching closer:

```bash
# directives that open with exactly ``` yet contain a ``` code block
awk '/^```\{/{d=1} d&&/^```[a-z]/{print FILENAME": "NR": nested fence in 3-tick directive"} /^```$/{d=0}' mystmd/*.md
```

## Generalizable rule

Any emitter that wraps arbitrary converted content in a same-character
fence must size the fence to the content, never hardcode it — the same
"size the delimiter to the payload" discipline as the depth-aware scans
in [029] and [039]. When the wrapper and a legal child use the same fence
character, count is the only thing keeping their scopes apart.
