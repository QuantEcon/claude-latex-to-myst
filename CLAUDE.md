# CLAUDE.md

Instructions for Claude when working in `claude-latex-to-myst` or in a book
repo that uses this pipeline.

## What this repo is

A reusable LaTeX → MyST Markdown conversion pipeline. The hard work has been
done — see `scripts/postprocess.py`, `scripts/preprocess.sh`, `scripts/convert.sh`.
**Do not re-derive these from scratch.** Adapt them via `config.yaml`.

## How to approach a new book conversion

1. **Read [`lessons/`](lessons/) first.** Every lesson there is a pitfall
   someone has already hit. Grep the lessons before writing new transforms.
2. **Edit `config.yaml`, not the scripts.** Chapter list, bib filename,
   custom-macro pre-rewrites, and the TikZ map are all configurable. If you
   find yourself editing `postprocess.py` for project-specific reasons, that
   reason probably belongs in config.
3. **Run the pipeline; categorize errors; fix the largest category.** See
   the "Iterative Error Reduction" section in the original PROMPT. One regex
   fix can eliminate dozens of errors.
4. **Capture new lessons.** When you hit a non-obvious bug, run
   `/capture-lesson` to add it to the catalogue. Future-you (or future-Claude)
   will thank you.

## Genuinely generic vs project-specific

| Generic (rarely edited) | Project-specific (in config or overrides) |
|-------------------------|-------------------------------------------|
| `ENV_MAP` defaults (theorem, lemma, etc.) | Chapter list & filenames |
| All 13 transform functions | `CHAPTER_TITLES` (frontmatter titles) |
| KaTeX compatibility fixes | Bibliography filename |
| Cross-ref / citation / figure regex | Custom-macro pre-rewrites (e.g., `\navy` → `\textbf`) |
| Blank-line-in-math handling | `TIKZ_FIGURE_MAP` (TikZ label → SVG path) |
| Pipeline ordering | `TIKZCD_INLINE_MAP` (inline tikzcd matches) |

If a transform feels too book-specific, it probably belongs in a project
overrides file, not in `postprocess.py`.

## When to capture a lesson vs. fix the pipeline

- **Capture as lesson + leave pipeline alone:** rare edge case, project-specific
  workaround, KaTeX/MyST behavior worth documenting but not worth automating.
- **Capture as lesson + codify in pipeline:** affects ≥2 projects, mechanically
  fixable, would be missed if not automated. Mark the lesson `status: codified`
  and reference the fix location.
- **The bar for codifying:** "would someone hit this on the next book?" If yes,
  fix it in the pipeline now; the cost of the regex is far less than the cost
  of re-debugging it in 6 months.

## Don't

- Don't rewrite `postprocess.py` from scratch. Read it, adapt it.
- Don't add LLM calls to the pipeline — it must be deterministic and re-runnable.
- Don't commit `mystmd/tmp/` or `_build/` from any consuming book repo.
- Don't promote a lesson from `open` to `codified` without actually adding the
  fix to the pipeline and verifying.
