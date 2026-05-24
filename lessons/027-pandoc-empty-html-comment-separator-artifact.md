---
id: 027
title: "Pandoc inserts empty `<!-- -->`{=html} between adjacent inline tokens to defeat CommonMark; MyST doesn't need it"
category: pandoc
tags: [pandoc, html, inline-math, artifacts, postprocess]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::strip_pandoc_html_separators
severity: low
date: 2026-05-24
---

## Symptom

Rendered HTML in MyST output contained raw fragments like:

```
($\sim$`<!-- -->`{=html}30 s, sanity check)
($\times$`<!-- -->`{=html}9 collocation points)
```

The literal text `` `<!-- -->`{=html} `` showed up between an inline
`$math$` and an adjacent digit. 14 occurrences across 6 chapter files
in the book that surfaced this. Looked like a markdown-quoting bug,
but the source `.tex` was clean — the artifact came from pandoc.

## Cause

Pandoc's CommonMark output is constrained by the lexer's
greedy-merging rules: `$\sim$30` would tokenise as the literal text
`$\sim$30` (the `30` adjacent to the closing `$` defeats math
recognition in some downstream renderers). Pandoc defeats this by
inserting an *empty* raw-HTML span between the two tokens:

```
$\sim$`<!-- -->`{=html}30 s
```

The `` `<!-- -->`{=html} `` is pandoc's raw-attribute syntax: an empty
HTML comment annotated with `{=html}` to mark it as raw HTML rather
than literal markdown. The CommonMark lexer treats the inline raw
span as a token boundary, so `$\sim$` stays a math span and `30`
stays text — solving pandoc's problem.

MyST's tokeniser has stricter math recognition than CommonMark and
doesn't need the separator: `$\sim$30` parses correctly without it.
So the artifact has no purpose in the MyST pipeline — it just
survives into the rendered HTML as raw text.

## Fix

A single regex substitution as the first step of `process_file`:

```python
def strip_pandoc_html_separators(text: str) -> str:
    return re.sub(r'`<!-- -->`\{=html\}', '', text)
```

Runs as the very first postprocess step so downstream transforms see
clean tokens.

Safety:

- The pattern is pandoc-specific syntax — Markdown authors don't
  write `` `<!-- -->`{=html} `` by hand.
- A genuine HTML comment carries content (`<!-- TODO: foo -->`); the
  empty-comment-with-`{=html}`-attribute shape is unambiguous.
- Removing the separator collapses the surrounding tokens back
  together as MyST expects (`$\sim$30 s`).

Tests in [tests/test_transforms.py](../tests/test_transforms.py):
`test_strip_pandoc_html_separators_inline_math_followed_by_digit`,
`test_strip_pandoc_html_separators_multiple_occurrences`,
`test_strip_pandoc_html_separators_does_not_touch_real_html_comments`.

## How to detect

```bash
grep -n '`<!-- -->`{=html}' mystmd/*.md
```

Should be zero in any chapter after a fresh pipeline run. A non-zero
count means a chapter slipped past `process_file` (or the strip is
running in the wrong order).

## Generalizable rule

**Pandoc emits a small set of CommonMark lexer-defeat tokens that
have no semantic content in stricter Markdown flavours.** These are
candidates for unconditional stripping in any pipeline targeting
MyST or another stricter renderer:

- `` `<!-- -->`{=html} `` — empty raw-HTML separator (this lesson).
- Trailing `\` line-continuation in some `--wrap=preserve` outputs.
- `&nbsp;` inserted to defeat heading-only-line rules.

When a pipeline targets a known-stricter renderer downstream, the
default postprocess should include strips for every pandoc
lexer-defeat artifact that has been observed. The cost of an
unconditional strip is one regex; the cost of letting the artifact
survive into HTML is a confusing rendering bug that the user
discovers during visual review.
