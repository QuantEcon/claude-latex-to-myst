---
id: 044
title: "Migrating a construct fallback→marker re-implements a parser that starts incomplete — lock it with a .tex-rooted differential gate, not counts"
category: preprocess
tags: [marker-pattern, figures, migration, testing, golden-tex, validate, differential-gate, regression]
source_project: book-dp2 / book-dp1 / book-dp-deep-learning (#98 regen audit)
status: codified
codified_in: tests/test_golden_tex.py (.tex→.md tier) + scripts/transforms/figures_from_latex.py (width/label/tikz-bail/path fixes) + scripts/transforms/cite.py::decode_natbib_markers (escaped+unescaped forms)
severity: high
date: 2026-05-29
---

## Symptom

The figure-marker migration (#95 Phase 1, #97 the #96 follow-up) closed a
real bug class (#89/#90/#92/#93 — see lesson [043](043-pandoc-figure-caption-content-loss.md))
and shipped with passing unit tests and a clean `validate.py`. Yet a regen
of the three consumer books against `main` regressed **four** figure
features that no test and no validator caught (#98):

1. **`:width:` dropped** — 31 figures in dp2. `\includegraphics[width=0.95\textwidth]`
   rendered with no `:width:` (the old `convert_figures` path emitted `95%`).
2. **Leading-space captions** — 66 in dp2. Every `\caption{\label{fig:x} Text}`
   gained a leading space (` Text`) in the rendered caption.
3. **TikZ node text leaked** — dp2 `f-coase_subp` / `f-coase_no`. A
   `\begin{figure}` wrapping a raw `\begin{tikzpicture}` had its
   `{\footnotesize $a_3$}` node labels scooped in as sub-captions and
   leaked above the override-SVG caption.
4. **Image dropped** — dp1 `f-finite_lq_1`. `\includegraphics[opts]` whose
   `{path}` sat on the next line was not matched, so the figure vanished.

**None of the four changes any `validate.py` count** — a figure still counts
as a figure, a caption is still present. They are invisible to count-based
validation *and* to the post-pandoc-only `tests/golden/` tier (whose inputs
already start from pandoc output, downstream of the marker preprocessor).

## Cause

The marker pattern trades *pandoc-emission bugs* (open-ended, invisible
until render) for *parser-completeness bugs* (a re-implemented parser that
starts incomplete). Migrating `\begin{figure}` from its `convert_html_figures`
fallback to `_apply_figure_markers` + `figures_from_latex` re-implemented, in
new code, every feature the old pandoc-fed path got "for free":

- pandoc converted `width=0.95\textwidth` → `95%`; the new `FigureSpec` had
  no `width` field, so the parser never read it and the emitter never wrote it.
- pandoc put the `\label` on the figure and kept the caption text clean; the
  new parser left `\label{}` *inside* the caption, so the batch pandoc pass
  emitted a `[]{#…}` span + a stray leading space that a later stripper
  reduced to one space.
- the old path bailed inline-tikz figures to `resolve_tikz_figures` (which
  *can* see `TIKZ_FIGURE_MAP`); the new parser marker-ized them and ran
  `_extract_footnotesize_subcaptions` over the tikz body.
- the old `\includegraphics` regex was pandoc's; the new one required
  `[...]{path}` adjacency.

That trade is favourable **only with a differential gate**: parser bugs are
finite, discoverable by diffing real `.tex` against a frozen output, and
lockable by a fixture. Without the gate the project paid the architecture's
cost (re-implemented parsers) without its benefit (safe migration).

## Second-order trap: bailing to another path drops *that path's* transforms

Fixing #98 #3 by bailing `\begin{tikzpicture}` figures to the post-pandoc
path **re-opened #92**: the marker path bracket-escapes `[[CITEP:X]]` so
`decode_natbib_markers` matches `\[\[CITEP:X\]\]`; the post-pandoc path emits
the caption into an HTML `<figcaption>` with the marker **unescaped**
(`[[CITEP:X]]`), which the decoder's escaped-only regex missed → 5 verbatim
`[[CITEP:…]]` leaks in DL ch01/02/04. **When you reroute a construct from
path A to path B, audit every transform A applied that B does not.** Fix:
make `decode_natbib_markers` tolerate both bracket forms.

## Fix

Four parser-completeness fixes in `figures_from_latex.py` (+ one in `cite.py`),
each locked by a named `tests/golden_tex/` case:

| # | fix | golden_tex case |
|---|-----|-----------------|
| 1 | `FigureSpec.width` + `_convert_includegraphics_width` (0.95\textwidth→95%, bare \textwidth→100%) | `figure_width_option` |
| 2 | strip `\label{}` from caption in `parse_figure_block` (label already captured as `:name:`) | `figure_label_in_caption` |
| 3 | bail `\begin{tikzpicture}` in `parse_figure_block` (syntactic, mirrors the subfigure bail) | `figure_raw_tikzpicture_with_override_bails` |
| 4 | `\s*` between `[opts]` and `{path}` in `_INCLUDEGRAPHICS_RE` | `figure_includegraphics_path_on_next_line` |
| 2nd-order | `decode_natbib_markers` matches escaped **and** unescaped `[[CITE…]]` | (same tikz case — `\citep` in caption) |

## Resolution: the `.tex`-rooted differential gate (Phase 1)

`tests/test_golden_tex.py` runs the **whole** pipeline (`_apply_rewrites` +
marker scripts → pandoc → `process_text`) against a hand-authored `input.tex`
and byte-diffs against a committed `expected.md`. This is the tier that would
have caught all four #98 regressions pre-merge. The four cases above seed it;
every future fallback→marker migration should add its real `.tex` shapes here
*before* merging, and diff old-path-vs-new-path output where a "before" exists.

## Generalizable rule

**A marker migration is not done when unit tests + `validate.py` pass — it is
done when a `.tex`→`.md` differential gate shows the new path reproduces every
feature the old path emitted.** Count-based validation is blind to
feature-level drops (width, caption whitespace, leaked/dropped text) because
the structural count is unchanged. Seed `tests/golden_tex/` with the real book
shapes the construct takes, and treat any byte diff from the old path as a
regression until explicitly reviewed and re-pinned. See lesson
[043](043-pandoc-figure-caption-content-loss.md) for the bug class this
migration was closing, and `notes/design/phase-1-validation-gate.md` for the
gate's design.
