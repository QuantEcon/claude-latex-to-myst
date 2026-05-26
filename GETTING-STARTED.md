# Getting started

How to use `claude-latex-to-myst` to convert a LaTeX book to MyST Markdown — in collaboration with [Claude Code](https://claude.com/claude-code).

This guide assumes you have:

- A LaTeX source tree for an academic book (chapters in separate `.tex` files, or a single file split by `\chapter{}`).
- [Claude Code](https://claude.com/claude-code) installed and configured.
- The mechanical prerequisites installed: `pandoc` ≥ 3.0, [`uv`](https://docs.astral.sh/uv/), and `mystmd` (`npm install -g mystmd`). See [README](README.md#requirements) for details.

If you just want the mechanical "how do I run the script" answer, see the [README](README.md#quick-start). This guide is about **what to ask Claude to do** and **how to work with it iteratively** to get a clean conversion.

## The collaboration model

This pipeline is built to be **driven by Claude Code**, not hand-edited. The transforms are deterministic — same `.tex` in, same `.md` out — so Claude can re-run the pipeline freely without ever losing your work.

| You do | Claude does |
|---|---|
| Provide the book source and high-level guidance | Scaffold `mystmd/`, fill in `config.yaml`, run the pipeline |
| Review rendered output, flag what looks wrong | Categorize errors, fix the largest category first |
| Decide what's good enough to ship | Capture lessons, propose pipeline upgrades |
| Approve risky/visible actions (commits, PRs, releases) | Stay inside its lane until told otherwise |

The tool ships with a [`CLAUDE.md`](CLAUDE.md) that teaches Claude how the pipeline is organized, where to add transforms, when to capture lessons, and which architectural decisions not to re-litigate. You don't need to feed Claude this context — it loads automatically when you start a session in this repo or any book repo that has its own `CLAUDE.md` pointing at the pipeline.

## Your first conversion

In your **book's** repo (not this repo), start a Claude Code session and try something like:

> "I want to convert this LaTeX book to MyST Markdown using the claude-latex-to-myst pipeline. Can you help me bootstrap `mystmd/` and run the first conversion?"

Claude will typically:

1. **Survey the source.** Look at `*.tex` to find chapters, the bib file, custom macros, TikZ figures.
2. **Bootstrap `mystmd/`.** Either using [`new-book.sh`](scripts/new-book.sh) from the tool, or by hand if your layout is non-standard. This produces `mystmd/config.yaml`, `mystmd/convert.sh`, `mystmd/.tool-version`, and a chapter list.
3. **Fill in the config.** Chapter titles, bib filename, custom-macro rewrites, TikZ overrides — Claude reads these out of your `.tex` and proposes values; you review and confirm.
4. **Run the pipeline.** `bash mystmd/convert.sh` — preprocess → pandoc → postprocess → validate.
5. **Build and survey.** `cd mystmd && myst build --html`, then summarize the warnings.

At this point you have an imperfect but readable conversion. **Don't try to fix it line-by-line yourself yet** — see the next section.

## The iterative loop

The first pipeline run on a new book typically produces hundreds of MyST build warnings. The fast path to a clean build is **category-first**, not error-by-error.

Ask Claude:

> "Run the pipeline, build the output, and categorize the warnings. Tell me the top 3 categories by count, and propose a fix for the largest one."

Claude will:

1. Re-run the pipeline.
2. Build with `myst build --html`.
3. Group warnings (typically by `duplicate_id`, `xref_not_found`, `math_parse`, `directive_unknown`, …).
4. Identify the highest-count category and propose either a **config rewrite** (in your book's `mystmd/config.yaml`, for book-specific shapes) or a **pipeline transform** (in the tool's `scripts/postprocess.py`, for shapes that will recur in other books).
5. Implement, re-run, recount.

One regex fix usually eliminates 50–200 build errors. Repeat until the remaining errors are genuinely per-file edge cases — at that point, hand-fixing the markdown directly is appropriate (but ask Claude to do it; it can review the diff for collateral damage).

## What to ask Claude vs. do yourself

**Tell Claude:**
- "The chapter titles in `mystmd/config.yaml` are wrong — pull them from the `\chapter{}` headings instead."
- "There are 47 `xref_not_found` warnings. Categorize them and find the pattern."
- "Equation labels inside `align*` aren't producing anchors. Check the lessons catalogue before writing new code."
- "Capture a lesson about the thing we just figured out."

**Do yourself:**
- Review the rendered HTML in a browser. Catch "this paragraph reads weirdly" or "this figure is in the wrong place" issues that don't show up as build warnings.
- Make editorial judgment calls (e.g., should this `\textbf{Title}` become an `## H2` in MyST?).
- Approve PRs, merges, releases, force-pushes.

## When something breaks

When you and Claude hit a non-obvious bug, ask Claude to **capture a lesson**:

> "/capture-lesson"

This adds a structured entry to [`lessons/`](lessons/) so the same hour of debugging never happens twice. The lessons catalogue is the institutional memory of the pipeline; every transform in `postprocess.py` traces back to a lesson.

If the bug is mechanically fixable and would affect another book, ask Claude to **codify it in the pipeline**, not just document it. The CLAUDE.md guide tells Claude [when to do which](CLAUDE.md#when-to-capture-a-lesson-vs-fix-the-pipeline).

## Working in parallel

For non-trivial pipeline work, ask Claude to set up a **git worktree** (`git worktree add ../mybook-issue-N -b fix/issue-N main`). This lets you run two Claude Code sessions side-by-side — one on a feature branch, one on a parallel fix — without either tripping on the other's branch state.

The two sessions share the same `.git` repository (so commits are immediately visible) but have independent working directories and HEADs. This is how complex multi-issue work happens here in practice.

## Where to go next

| If you want to… | Read |
|---|---|
| Understand the pipeline mechanics (`convert.sh`, transforms, file tour) | [README.md](README.md) |
| See a working config side-by-side with the LaTeX it converts | [`examples/book-dp1/`](examples/book-dp1/), [`examples/book-dp2/`](examples/book-dp2/) |
| Browse the catalogue of known pitfalls | [LESSONS.md](LESSONS.md) |
| See what Claude has been told about working in this repo | [CLAUDE.md](CLAUDE.md) |
| Track what changed in a given release | [CHANGELOG.md](CHANGELOG.md) |
| Find an unresolved issue or contribute a fix | [GitHub issues](https://github.com/QuantEcon/claude-latex-to-myst/issues) |
