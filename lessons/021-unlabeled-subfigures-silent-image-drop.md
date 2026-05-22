---
id: 021
title: "Unlabeled subfigures inside a labeled \\begin{figure} silently drop all but the first image"
category: post-processing
tags: [figures, subfigures, html-figures, pandoc, silent-data-loss]
source_project: book-dp2 (ch_approx_learning.tex:609)
status: codified
codified_in: scripts/postprocess.py::convert_html_figures (nested-subfigure embed path)
severity: high
date: 2026-05-22
---

## Symptom

A `\begin{figure}` block containing multiple `\begin{subfigure}` blocks
where the **subfigures have no individual `\label{}`** was collapsed
into a single `{figure}` directive. The first subfigure's image was
emitted (using the outer label as its `:name:`), but the second (and
any subsequent) subfigure was silently dropped — no warning, no
placeholder, the `<embed src="…">` for the second image simply
disappeared from the MyST output.

The original caption text (e.g. "Standard iteration" / "Damped
iteration") survived in the figure's caption slot because authors
typically wrote a combined outer caption ("Trajectories of standard
and damped iteration. Left: … Right: …"), masking the missing image
unless someone visually inspected the rendered output.

The validator's `figures` column reported `10/10` in the affected
chapter — the bug was double-masked, because the old LaTeX-side count
(`\begin{figure}` only, no subfigure awareness) coincidentally
balanced the dropped MyST-side image. Lesson 015's subfigure-aware
LaTeX count surfaced the issue as `11/10`.

## Cause

Pandoc emits unlabeled subfigures as nested HTML `<figure>` blocks
where the inner `<figure>` has an `<embed src="…">` but no `id`
attribute (no `\label{}` means no id):

```html
<figure id="f:sa_damped_trajectory">
  <figure>
    <embed src="figures/sa_damped_trajectory_standard.pdf" />
    <figcaption>Standard iteration</figcaption>
  </figure>
  <figure>
    <embed src="figures/sa_damped_trajectory_damped.pdf" />
    <figcaption>Damped iteration</figcaption>
  </figure>
  <figcaption>Trajectories of standard and damped iteration</figcaption>
</figure>
```

The original `convert_html_figures` `replace_nested` path ignored
`<embed src>` entirely. Every inner figure was converted to a TikZ
admonition placeholder via `make_admonition`, regardless of whether
the source was a real raster image (`\includegraphics`) or a TikZ
include (`\input{tikz/…}`).

The outer label `f-sa_damped_trajectory` was donated to the **first**
unlabeled inner (because it was cross-referenced via `{numref}` and
needed a destination), then `outer_assigned` was set, and the second
unlabeled inner kept `chosen = None`. `resolve_tikz_figures`'s
`elif label:` branch handles labeled-but-unresolved as a passthrough;
its `else` branch ("orphaned sub-panel from subfigure, skip") drops
the unlabeled admonition entirely.

A vestigial `TIKZ_FIGURE_MAP` entry in the project's
`tikz_overrides.py` then rescued the first image (mapping the outer
label to one specific PDF) with a side-by-side caption — which both
worked around the silent drop and obscured it from future readers.

## Fix

Two coupled changes inside `convert_html_figures.replace_nested`:

### 1. Detect `<embed src>` and emit a real `{figure}` directly

When an inner subfigure carries an actual image source, bypass the
admonition placeholder round trip entirely:

```python
embed_match = re.search(r'<embed[^>]*src="([^"]+)"', inner_block)
if embed_match:
    parts.append(make_figure(chosen, embed_match.group(1), caption))
else:
    parts.append(make_admonition(chosen, caption))  # TikZ path unchanged
```

This treats real images and TikZ placeholders as different paths.
TikZ continues to route through `TIKZ_FIGURE_MAP`; real images skip it.

### 2. Auto-generate `{outer}-{a,b,…}` for unlabeled inners

After the existing "outer label donation" logic runs, any inner that
still has `chosen = None` is given a deterministic suffix derived
from its index:

```python
if chosen is None and outer_label:
    chosen = f"{outer_label}-{chr(ord('a') + idx)}"
```

This guarantees every subfigure has a cross-refable name (even if
nothing actually references it), and matches the natural author
intent for two unlabeled subfigures under `f:foo` → `f-foo-a`,
`f-foo-b`.

## Caption behaviour

Because the fix emits the inner caption directly (e.g. "Standard
iteration", "Damped iteration ($\alpha = 0.7$)"), the outer caption
("Trajectories of standard and damped iteration") and any
caption-override stored in `TIKZ_FIGURE_MAP` for the outer label go
unused for `<embed>` inners. This is correct in spirit — the outer
caption usually described a side-by-side view that no longer exists
once the subfigures are emitted as separate figures. Authors who
want a combined caption should keep one `\begin{figure}` with a
single `\includegraphics` that points at a pre-composited image, not
two subfigures.

## How to detect

```bash
# Compare LaTeX-side subfigure-aware count to MyST {figure} count.
# Pre-fix this was the only signal — and it was masked by the old
# validator that didn't count subfigures.
uv run python scripts/validate.py --config .../config.yaml

# Sanity grep: every {numref} should land somewhere.
for label in $(grep -oE '\{numref\}`[^`]+`' mystmd/*.md | sed 's/.*`\([^`]*\)`/\1/' | sort -u); do
    grep -l ":name: $label" mystmd/*.md >/dev/null || echo "MISSING: $label"
done
```

## Generalizable rule

Pandoc's HTML `<figure>` emission is not a TikZ-only path —
`\includegraphics` inside a labeled figure that also has a label of
its own (or contains subfigures with their own labels) also routes
through it. Any handler for that path must read `<embed src>` instead
of assuming the contents are opaque and need an external resolution
map. The TikZ-placeholder behavior is correct only when there's no
real image source to fall back on.

Two reinforcing meta-lessons:

- **Silent data loss compounds.** A single ad-hoc override
  (`TIKZ_FIGURE_MAP[label] = (one-of-two-images, side-by-side-caption)`)
  papered over the symptom and let the bug live for many months. The
  override produced output that *rendered fine*, just incorrectly.
- **Validator quality gates bug discovery.** The under-counting
  validator (lesson 015) hid this for the same period. Fixing the
  validator first surfaced the underlying bug. When a validator
  column shows "all clean" but the rendered output is wrong, suspect
  the validator before the pipeline.

Related: lesson [015](015-minted-listings-resolution.md) (subfigure
counting), lesson [008](008-pipeline-ordering.md) (transform order).
