# Roadmap

What to work on next, in priority order. Each item lists rough effort,
expected impact, and pointers to the relevant lesson(s) or report(s).

## Recently closed

- **#014 — algorithm2e support** (closed 2026-05-20). Ported as
  `scripts/_apply_algorithm_markers.py` + `postprocess.py::resolve_algorithms`.
  Algorithm directives on all five dp1 chapters with algorithm2e blocks
  (ch_intro, ch_mdps, ch_rdps, ch_state_dep, ch_ctime) are byte-identical
  to dp1's committed output. Surfaced and fixed an unrelated regex bug
  in `convert_equations` (see lesson 014's "Side bug fixed during port").

## Open issues (prioritised)

### 🟡 1. Close gap #015 — minted listings

**Effort:** ~1–2 hours
**Impact:** Medium. Affects any book embedding code listings via minted
(`\begin{listing}` + `\inputminted`). Common in QuantEcon books; absent
from purely theoretical texts.

**What it requires:**

- Port `_rewrite_listings.pl` (~44 lines Perl) to Python.
- Port `resolve_listings` (~80 lines). Adds a new responsibility: reading
  source files at postprocess time and inlining line ranges into the
  output as `code-block` directives.
- Introduces a new config concept: `source_code_dirs` (where to look for
  the referenced source files; absolute paths or relative to `source_dir`).

Reference implementation: see [lesson 015](lessons/015-minted-listings-resolution.md).

**Test:** Re-run dp1 parity; listings should now appear as `code-block`
directives with `:name:` for `{numref}` cross-references.

---

### 🟡 2. Regenerate `book-dp2/mystmd/` to absorb pipeline improvements

**Effort:** ~30 minutes
**Impact:** Low (cosmetic) but ongoing — every future maintenance run
against dp2 will produce the same drift until this happens.

The 3 dp1 transforms we ported affect dp2's output by:

- +440 cosmetic blank lines after closing `$$`
- 1 correctness improvement in `ch_adps2.md` (`Theorem~\ref` → `{prf:ref}`)

These are objectively improvements. The committed `book-dp2/mystmd/`
predates them. Suggestion: run our tool against dp2 once, commit the
result with a clear "regenerate from claude-latex-to-myst" message, and
make claude-latex-to-myst the canonical source going forward.

See [reports/book-dp2-parity.md](reports/book-dp2-parity.md) for the
detailed numbers.

---

### 🟢 3. Promote `examples/book-dp1/` config

**Effort:** ~30 minutes
**Impact:** Low. Anyone wanting to convert dp1 in the future re-derives the
config from scratch otherwise.

The dp1 test config (committed only inside the parity-test worktree, now
gone) covered:

- 10 dp1 chapters + `common_symbols` with titles
- `source_dir: ../book`, `bibliography: qe_bib.bib`, `figures_dir: ../figures`
- 11 strip rules (5 are pageref variants — dp1 has many `\pageref{...}`
  patterns that need stripping for HTML)
- 7 rewrite rules (`\navy`, scalebox, tikz, xfig `.pdf_t`, minted, algorithm)
- `tikz_overrides: null` (not populated for the test)

Add it as `examples/book-dp1/config.yaml` and a stub `tikz_overrides.py`
for the figures dp1 actually uses. Then someone re-running can do
`cp examples/book-dp1/* mystmd/` and pick up where the test left off.

See [reports/book-dp1-parity.md](reports/book-dp1-parity.md) for the
config that worked.

---

### 🟢 4. `frontmatter_style` config flag

**Effort:** ~1 hour
**Impact:** Low (stylistic) — but unblocks dp1 adoption if dp1 wants to
keep its current `(label)=\n# Title` style.

Two valid MyST conventions:

- `absorbed` (dp2, our current default): `---\ntitle: "..."\nlabel: ...\n---`
- `standalone` (dp1): `(label)=\n# Title\n`

Both work. Adding a config flag is small. Default to `absorbed` (current
behaviour). dp1 sets `frontmatter_style: standalone` in its config.

Touches: `postprocess.py::add_frontmatter`, `config.example.yaml`.

---

### 🟢 5. (Optional) `whitespace_compression` config flag

**Effort:** ~2 hours
**Impact:** Low.

dp1 strips blank lines aggressively (after `:label:`, before `$$`, between
adjacent directives). dp2 and our tool keep them for source readability.

Could become a config flag (`whitespace: readable | compact`) with the
compact path implementing dp1's stripping. Or we declare "readable" as the
canonical style and let dp1 either adopt it or maintain its own override.

Deferred until someone actually asks. Lower priority than the algorithm
and listing gaps.

---

## Things to consider once gaps are closed

### Adopt this tool inside `book-dp1` PR #336

[PR #336](https://github.com/QuantEcon/book-dp1/pull/336) is the dp1
mystmd conversion. It currently uses a fork of dp2's pipeline. With #014
closed, only #015 (minted listings) and the optional `frontmatter_style`
flag remain before dp1 could
switch its `mystmd/scripts/` to be a thin wrapper that calls into
`claude-latex-to-myst`:

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
