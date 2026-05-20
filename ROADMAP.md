# Roadmap

What to work on next, in priority order. Each item lists rough effort,
expected impact, and pointers to the relevant lesson(s) or report(s).

## Recently closed

- **`examples/book-dp1/` config promoted** (closed 2026-05-20). Verified
  config + `tikz_overrides.py` stub + README that reproduces dp1's
  algorithm and listing directives byte-for-byte. Sets
  `frontmatter_style: standalone` to match dp1's convention. New books
  cloning the dp1 workflow now have a template instead of re-deriving.

- **#016 — `§ Section` doubled prefix** (closed 2026-05-20). Added
  `strip_doubled_section_symbol` in `postprocess.py`, parallel to lesson
  011's noun-strip. Drops 471 `§{ref}` occurrences in dp2's regen output
  to 0; preserves the 13 legitimate external-section references like
  "§10.2 of {cite}`sargent2025dynamic`".

- **frontmatter_style flag** (closed 2026-05-20). Two valid MyST forms
  for chapter heading + label: `absorbed` (YAML block, default) and
  `standalone` (`(label)=` + `# Title`, dp1 style). Verified both work
  byte-for-byte against their reference outputs; idempotent on re-runs.

- **whitespace_compression flag** (closed 2026-05-20). Optional
  `compact` mode collapses blank lines between adjacent ` ``` ` fences
  for denser source; `readable` (default) preserves them. Honest scope:
  approximation of dp1's hand-tuned spacing, not byte-identical.

- **#015 — minted listings** (closed 2026-05-20). Ported as
  `scripts/_apply_listing_markers.py` + `postprocess.py::resolve_listings`.
  Adds `source_code_base` config option (defaults to `source_dir`). All
  21 `\begin{listing}` blocks across 5 dp1 chapters (ch_intro, ch_mcs,
  ch_mdps, ch_val, ch_ctime) produce byte-identical `{code-block}`
  directives. Surfaced a pipeline-ordering issue: resolve_listings/
  resolve_algorithms must run AFTER convert_citations so inlined source
  code isn't mangled (Julia `@views` → `{cite:t}`views``).

- **#014 — algorithm2e support** (closed 2026-05-20). Ported as
  `scripts/_apply_algorithm_markers.py` + `postprocess.py::resolve_algorithms`.
  Algorithm directives on all five dp1 chapters with algorithm2e blocks
  (ch_intro, ch_mdps, ch_rdps, ch_state_dep, ch_ctime) are byte-identical
  to dp1's committed output. Surfaced and fixed an unrelated regex bug
  in `convert_equations` (see lesson 014's "Side bug fixed during port").

## Open issues (prioritised)

### 🟡 1. Selectively regenerate `book-dp2/mystmd/` to absorb pipeline improvements

**Effort:** ~2 hours (was ~30 min — see below)
**Impact:** Medium. Affects how dp2's MyST output looks and which
features (algorithm bullet lists, `§ Section` dedupe, etc.) are visible.

Originally scoped as "cosmetic blank-line drift + 1 semantic fix". After
the algorithm2e port (#014), minted port (#015), and § dedupe (#016), the
diff is much larger:

| File | Diff lines | Semantic |
|------|-----------:|---------:|
| ch_apps.md | 156 | 0 |
| ch_rdps.md | 98 | 0 |
| ch_math_foundations.md | 68 | 0 |
| ch_ldps.md | 48 | 0 |
| ch_adps.md | 60 | 0 |
| ch_adps2.md | 82 | 2 |
| ch_adps3.md | 87 | 13 |
| ch_approx_learning.md | 93 | 16 |
| ch_transforms.md | 108 | 27 |
| ch_egs.md | 226 | 34 |
| common_symbols.md | 153 | **138** ← hand-edited |
| preface.md | 109 | **84** ← hand-edited |

`common_symbols.md` and `preface.md` carry hand-edits (table reformatted,
title changes, `# Preface` heading manually added) that a blind regen
would wipe. Recommendation:

1. **Regenerate the chapters with 0 semantic diffs** (`ch_adps`,
   `ch_apps`, `ch_ldps`, `ch_math_foundations`, `ch_rdps`) — pure
   blank-line additions, safe.
2. **Inspect-then-regenerate the small-semantic chapters** (`ch_adps2`,
   `ch_adps3`) — diffs are clear improvements (algorithm bullets,
   `§ Section` dedupe).
3. **Larger-diff chapters with new algorithm bodies** (`ch_egs`,
   `ch_approx_learning`, `ch_transforms`) — biggest *quality* wins;
   verify the algorithm-body bullet structure looks right then regen.
4. **Skip** `common_symbols.md` and `preface.md` — preserve the
   hand-edits; a future hand-merge can pull in our § dedupe later.

Sandbox the regen output in `fixtures/book-dp2/regen/` first (see
`scripts/setup_fixtures.sh`), eyeball the diffs, and only then commit
into the dp2 repo with a "regenerate from claude-latex-to-myst" message.

See [reports/book-dp2-parity.md](reports/book-dp2-parity.md) for the
older single-fix numbers (now superseded).

---

### 🟢 2. (Optional) Tighten `whitespace_compression: compact`

**Effort:** ~2 hours
**Impact:** Low. The flag exists and works for projects that want denser
source than the default. Matching dp1's hand-tuned spacing
byte-for-byte would additionally require preserving the original LaTeX
source-spacing through `convert_environment_divs`, which would be a
bigger refactor. Defer unless someone asks for it.

---

## Things to consider once gaps are closed

### Adopt this tool inside `book-dp1` PR #336

[PR #336](https://github.com/QuantEcon/book-dp1/pull/336) is the dp1
mystmd conversion. It currently uses a fork of dp2's pipeline. With #014
and #015 closed, `frontmatter_style` and `whitespace_compression` added
as config flags, and the dp1 reference config promoted to
`examples/book-dp1/`, nothing in this tool's roadmap is blocking
adoption. dp1 could switch its `mystmd/scripts/` to a thin wrapper that
calls into `claude-latex-to-myst`:

```bash
# In book-dp1/mystmd/scripts/convert.sh
exec bash ../../claude-latex-to-myst/scripts/convert.sh \
  --config ../config.yaml "$@"
```

This eliminates dp1's ~488 lines of duplicated `postprocess.py`. The
benefit: future improvements to the shared tool flow to dp1 automatically.
The cost: dp1 adopts our stylistic defaults (or we add the config flags).

### Set up the `claude-pdf-to-myst` repo (separate tool)

Per our earlier discussion: PDF → MyST conversion has a fundamentally
different shape (OCR + LLM cleanup, vs pandoc + regex). Different repo,
different lessons catalogue, but a shared `myst-conventions.md` doc.

Not blocking anything in this repo. Track separately.

### Template-repo / one-command bootstrap

When more books start using this tool, the "copy config + edit" step
could be a `scripts/new-book.sh BOOK_NAME` that scaffolds a config from
the examples directory. Premature until at least one more book has been
through the flow.

---

## Things I won't do (and why)

- **Won't add LLM calls to the pipeline.** The pipeline must be
  deterministic and re-runnable. LLM use for *targeted cleanup of edge
  cases* happens in the human's editor / Claude Code session, not inside
  `convert.sh`. (Implicit in `CLAUDE.md`.)
- **Won't write a YAML subset parser to avoid the PyYAML dep.** Per
  [lesson 010](lessons/010-pep-668-system-python.md), uv solved the
  dependency-installation problem more cleanly than dropping the dep.
- **Won't generalise beyond academic books.** The tool assumes chapters,
  theorems, equations, bibliography. Documents without that shape need a
  different tool.
