# HANDOFF

Context for the next Claude Code session opened in this directory.

This repo was created and brought to its current state in a single session
run from inside `~/work/quantecon/book-dp2`. The session history lives in
Claude Code's project store for that directory and can't be cleanly
relocated. **This document is the replacement for that history** — read it
first and you'll have everything you need to continue.

If you're a human reading this: skim, then go to `ROADMAP.md`.
If you're Claude resuming work: read this in full before doing anything.

---

## How this repo came to exist

The user (Matt McKay, QuantEcon) has a series of academic books that need
to be converted from LaTeX → MyST Markdown. The `book-dp2` repo had a
working but bespoke pipeline (`mystmd/scripts/postprocess.py` + friends)
developed during that book's conversion. We extracted it into a reusable,
config-driven tool that can be applied to other books with minimal
per-project setup.

The originating conversation covered:

1. Capturing lessons learnt from book-dp2 into the existing
   `book-dp2/PROMPT-LaTeX-TO-MD.md` (now updated with 23 lessons).
2. Deciding on a strategy: separate tools for LaTeX-to-MyST and
   PDF-to-MyST (different problem shapes), not one combined tool.
3. Extracting and generalising `book-dp2/mystmd/scripts/` into this repo.
4. Adopting `uv` as the project manager (one-command bootstrap, no PEP 668
   pain).
5. Parity-testing against `book-dp2` (byte-identical for 10/10 chapters
   after the initial extract) and `book-dp1` (end-to-end success on the
   first try; identified 5 missing transforms, ported 3, documented 2 as
   open gaps).

## Current state of the repo

```
claude-latex-to-myst/
  pyproject.toml          # uv project; `dependencies = ["pyyaml>=6.0"]`
  uv.lock                 # committed for reproducible installs
  README.md               # quick-start (uv-based bootstrap)
  CLAUDE.md               # instructions for Claude working in this repo
  ROADMAP.md              # ← prioritised next-work list. READ THIS NEXT.
  HANDOFF.md              # this file
  LESSONS.md              # index of the lessons/ catalogue (15 entries)
  config.example.yaml     # per-project config schema
  .gitignore
  .claude/
    commands/
      capture-lesson.md   # /capture-lesson slash command
  scripts/
    convert.sh            # orchestrator; auto-runs `uv sync`
    preprocess.sh         # sanitise .tex via Python (all rewrites)
    postprocess.py        # 14 transforms; library + CLI
    _config.py            # YAML loader helper (used by shell scripts)
    _apply_rewrites.py    # applies preprocess.strip / preprocess.rewrites
    validate.py           # counts equations / refs / theorems source vs output
  lessons/
    001 .. 015            # one .md per lesson (10 codified, 2 open, 3 tooling)
    README.md             # schema and lifecycle
  reports/
    book-dp2-parity.md    # extraction parity test
    book-dp1-parity.md    # first cross-project test
    README.md
  examples/
    book-dp2/             # config + tikz_overrides that produced dp2's mystmd/
```

4 commits on `main`:

```
fa85014  Port 3 generic transforms from book-dp1; document 2 open gaps
e73d8a4  Adopt uv as the project manager
671fa11  Portability fixes from book-dp2 parity test
1e2dc1a  Initial skeleton: config-driven LaTeX → MyST pipeline
```

Not yet pushed to GitHub. The intended remote is
`QuantEcon/claude-latex-to-myst`.

## How to verify nothing rotted

```bash
cd ~/work/quantecon/claude-latex-to-myst
git status                                          # should be clean
git log --oneline                                   # should show the 4 commits above
.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import postprocess; print('OK')"
bash scripts/convert.sh --help                      # auto-runs uv sync; prints usage
```

If any of those fail, something has drifted since 2026-05-20.

## How to verify the dp2 parity test still passes

```bash
cd ~/work/quantecon/book-dp2
git worktree add --detach ../book-dp2-pipeline-test mystmd-conversion
mkdir -p ../book-dp2-pipeline-test/mystmd-test
cp ~/work/quantecon/claude-latex-to-myst/examples/book-dp2/{config.yaml,tikz_overrides.py} \
   ../book-dp2-pipeline-test/mystmd-test/
bash ~/work/quantecon/claude-latex-to-myst/scripts/convert.sh \
  --config ../book-dp2-pipeline-test/mystmd-test/config.yaml

# Expected drift: ~440 cosmetic blank-line additions + 1 ch_adps2.md
# semantic change (Theorem~\ref → just the ref). See
# reports/book-dp2-parity.md for the precise numbers.
diff -r ../book-dp2-pipeline-test/mystmd/ \
       ../book-dp2-pipeline-test/mystmd-test/ | head -20

# Cleanup
cd ~/work/quantecon/book-dp2
git worktree remove --force ../book-dp2-pipeline-test
```

## What's outstanding

Read [`ROADMAP.md`](ROADMAP.md). Summary of the prioritised list:

1. 🔴 Close gap [#014](lessons/014-algorithm2e-resolution.md): algorithm2e
   support. ~3–4 hrs. Highest impact; needed for most theoretical books.
2. 🟡 Close gap [#015](lessons/015-minted-listings-resolution.md): minted
   listings. ~1–2 hrs.
3. 🟡 Regenerate `book-dp2/mystmd/` to absorb the pipeline improvements
   (cosmetic, but stops drift compounding).
4. 🟢 Promote `examples/book-dp1/` (the working dp1 config — currently
   only existed in a temporary worktree).
5. 🟢 `frontmatter_style` config flag (stylistic).
6. 🟢 (Optional) `whitespace_compression` config flag.

## Decisions you can rely on

These were debated in the originating session and resolved. Don't re-litigate
without checking:

- **Per-project config + generic transforms.** Chapter list, custom-macro
  rewrites, TikZ overrides live in `config.yaml` / `tikz_overrides.py`.
  Transforms live in `postprocess.py`. If something feels "too dp1-specific"
  or "too dp2-specific" inside `postprocess.py`, it probably belongs in
  config.
- **`uv` is the project manager.** Not pip, not conda, not raw venv. Per
  lesson [010](lessons/010-pep-668-system-python.md).
- **No Perl in the pipeline.** Per lesson
  [009](lessons/009-bsd-sed-mapfile-portability.md). When porting dp1's
  Perl preprocessors (gaps #014, #015), they get rewritten in Python.
- **No LLM calls inside the pipeline.** It must be deterministic and
  re-runnable. LLM-driven cleanup happens in the user's editor session,
  not in `convert.sh`. See `CLAUDE.md`.
- **Lessons catalogue: one .md per lesson with frontmatter.** New lessons
  via `/capture-lesson`. Lifecycle: `open` → `codified` once the fix is in
  the pipeline. Lessons are never deleted.
- **Reports format.** New parity tests get a report in `reports/`
  documenting what worked, what didn't, and what was learned. They
  motivate any pipeline changes that follow.

## Things that surprised us (so they don't surprise you)

- **Non-breaking space in pandoc output.** LaTeX `~` (e.g.
  `Theorem~\cref{...}`) emerges as U+00A0 in pandoc's markdown — not a
  regular space. Any text-pattern matching against pandoc output needs to
  consider both. Lesson
  [011](lessons/011-doubled-noun-refs.md).
- **`id(list)` is not unique across a Python program's lifetime.**
  Caused 118 duplicate-label bugs in dp2. Lesson
  [004](lessons/004-id-recycling-duplicate-labels.md).
- **Pandoc's `--wrap=none` produces lines that can be thousands of
  characters long.** Regex character classes like `[^\]]*` will happily
  match across `$` math boundaries and consume entire equation blocks.
  Always exclude structural delimiters. Lesson
  [002](lessons/002-cross-ref-regex-eats-equations.md).
- **MyST treats blank lines as block terminators inside `$$ ... $$`.**
  Pandoc routinely inserts blank lines between `\right].` and the closing
  `$$`. One of the highest-impact transforms in the pipeline strips them.
  Lesson [001](lessons/001-blank-lines-in-math-blocks.md).
- **PR #336 in book-dp1** has a parallel mystmd conversion that diverged
  from dp2's pipeline. Our parity test against it surfaced 5 gaps; 3 are
  closed, 2 are documented as open.

## Where the originating session's session history lives

For posterity / if you want to read the source conversation:

```
~/.claude/projects/-Users-mmcky-work-quantecon-book-dp2/
```

Most of the relevant decisions are captured in this `HANDOFF.md`,
`ROADMAP.md`, the lessons catalogue, and the two parity reports. The raw
session is the lowest-priority archive.

## Conventions if you're Claude continuing this work

- Verify before committing. Run the dp2 parity check; the drift should
  match what `reports/book-dp2-parity.md` documents. If it doesn't,
  something has changed unexpectedly.
- Capture lessons with `/capture-lesson`. The point of the catalogue is
  cumulative learning across many books; please feed it.
- When closing an open lesson (e.g. #014), flip its status from `open` to
  `codified`, fill in `codified_in:`, and update the index entry in
  `LESSONS.md`. Don't delete the lesson.
- The user prefers terse responses with concrete file paths, line
  numbers, and clear scope estimates. Don't over-explain; do tell them
  honestly when something is bigger than initially scoped (per the dp1
  algorithm-porting episode).
- The git user is `Matt McKay <mamckay@gmail.com>`. Commits in this repo
  have used `-c user.name=... -c user.email=...` flags rather than
  config; that's fine, continue that pattern.
