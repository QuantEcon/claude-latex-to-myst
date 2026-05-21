# Roadmap

What to work on next, in priority order. See [CHANGELOG.md](CHANGELOG.md)
for the per-release record of what's already landed.

## In flight

### Migrate `book-dp1` to this pipeline

**Effort:** ~half a day (mostly config porting, no tool changes expected).
**Impact:** High. dp1 still runs ~1500 lines of its own
`mystmd/scripts/` (postprocess.py, preprocess.sh, perl rewriters) that
duplicate transforms now in this repo. Migrating drops the duplication
and means future improvements propagate to dp1 automatically.

All known gaps are closed in v0.1.0:

- `preprocess.split` handles `book/appendix.tex` (3 `\chapter{}` → appA/appB).
- Per-file `frontmatter_style` handles dp1's mixed conventions
  (numbered chapters standalone, front-matter absorbed).
- Book-side wrapper post-steps run `render_tikz.py` + `build_llms_txt.py`
  inside the same `bash mystmd/convert.sh` invocation.
- `validate.broken_inline_math` folds in dp1's standalone
  `_find_broken_math.py`.
- `postprocess.rewrites` is available if dp1 needs editorial rewrites
  comparable to dp2's `## Mathematical Notation` promotion.

Remaining work is dp1-side config (not tool changes):
`\scalebox{N}{\input{...}}` unwrap, `\input{figures/*.pdf_t}` rewrite,
`\inputminted` strip, `\pageref` variants. All entries in
`config.preprocess.rewrites` / `config.preprocess.strip`.

Handover notes: see [`HANDOVER-book-dp1.md`](HANDOVER-book-dp1.md).

## Open items

### GH issue [#1](https://github.com/QuantEcon/claude-latex-to-myst/issues/1) — em/en-dash conversion

**Effort:** ~half a day for `---` only; ~full day with `--` too.
**Impact:** Low / cosmetic. MyST renders `---` literally; ~40 instances
per dp2 book chapter would benefit. The committed dp2 chapters already
accept `---`, so this is a polish item rather than a blocker.

Full scope analysis is in the issue. When picking this up, start with
`---` only (em-dash) and skip `--` (en-dash) — the en-dash positions
include legitimate `Author--Author` proper nouns and `(i)--(iii)` ranges
that are higher-judgment cases.

### Optional polish

- **Tighten `whitespace_compression: compact`** to match dp1's
  hand-tuned spacing byte-for-byte. The flag works for projects that
  want denser source; exact dp1 parity would require preserving
  source-spacing through `convert_environment_divs` — bigger refactor,
  defer unless asked.

## Things to consider once gaps are closed

### Adopt this tool in additional books

The bar for "adopt" is now `mystmd/config.yaml` + drop in the wrapper.
After dp1 migrates, the obvious next candidates are any other
QuantEcon books with LaTeX sources and chapter structure.

### Set up the `claude-pdf-to-myst` repo (separate tool)

PDF → MyST conversion has a fundamentally different shape (OCR + LLM
cleanup vs. pandoc + regex). Different repo, different lessons
catalogue, but a shared `myst-conventions.md` doc. Not blocking
anything in this repo.

## Things I won't do (and why)

- **Won't add LLM calls to the pipeline.** Determinism and
  re-runnability are non-negotiable. LLM-driven cleanup for edge
  cases happens in the user's editor / Claude Code session, not
  inside `convert.sh`. Settled in [CLAUDE.md](CLAUDE.md).
- **Won't write a YAML subset parser to avoid the PyYAML dep.** Per
  [lesson 010](lessons/010-pep-668-system-python.md), `uv` solved the
  installation problem more cleanly than dropping the dep.
- **Won't generalise beyond academic books.** The tool assumes
  chapters, theorems, equations, bibliography. Documents without that
  shape need a different tool.
- **Won't add a hooks framework to `convert.sh`.** The book wrapper
  is the right place to hang project-specific post-steps; coupling
  the tool to book-side script semantics adds complexity for no gain.
