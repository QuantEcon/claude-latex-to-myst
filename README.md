# claude-latex-to-myst

A reusable pipeline for converting academic LaTeX (books, monographs, long
papers) to high-fidelity MyST Markdown. Extracted from the
[`book-dp2`](https://github.com/QuantEcon/book-dp2) conversion and
generalized so a new book is a config change rather than a re-implementation.

The pipeline is **pandoc + post-processing**:

```
LaTeX (.tex) ──► preprocess.sh ──► pandoc ──► postprocess.py ──► MyST (.md)
                  (sanitize)        (parse)     (13 transforms)
```

Pandoc handles the hard parsing. A 13-stage Python post-processor turns its
output into proper MyST syntax (sphinx-proof directives, MyST cross-refs,
figure directives, KaTeX-safe math, etc.). The transforms encode every
lesson learned over a 26K-line book conversion — see [`lessons/`](lessons/)
for the catalogue.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
and `pandoc` ≥ 3.0.

```bash
# 1. Clone alongside your book repo, just for the bootstrap
git clone https://github.com/QuantEcon/claude-latex-to-myst.git /tmp/clm

# 2. Scaffold mystmd/ for your book — discovers chapters automatically,
#    drops in a vendored convert.sh wrapper + .tool-version pin file.
cd your-book/
bash /tmp/clm/scripts/new-book.sh --source . --dest mystmd --template dp2
$EDITOR mystmd/config.yaml          # fill in 'TODO:' titles, bib name, etc.

# 3. Run the pipeline. On first call, mystmd/convert.sh clones the tool
#    into _tools/claude-latex-to-myst/ at the version pinned in
#    .tool-version. Subsequent calls reuse the local checkout.
bash mystmd/convert.sh

# 4. Build and preview
cd mystmd && myst build --html && myst start
```

`--template` choices: `dp2` (default; full-featured), `dp1` (book/ subdir
layout, standalone frontmatter), or `minimal` (you fill in everything).

## How a book stays in sync with the tool

After scaffolding, the book repo owns its conversion workflow. The
clone at `/tmp/clm` from step 1 is throwaway — the book never depends
on a sibling checkout of this repo.

```
your-book/
├── mystmd/
│   ├── config.yaml
│   ├── convert.sh        ← vendored wrapper
│   ├── .tool-version     ← single line: tag, branch, or SHA
│   └── ch_*.md           ← regenerated output (committed)
└── _tools/               ← gitignored; managed by convert.sh
    └── claude-latex-to-myst/
```

**Day-to-day:** edit `.tex`, rerun `bash mystmd/convert.sh`, review the
`mystmd/*.md` diff, commit both. The wrapper announces which version of
the tool it's running on each invocation.

**Update the tool:** edit `.tool-version` (`main` → `v0.2.0`, or pin a
specific SHA), rerun `bash mystmd/convert.sh`. The wrapper fetches and
checks out the new ref automatically; the diff in `mystmd/*.md` shows
exactly what the tool change did to your book.

**Reproduce a past build:** check out the older commit of the book repo
— `.tool-version` is part of the commit, so the wrapper will fetch the
correct tool version. No need to remember anything externally.

`.tool-version` accepts any git ref: a tag for stability, a branch like
`main` for "always latest", or a SHA for fully-reproducible pinning.

**Book-side post-steps:** the wrapper deliberately doesn't `exec` to
delegate. Anything you append after the delegation line (TikZ rendering,
`llms.txt` generation, project-specific validators, etc.) runs as part
of the normal `bash mystmd/convert.sh` invocation. See the template's
"Book-side post-conversion steps" block for the commented-out examples.

Output lands in `mystmd/ch_*.md`, `mystmd/figures/`, and `mystmd/references.bib`.

No venv activation, no `pip install`, no `PATH=…` prefix — the shell script
bootstraps everything via `uv sync`. The lockfile (`uv.lock`) is committed
so installs are reproducible across machines.

## What's in here

| Path | Purpose |
|------|---------|
| `scripts/postprocess.py` | The 13-stage transform library (generic). |
| `scripts/preprocess.sh` | LaTeX sanitization before pandoc (config-driven). |
| `scripts/convert.sh` | Orchestrator: preprocess → pandoc → postprocess → validate. |
| `scripts/validate.py` | Structural diff: equations, refs, theorems counted in source vs output. |
| `config.example.yaml` | Per-project config (chapter list, bib, custom-macro rewrites, TikZ map). |
| `lessons/` | One markdown file per lesson learned, with frontmatter. |
| `LESSONS.md` | Index of the lessons catalogue. |
| `examples/book-dp2/` | Reference configuration that produced the `book-dp2` conversion. |
| `.claude/commands/capture-lesson.md` | `/capture-lesson` slash command to add a new lesson. |

## The lessons catalogue

Every non-obvious pitfall encountered while converting books goes into
`lessons/` as a structured markdown file. Each lesson has a lifecycle:

- **`status: open`** — known issue, documented but not yet fixed in the pipeline. Surfaced as a warning in the README and as a comment near related code.
- **`status: codified`** — the pipeline now handles this automatically. The lesson stays for posterity; future readers can grep for it.

Use `/capture-lesson` inside this repo to add a new entry without remembering
the format. See [`lessons/README.md`](lessons/README.md) for the schema.

## Scope (what this tool is and isn't)

**Designed for:**

- Academic books and long monographs with chapters
- LaTeX sources with custom macros, theorem environments, cross-references
- High-fidelity output: 95%+ equation/section/citation match against source

**Not designed for:**

- PDF input — use a separate tool (the failure modes are different; OCR
  errors and layout reconstruction dominate)
- LaTeX with no chapter structure — overkill for a single-file paper
- Bespoke TikZ diagrams — these need per-project rendering scripts; see
  `examples/book-dp2/render_tikz.py` for the pattern

## Requirements

- [`uv`](https://docs.astral.sh/uv/) — manages the Python interpreter and `pyyaml`
- `pandoc` ≥ 3.0
- `mystmd` for building the output: `npm install -g mystmd`
- Optional, for TikZ: `xelatex` + `pdf2svg`

Python itself is managed by `uv` — no system Python required, no virtualenv
juggling, no PEP 668 dance.

## Sanity check

After cloning or after pulling new changes:

```bash
git status                                       # should be clean
bash scripts/test.sh                             # runs the pytest suite
bash scripts/convert.sh --help                   # auto-runs uv sync; prints usage
```

For full parity tests against `book-dp1` / `book-dp2`, see
[`reports/README.md`](reports/README.md).

To run an end-to-end conversion AND build the resulting MyST site in
one go, pass `--build` to `convert.sh` — it runs `myst build --html`
in `output_dir` and summarizes errors/warnings:

```bash
bash scripts/convert.sh --config mystmd/config.yaml --build
```

Skipped by default to keep the conversion loop fast for iteration.

## License

MIT. Use freely, fork freely, add lessons freely.
