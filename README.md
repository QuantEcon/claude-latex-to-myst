# claude-latex-to-myst

A reusable pipeline for converting academic LaTeX (books, monographs, long
papers) to high-fidelity MyST Markdown. Extracted from the
[`book-dp2`](https://github.com/QuantEcon/book-dp2) conversion and
generalized so a new book is a config change rather than a re-implementation.

The pipeline is **pandoc + post-processing**:

```
LaTeX (.tex) ──► preprocess.sh ──► pandoc ──► postprocess.py ──► MyST (.md)
                  (sanitize)        (parse)     (transforms)
```

Pandoc handles the hard parsing. A Python post-processor (25 transform
stages and counting) turns its output into proper MyST syntax —
sphinx-proof directives, MyST cross-refs, figure directives, KaTeX-safe
math, natbib citation variant decoding, structured table conversion
(`\begin{tabular}` variants → MyST `{table}` / pipe-table via a marker
preprocessor that bypasses pandoc's lossy table reader), etc. The
transforms encode every lesson learned over a 26K-line book conversion
— see [`lessons/`](lessons/) for the catalogue and
[`CHANGELOG.md`](CHANGELOG.md) for what changed when.

> **New here?** [`GETTING-STARTED.md`](GETTING-STARTED.md) is a short guide
> to running a first conversion in collaboration with Claude Code. The rest
> of this README is the tool reference — bootstrap mechanics, file tour,
> and sanity checks.

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
| `scripts/postprocess.py` | Orchestrator: `process_text` chains the ~25 transform stages. Holds no mutable run state (a back-compat module-proxy forwards the legacy `ENV_MAP` etc. names to the context). |
| `scripts/conversion_context.py` | `ConversionContext` — the threaded run state (env map, tikz map, rewrites, per-file counters, the `POST_CONVERT` hook); `from_config` builds it. Makes the pipeline reentrant. |
| `scripts/transforms/` | Themed transform modules (`math`, `refs`, `cite`, `figures`, `code`, `envs`, `tables`, `frontmatter`, …). A stateful transform takes `ctx`. |
| `scripts/transforms/_markers.py` | Shared marker base (`pandoc_batch_convert`, `encode_payload`/`decode_payload`, `reassemble`) used by the figure + table preprocessors. |
| `scripts/preprocess.sh` | LaTeX sanitization before pandoc (config-driven). Calls helpers for chapter-split, rewrites, algorithm / listing / description / enumerate / table / figure markers. |
| `scripts/convert.sh` | Pipeline driver: preprocess → pandoc → postprocess → validate. |
| `scripts/validate.py`, `scripts/count_baseline.py` | Structural diff (equations, refs, theorems, figures, citations — source vs output; marker-aware; flags broken math) + per-book count baselines. |
| `scripts/validate_fixture.sh`, `scripts/setup_fixtures.sh` | Two-baseline fixture harness: `--against snapshot` (refactor-safety byte-identity) vs the default parity gap against the worked-on `mystmd/`. |
| `tests/golden_tex/`, `tests/test_marker_differential.py` | `.tex`-rooted golden tier + the §1b differential migration gate (Phase 1 safety net). `.github/workflows/test.yml` runs them in CI with a pinned pandoc. |
| `scripts/templates/book-convert.sh`, `scripts/new-book.sh` | Vendored book wrapper + the scaffolder for a book's `mystmd/`. |
| Book-side `project_overrides.py` | Optional closed surface a consumer book supplies: `TIKZ_FIGURE_MAP`, `EXTRA_REWRITES`, one `POST_CONVERT(text, stem, ctx)` hook (the graduation-rule "one book → book-side" tier). |
| `config.example.yaml` | Per-project config (chapter list, bib, preprocess/postprocess rewrites, TikZ map, validation toggles). |
| `lessons/` + `LESSONS.md` | One markdown file per lesson learned, plus the index. |
| `CHANGELOG.md`, `ROADMAP.md`, `notes/design/` | What changed, what's next, and the architecture design substrate. |
| `examples/book-dp1/`, `examples/book-dp2/` | Reference configurations from the originating conversions. |
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
