---
id: 026
title: "Pandoc emits <img src=…> for \\includegraphics and <embed src=…> for \\input{tikz/…} — both must be recognised as figure sources"
category: post-processing
tags: [figures, html, pandoc, includegraphics, tikz, subfigures]
source_project: external book (Deep_Learning_for_Solving_And_Estimating_Dynamic_Economic_Models)
status: codified
codified_in: scripts/postprocess.py::convert_html_figures
severity: medium
date: 2026-05-24
---

## Symptom

An ordinary `\begin{figure}…\includegraphics{foo.png}…\end{figure}` —
no TikZ involved — came through the pipeline as

```
```{admonition} Figure (TikZ — needs manual conversion)
:name: fig-foo

…caption…
```
```

instead of as a real `{figure}` directive pointing at `foo.png`. In
the book that surfaced this, 10 of 88 figures were affected — every
pre-rendered raster figure became a TikZ placeholder.

The downstream book worked around it by listing each affected label in
its `TIKZ_FIGURE_MAP`, but that duplicates the converter's job and
fails for any new figure added later.

## Cause

Pandoc emits two distinct HTML shapes for figures:

- `<embed src="…">` for `\input{tikz/…}` figures. The src points at
  the original `.tex`/`.tikz` path that the LaTeX-side toolchain
  would have rendered.
- `<img src="…">` for ordinary `\includegraphics{…}` references. The
  src is the image filename verbatim.

`convert_html_figures` has two passes:

- **Pass 1** (nested subfigure pattern) correctly checked for
  `<embed src>` and emitted a real `{figure}` when one was present
  (the GH #17 fix). But the regex was anchored to `<embed>` only —
  so a nested subfigure using `<img>` would still slip through.
- **Pass 2** (non-nested) didn't check for an image source at all.
  It unconditionally called `make_admonition`, regardless of whether
  the figure contained a real image.

Two cumulative defects: (a) Pass 1's regex was too narrow; (b) Pass 2
never adopted Pass 1's image-source check.

## Fix

Unify the image detector and mirror the image-check into both passes:

```python
_figure_src_re = re.compile(r'<(?:embed|img)[^>]*src="([^"]+)"')

# Pass 1 (nested subfigures):
embed_match = _figure_src_re.search(inner_block)
if embed_match:
    parts.append(make_figure(chosen, embed_match.group(1), caption))
else:
    parts.append(make_admonition(chosen, caption))

# Pass 2 (non-nested):
def replace_html_figure(m):
    block = m.group(0)
    id_match = re.search(r'<figure[^>]*id="([^"]+)"', block)
    label = convert_label_colons(id_match.group(1)) if id_match else None
    caption = extract_caption(block)
    embed_match = _figure_src_re.search(block)
    if embed_match:
        return make_figure(label, embed_match.group(1), caption)
    return make_admonition(label, caption)
```

The TikZ placeholder path remains the correct fall-through: when there
is no `<img>`/`<embed>` src, the figure body must have been a
`\input{tikz/…}` (or similar generated content) that the user needs
to wire up via `TIKZ_FIGURE_MAP`.

Tests: `test_non_nested_figure_with_img_src_emits_figure_not_admonition`
and `test_nested_subfigure_with_img_src_emits_figure` in
[tests/test_transforms.py](../tests/test_transforms.py).

## How to detect

Before fix, in a converted chapter:

```bash
# Count "TikZ — needs manual conversion" placeholders vs. real
# {figure} directives.
grep -c 'TikZ — needs manual conversion' mystmd/ch_*.md
grep -c '```{figure}'                     mystmd/ch_*.md
```

If the placeholder count is non-zero in a book that has *no* TikZ
figures (only `\includegraphics` references), the bug is firing. The
ratio in the book that surfaced this was 10 placeholders to 78 real
figures.

A complementary check — look for `<img src>` survivors in the
converted markdown:

```bash
grep -n '<img src' mystmd/ch_*.md
```

Should be zero after the fix; any hit means a figure block didn't
match either pass.

## Generalizable rule

**Pandoc's HTML output uses different tags for semantically similar
sources.** Whenever a transform inspects pandoc HTML for "is there
real image content here", the regex must cover every tag pandoc emits
for that semantic class — not just the one tag observed in the book
that motivated the transform.

For images today that means at least `<embed>` and `<img>`. If a
future book turns up another shape (e.g. `<object src=…>` for SVGs in
some pandoc versions), the unified `_figure_src_re` is the one place
to extend.

Same lesson applies elsewhere in `postprocess.py`: any regex anchored
on a single tag name that pandoc could plausibly emit under a
different name (`<svg>` vs `<embed>` for some SVG paths, `<a href>`
vs `<link>` for some link shapes) is a latent project-specific
narrowness.
