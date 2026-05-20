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

```bash
# 1. Clone this template into your book repo, or copy scripts/ into it
git clone https://github.com/QuantEcon/claude-latex-to-myst.git
cd your-book/

# 2. Copy config and edit for your project
cp claude-latex-to-myst/config.example.yaml mystmd/config.yaml
$EDITOR mystmd/config.yaml          # set chapter list, bib filename, etc.

# 3. Run the pipeline
bash claude-latex-to-myst/scripts/convert.sh --config mystmd/config.yaml

# 4. Build and preview
cd mystmd && myst build --html && myst start
```

Output lands in `mystmd/ch_*.md`, `mystmd/figures/`, and `mystmd/references.bib`.

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

- `pandoc` ≥ 3.0
- Python 3.10+ (no third-party deps for the core pipeline)
- `mystmd` for building the output: `npm install -g mystmd`
- Optional, for TikZ: `xelatex` + `pdf2svg`

## License

MIT. Use freely, fork freely, add lessons freely.
