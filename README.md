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
# 1. Clone alongside your book repo
git clone https://github.com/QuantEcon/claude-latex-to-myst.git

# 2. Scaffold mystmd/ for your book — discovers chapters automatically,
#    picks sensible defaults from one of the bundled example projects.
cd your-book/
bash ../claude-latex-to-myst/scripts/new-book.sh \
  --source . --dest mystmd --template dp2
$EDITOR mystmd/config.yaml          # fill in 'TODO:' titles, bib name, etc.

# 3. Run the pipeline. scripts/convert.sh auto-runs `uv sync` on first call,
#    so the venv is created and pyyaml installed transparently.
bash ../claude-latex-to-myst/scripts/convert.sh --config mystmd/config.yaml

# 4. Build and preview
cd mystmd && myst build --html && myst start
```

`--template` choices: `dp2` (default; full-featured), `dp1` (book/ subdir
layout, standalone frontmatter), or `minimal` (you fill in everything).

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
.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import postprocess; print('OK')"
bash scripts/convert.sh --help                   # auto-runs uv sync; prints usage
```

For full parity tests against `book-dp1` / `book-dp2`, see
[`reports/README.md`](reports/README.md).

## License

MIT. Use freely, fork freely, add lessons freely.
