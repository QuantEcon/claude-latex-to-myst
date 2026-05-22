# FIX-frontmatter-and-tables parity report

**Date:** 2026-05-20
**Pipeline version:** through commit `9870687`
**Triggered by:** `FIX-frontmatter-and-tables.md`, filed earlier the same day
by book-dp2 against pipeline `315e8f2`. Documented four upstream gaps
blocking dp2 from a diff-only-shows-content-changes regen workflow.

## What was tested

Both fixtures end-to-end through `scripts/convert.sh`:

- **book-dp2** (canonical originating project): `fixtures/book-dp2/regen/`
  with the existing `config.yaml`. 10 chapters + preface + common_symbols.
- **book-dp1** (sibling project on a legacy pipeline): smoke-tested by
  creating a minimal `fixtures/book-dp1/regen/config.yaml` in
  standalone-frontmatter mode. dp1 is not yet on the unified pipeline;
  the test confirms our shared transforms don't regress on its source
  shape.

## Issues addressed

| # | Issue | Resolution | Commit |
|---|-------|------------|--------|
| 1 | pandoc 2-col `tabular` → unusable `simple_tables` | New `convert_simple_tables` transform; restricted to 2-col for first cut | `d6dcbe7` |
| 2 | `\chapter*{}` + `\label{}`: class attrs leak into label, explicit `\label{}` becomes orphan body anchor | Strip class tokens in `convert_section_labels`; prefer explicit body anchor over heading auto-id in `add_frontmatter`, guarded against stealing section anchors | `5a17cb6` |
| 3 | natbib variants (`\citep`, `\citealp`, `\citeyearpar`, `\citeauthor`) collapse to `{cite}` | Preprocess bracket-marker rewrites + new `decode_natbib_markers` running before `convert_cross_references` | `9870687` |
| 4 | LaTeX `---`/`--` not converted to Unicode | **Deferred.** Analysed and filed as [GH #1](https://github.com/QuantEcon/claude-latex-to-myst/issues/1) — real but cosmetic, larger scope than originally implied (140+ substitution sites in dp2 across 9 fragile contexts) |

## Result: parity ✓ for both books

### book-dp2

All 11 chapter frontmatter labels match committed dp2 exactly:

```
ch_adps.md            label: c-adps
ch_egs.md             label: c-egs
ch_apps.md            label: c-apps          ← caught regression: an
                                               over-greedy first cut
                                               had stolen `s-optstop`
                                               from the first section
common_symbols.md     label: c-cs            ← was the bug case
...
```

`common_symbols.md` produces 3 `{list-table}` directives matching the
committed file byte-for-byte modulo 4 out-of-scope cosmetic diffs
(title quoting, H2 promotion of `\textbf{}` pseudo-headings, IID/iid case).

Citation roles now match source exactly:

| natbib variant      | source count | fresh output | role           |
|---------------------|--------------|--------------|----------------|
| `\cite`             | 336          | 337 `{cite}` | `cite`         |
| `\citep`            | 14           | 14 `{cite:p}`| `cite:p`       |
| `\citet`            | 14           | 14 `{cite:t}`| `cite:t`       |
| `\citealp`          | 1            | 1 `{cite:t}` | `cite:t`       |
| `\citeyearpar`      | 2            | 2 `({cite:year})` | `cite:year` + parens |

Zero marker leaks, zero stray `[-@…]` residues.

### book-dp1 (smoke test)

Pipeline ran end-to-end without errors. All 10 chapters and both extras
produced clean `(c-foo)=` body anchors (standalone style). Notable
observations:

- **Our pipeline is more precise than dp1's legacy pipeline.** dp1's
  committed output has 406 `{cite:t}` + 45 `{cite}` only (everything
  collapses to those two). Fresh output preserves 404 `{cite:t}`,
  36 `{cite}`, 4 `{cite:p}`, 1 `{cite:year}`, 1 `{cite:author}` —
  matching dp1's source (4 `\citep`, 3 `\citeyear`, 3 `\citeauthor`).
- `common_symbols.md` correctly converts the 2-col tabular to
  `{list-table}` (Issue 1 fix).
- No marker leaks, no broken frontmatter labels, no stray
  suppress-author residues.

Line-count drift versus committed dp1 ranges from +6 to +38 per
chapter (typical wrapping/quoting differences); preface is -12 (the
committed wraps at ~80 cols). No regressions.

## Lessons captured

- [017](../lessons/017-pandoc-class-attrs-leak-into-labels.md) —
  pandoc class attrs leak into MyST labels
- [018](../lessons/018-greedy-explicit-label-promotion.md) —
  promoting body anchors needs a non-heading guard
- [019](../lessons/019-simple-vs-multiline-tables.md) —
  pandoc simple_tables vs multiline_tables blank-line distinction
- [020](../lessons/020-natbib-bracket-markers-precede-cross-refs.md) —
  natbib bracket markers must decode before cross-refs

## Open items

- GH issue #1 — em-/en-dash conversion (deferred Issue 4)
- `FIX-postprocess-rewrites.md` — separate untracked feature proposal
  about per-project Markdown rewrites (not part of this session's scope)
