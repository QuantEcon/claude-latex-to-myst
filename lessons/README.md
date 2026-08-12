# Lessons

A growing catalogue of pitfalls hit while converting LaTeX to MyST. Each
lesson is its own file with YAML frontmatter, so they can be grepped,
filtered, and individually linked from code comments.

## Adding a lesson

The easy way: run `/capture-lesson` inside Claude Code from this repo.

The manual way: create `lessons/NNN-short-slug.md` with the frontmatter
below, then add a one-line entry to `../LESSONS.md`.

## Frontmatter schema

```yaml
---
id: 016                       # zero-padded, sequential, never reused
title: "One-line summary"
category: post-processing     # see categories below
tags: [katex, equations, regex]
source_project: book-dp2      # which project surfaced this
status: codified              # open | codified | superseded (see below)
codified_in: postprocess.py::convert_equations    # only if status=codified
severity: high                # low | medium | high — by impact when missed
date: 2026-04-09              # ISO date discovered
---
```

## Categories

| Category          | Scope |
|-------------------|-------|
| `preprocess`      | LaTeX-side sanitization (before pandoc) |
| `pandoc`          | Quirks of pandoc's LaTeX→markdown output |
| `post-processing` | Transforms applied to pandoc's markdown |
| `myst`            | MyST/sphinx-proof directive requirements |
| `katex`           | KaTeX strictness vs LaTeX |
| `regex-safety`    | Regex patterns that bit us |
| `validation`      | Things to check before declaring conversion done |
| `tooling`         | Workflow, CI, build, deployment |

## Body structure

Each lesson should have these sections:

```markdown
## Symptom
What the user observes — broken output, build error, missing content.

## Cause
Why it happens — the underlying mechanism.

## Fix
What to do about it. If `status: codified`, name the function/file that
handles it. If `status: open`, describe the manual workaround.

## How to detect
A regex, grep, or test that surfaces the issue. Optional but valuable.
```

## Lifecycle

- New lessons start as `status: open`.
- When a lesson is fixed in the pipeline, change to `status: codified` and
  fill `codified_in:` with the function or file that handles it.
- Never delete a lesson. If something turns out to be wrong, mark
  `status: superseded` and link to the replacement.
