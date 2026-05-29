---
id: 045
title: "Pandoc's HTML figcaption flattens caption math ($\\theta_0$ → unicode) for tikzpicture figures — extract the caption from source instead"
category: post-processing
tags: [figures, tikz, captions, math, pandoc, html, fidelity, phase-6]
source_project: book-dp-deep-learning
status: codified
codified_in: scripts/transforms/figures_from_latex.py::parse_figure_block (tikzpicture branch) + _emit_figure
severity: high
date: 2026-05-29
---

## Symptom

Across the Deep-Learning book's 78 inline-`tikzpicture` figures, every
caption with math rendered as flattened unicode instead of MyST math:

    source:   \caption{The model $h_{\bm{\theta}}(x) = \theta_0 + \theta_1 x$ ...}
    regen:    The model hθ(x) = θ0 + θ1x ...            ← math lost
    worked-on: The model $h_{\bm{\theta}}(x) = \theta_0 + \theta_1 x$ ...

The figure image itself resolved correctly (via `TIKZ_FIGURE_MAP` →
pre-rendered SVG); only the caption math was degraded. This was the
dominant Deep-Learning parity gap — 166 diff lines vs the worked-on
baseline, ~136 of them caption math.

## Cause

A `\begin{figure}` wrapping a raw `\begin{tikzpicture}` *bails* the marker
preprocessor (so the consumer's `TIKZ_FIGURE_MAP` override applies
post-pandoc — lesson [042]/#98 #3). Bailing means the **whole** float,
caption included, flows through pandoc. Pandoc renders the figcaption math
as HTML:

    <figcaption>The model
      <span class="math inline"><em>h</em><sub><em>θ</em></sub>(<em>x</em>) = …</span>
    fitted.</figcaption>

`convert_html_figures.extract_caption` then strips the tags, leaving
`hθ(x) = θ0 + θ1x`. The original `$...$` is **unrecoverable** from the
`<em>`/`<sub>` soup — the only way to keep the math is to never let pandoc
HTML-render the caption.

## Fix

`parse_figure_block` no longer bails *entirely* on a tikzpicture figure —
it emits a **caption-only marker**: strip the
`\begin{tikzpicture}…\end{tikzpicture}` region first (so node text /
`{\footnotesize …}` labels are **not** scooped — the #98 #3 protection),
then extract the float `\caption{}`, `\label{}`, and any *legitimate*
`{\footnotesize}` sub-panel captions that live OUTSIDE the tikz block. The
caption is batch-converted through pandoc by `_apply_figure_markers` like
every other marker caption, which preserves `$...$`. No image is set, so
`_emit_figure` resolves the image from `TIKZ_FIGURE_MAP` (override path) —
yielding the mapped SVG **plus** the math-preserving caption. With no
override it falls back to a caption admonition.

```python
if _TIKZPICTURE_RE.search(body):
    outer = _TIKZPICTURE_BLOCK_RE.sub('', body)        # strip tikz (no scoop)
    spec = FigureSpec(placement=placement)
    label_m = _LABEL_RE.search(outer)
    if label_m: spec.name = convert_label_colons(label_m.group(1))
    cap, _ = _extract_caption(outer)
    if cap is not None: spec.caption = _LABEL_RE.sub('', cap).strip() or None
    spec.sub_captions = _extract_footnotesize_subcaptions(outer)  # OUTSIDE tikz only
    if not spec.name and not spec.caption and not spec.sub_captions:
        return None
    return spec
```

Result: Deep-Learning parity diff vs the worked-on baseline fell **166 → 20
lines** (7 of 12 chapters now byte-identical). dp1 (no tikz figures) and
dp2 (3 tikz figures, plain-text captions) stayed byte-identical.

## How to detect

Grep the regen output for figure captions that contain unicode Greek /
math operators where the source had `$...$`:

    grep -nE '```\{figure\}' regen/ch.md   # then read the caption line
    # math flattening shows as bare θ α σ ∈ ⋅ where source had $\theta$ etc.

The structural gate: the §1b differential / a `golden_tex` case
(`tikz_figure_caption_math`) whose caption carries `$h_\theta$` and asserts
it survives as `$...$`, not unicode.
