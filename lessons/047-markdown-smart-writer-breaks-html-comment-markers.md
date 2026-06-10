---
id: 047
title: "pandoc's smart writer is load-bearing for HTML-comment markers — the LaTeX reader ligatures the `--` in `<!--MARKER-->` to en-dashes, and only the writer's re-encoding restores the delimiters"
category: pandoc
tags: [markers, smart, dashes, ligatures, en-dash, em-dash]
source_project: claude-latex-to-myst (issue #1)
status: codified
codified_in: scripts/transforms/typography.py::convert_latex_dashes
severity: high
date: 2026-06-11
---

## Symptom

Implementing the `--`/`---` → en/em-dash conversion (issue #1), the
obvious zero-cost fix was disabling the markdown writer's `smart`
extension: `pandoc -f latex -t markdown-smart`. The LaTeX reader already
converts the dash ligatures context-correctly (math, verbatim, and
`\texttt` stay untouched), and with the smart writer disabled the
Unicode dashes write straight through. A two-line change.

Running the test suite: **21 failures.** Every marker construct broke —
figure markers, table markers, exercise markers, the batch `<!--CELL_N-->`
cells. The output contained mangled markers like:

```
\<!–FIGURE payload=eyJuYW1lIjog...–\>
```

The decoder regexes (`<!--FIGURE payload=...-->`) never match again, so
whole figures/tables/exercises vanish into undecodable comment soup.

## Cause

The marker architecture passes `<!--MARKER ...-->` HTML comments through
pandoc as plain text. Pandoc's **LaTeX reader applies TeX ligatures to
that text too**: the `--` inside `<!--` and `-->` becomes an en-dash
(`–`) in the AST. The pipeline has only ever worked because the markdown
**writer's `smart` extension (on by default) re-encodes en-dashes back
to `--`** on output — accidentally round-tripping the marker delimiters
to their original bytes.

So `smart` on the writer is not a cosmetic setting here; it is a
load-bearing part of the marker round-trip. Any change that stops the
writer re-encoding dashes (e.g. `-t markdown-smart`) corrupts every
HTML-comment marker in the pipeline.

## Fix

Dash conversion happens **post-pandoc**, prose-only:
`convert_latex_dashes` in `scripts/transforms/typography.py`, running
late in `process_text` (after every marker decoder, so no marker comment
remains to corrupt). It uses the lesson-040 fence-stack scan, skips
`{math}`/code directives, indented code blocks, structural dash lines
(frontmatter `---`, table rules), directive options, and protects inline
code, `$…$` math, HTML comments, autolinks, link targets, and bare URLs
per line.

## How to detect

If a writer-flag change is ever attempted again, the failure is loud:

```bash
uv run pytest tests/test_figure_markers.py tests/test_marker_differential.py -q
```

Or grep any converted output for a mangled delimiter:

```bash
grep -rn '<!–\|–>' output/*.md
```
