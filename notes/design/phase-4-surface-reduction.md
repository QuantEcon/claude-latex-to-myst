# Phase 4 — Surface reduction + decision records

**Status:** LANDED (architecture-evolution branch, commit 4/5) · **Effort:** subfigure ~2–3 days; fallback removal ~1 day · **Risk:** medium · **Depends on:** Phases 2–3 and GH #94

> **Landed — with a reassessment (the design was partly wrong; corrected
> here first, per the session prompt).**
>
> 1. **#94 subfigure marker — done for the fully-modelled shape.**
>    `_apply_figure_markers` now marker-izes a `\begin{figure}` whose every
>    `\begin{subfigure}` panel is a plain `\includegraphics`, emitting one
>    `{figure}` per panel (outer label → first panel, `-b`/`-c` suffix for
>    later unlabelled panels; lesson 021 semantics). Panels that aren't plain
>    `\includegraphics` (dp1's `\scalebox{\input{…pdf_t}}`) **bail** to the
>    HTML path — conservatism (bail unless fully modelled). Gated by the §1b
>    differential (`tests/marker_corpus/figures/subfigure.tex` → equal) and a
>    `golden_tex` case (`subfigure_includegraphics`). Real-book effect: dp2
>    `ch_approx_learning` improved (panel-caption math `$\alpha=0.7$` is now
>    preserved, vs the old fallback flattening it to unicode `α`); dp1
>    `ch_val` `f-du` unchanged in substance (the composite `du.svg` override
>    still wins — see below) with a cosmetic apostrophe flip. Snapshot
>    **re-pinned** after review.
>
> 2. **`convert_html_figures` is NOT removed — the design's premise was
>    invalidated by #98 #3.** The plan assumed subfigure was the last shape
>    keeping the fallback alive. But the post-#design `\begin{tikzpicture}`
>    bail (#98 #3) and the scalebox/input-subfigure bail both *route through*
>    `convert_html_figures` → `resolve_tikz_figures` to apply the consumer's
>    `TIKZ_FIGURE_MAP` override. The preprocessor can't see that map, so it
>    must bail and the fallback must stay. **Revised rule: one path per
>    *fully-modelled* construct; the fallback is retained for the bail set.**
>    An outer-label override still wins for a marker-ized subfigure float —
>    the check moved post-pandoc into `_emit_figure` (where the map is
>    visible), which is what keeps dp1 `f-du` rendering `du.svg`.
>
> 3. **Table audit:** `convert_simple_tables` handles **non-float**
>    `\begin{center}\begin{tabular}` (pandoc fixed-width output); the marker
>    path owns `\begin{table}` floats. Disjoint shapes — one path per
>    construct already holds; neither retires the other. No change.
>
> 4. **AST decision record** landed in CLAUDE.md "Settled architectural
>    decisions"; **lessons re-tagged** quirk-vs-permanent in LESSONS.md.

## Problem

Every structural construct currently carries **two** code paths: the
marker resolver (primary) and the post-pandoc HTML/markdown fallback.
[`process_text`](../../scripts/postprocess.py#L588-L607) runs
`resolve_table_markers` **and** `convert_simple_tables`,
`resolve_figure_markers` **and** `convert_html_figures`. The fallbacks
are the old pre-marker code, kept alive because the marker path doesn't
yet cover all shapes:

- Figures: `_apply_figure_markers.py` is **Phase-1 scope only** — it
  bails on `\begin{subfigure}`, which still falls through to
  `convert_html_figures` (GH #94).
- Tables: `convert_simple_tables` still handles non-float
  `\begin{center}\begin{tabular}` shapes.

This dual path is a standing maintenance tax:
[tables.py](../../scripts/transforms/tables.py) (29 KB) +
[tables_from_latex.py](../../scripts/transforms/tables_from_latex.py)
(46 KB), two figure modules, etc. "Generality" here means **removing** a
path, not maintaining both forever.

## Design

### 1. Finish the marker coverage (GH #94 — subfigure)

Extend `_apply_figure_markers.py` to handle `\begin{subfigure}` blocks
(the Phase-2-of-figures work the review schedules). `FigureSpec` already
carries `sub_captions`; the gap is parsing multi-image subfigure layout
and emitting N `{figure}` directives (one per subfigure label) — the
shape `validate.py::_count_figures_latex`
([27–39](../../scripts/validate.py#L27-L39)) already *expects*.

Do the equivalent audit for tables: enumerate the shapes still served
only by `convert_simple_tables` and bring them under the marker path.

### 2. Retire the HTML fallbacks

Once a construct's marker path covers all observed shapes (proven by the
golden corpus + consumer-fixture validation from Phase 1):

- Remove the fallback call from `process_text`.
- Delete or shrink the fallback module to a documented "legacy / removed"
  stub.
- Keep a golden case per retired shape so coverage doesn't silently
  regress.

This is the concrete payoff of the Phase-2 hybrid-boundary commitment:
the boundary stops being "two paths, one preferred" and becomes "one
path."

### 3. Custom-AST decision record (close the door deliberately)

Per the review (§5) and the user, the custom LaTeX → AST → MyST rewrite
is **declined**. Record it so it's never silently re-litigated:

> **Decision: no custom LaTeX AST.** Evaluated in DESIGN-REVIEW §2.
> Pandoc's math/cite/prose reader is ~15 years hardened and would take
> multiple quarters to match; a new parser is pure new bug surface. The
> marker-hybrid already replaces pandoc exactly where it's weak
> (structure) while keeping it where it's strong (inline prose, math,
> native cites, ref plumbing). Revisit only if the marker boundary proves
> unable to cover a structural construct that matters — which has not
> happened across tables, figures, algorithms, listings, description, and
> enumerate.

Land this as a short entry in CLAUDE.md's "Settled architectural
decisions" plus a one-paragraph record here.

### 4. Lesson catalogue re-categorization

Re-tag the 43 lessons along one axis: **pandoc-emission quirk** (retired
once the construct is fully marker-ized — these should *shrink* as
Phases 2/4 land) vs. **genuine unmodeled construct / MyST/KaTeX fact**
(permanent). This makes the catalogue's growth interpretable: a rising
quirk-count means the boundary is leaking; a rising permanent-count is
just normal coverage. Pairs naturally with the Phase-1 work of giving
each quirk lesson a `golden_tex` reproducer.

## Scope boundaries

- **In:** #94 subfigure marker, table-shape audit, fallback removal for
  fully-covered constructs, AST decision record, lesson re-tagging.
- **Out:** removing a fallback whose marker path is *not* proven complete
  by the gate. Coverage-first; deletion follows proof.

## Exit criteria

- `convert_html_figures` removed (or stubbed) after #94 + subfigure
  golden cases pass.
- At most one active code path per structural construct in `process_text`.
- AST decision recorded in CLAUDE.md.
- Lessons carry a quirk/permanent tag; LESSONS.md "By category" reflects it.
