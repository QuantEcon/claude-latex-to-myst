# claude-latex-to-myst

A reusable pipeline for converting academic LaTeX (books, monographs, long
papers) to high-fidelity MyST Markdown. Extracted from the
[`book-dp2`](https://github.com/QuantEcon/book-dp2) conversion and
generalized so a new book is a config change rather than a re-implementation;
it now drives the `book-dp1`, `book-dp2`, and Deep-Learning book conversions.

The pipeline is **pandoc + post-processing**:

```
LaTeX (.tex) ──► preprocess.sh ──► pandoc ──► postprocess.py ──► MyST (.md)
                  (sanitize)        (parse)     (transforms)
```

Pandoc handles the hard parsing — inline prose, math, native citations.
Everything structural (floats, tabulars, algorithms, listings,
description/enumerate lists) is extracted to marker comments before pandoc
and decoded after it, bypassing pandoc's lossy readers. A Python
post-processor (~40 transform stages) turns the result into proper MyST —
sphinx-proof directives, MyST cross-refs, figure directives, KaTeX-safe
math, natbib citation variant decoding, structured tables. The transforms
encode every lesson learned across three book conversions — see
[`lessons/`](lessons/) for the catalogue and [`CHANGELOG.md`](CHANGELOG.md)
for what changed when.

> **New here?** [`docs/getting-started.md`](docs/getting-started.md) is a
> short guide to running a first conversion in collaboration with Claude
> Code. The rest of this README is the tool reference — bootstrap
> mechanics, repo tour, and sanity checks.

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

## Repo tour

| Path | Purpose |
|------|---------|
| `scripts/` | The pipeline: `convert.sh` (driver), `preprocess.sh` + `_apply_*.py` marker preprocessors (pre-pandoc), `postprocess.py` + `transforms/` (post-pandoc), `validate.py` (structural counts), `new-book.sh` (book scaffolder). |
| `config.example.yaml` | Per-project config: chapter list, bib, preprocess/postprocess rewrites, TikZ map, validation toggles. |
| `lessons/` + `LESSONS.md` | The pitfall catalogue — one file per lesson (54 and counting), plus the index. |
| `tests/` | ~900 unit tests, the `.tex`-rooted golden tier (52 cases), and the marker differential gate; run in CI with a pinned pandoc. |
| `docs/` | [`getting-started.md`](docs/getting-started.md) (guided first conversion) and [`design/`](docs/design/) (architecture design records). |
| `reports/` | Parity reports against the consumer books ([`reports/README.md`](reports/README.md)). |
| `examples/` | Reference configurations from the originating `book-dp1` / `book-dp2` conversions. |

For the detailed code layout — which module owns which transform family,
how to add a transform, the pandoc/marker boundary, and the settled
architectural decisions — see [`CLAUDE.md`](CLAUDE.md), the repo's working
guide (written for Claude Code sessions, equally useful to humans).

## The lessons catalogue

Every non-obvious pitfall encountered while converting books goes into
`lessons/` as a structured markdown file, marked `open` (documented, not
yet automated) or `codified` (the pipeline now handles it). Use
`/capture-lesson` in a Claude Code session to add one; see
[`LESSONS.md`](LESSONS.md) for the index and
[`lessons/README.md`](lessons/README.md) for the schema.

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
