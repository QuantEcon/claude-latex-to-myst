---
id: 043
title: "Pandoc figure-caption emit drops citations and minipage sub-captions — recover from HTML attributes and sibling divs"
category: post-processing
tags: [pandoc, figures, captions, citations, minipage, html-extraction]
source_project: book-dp-deep-learning (R12 fidelity walkthrough)
status: codified
codified_in: scripts/_apply_figure_markers.py + scripts/transforms/figures_from_latex.py (figure-marker preprocessor, replaces the patches in scripts/transforms/figures.py::convert_html_figures); scripts/transforms/figures.py::convert_html_figures retained as fallback for subfigure shapes (Phase 2, issue #94)
severity: medium
date: 2026-05-28
---

## Symptom

Two distinct content-loss bugs reported on the same code path:

**#89** — `\citet{}` / `\citep{}` inside a `\caption{}` of `\begin{figure}`
arrive in the rendered output as nothing. The cite key is gone, the
prose breaks mid-sentence:

```
:caption: The DGM architecture of . The input feeds the first layer.
```

8 unique drops in book-dp-deep-learning ch07 / ch11. Table captions —
which go through the `_apply_table_markers.py` preprocessor — preserve
cites fine. Only the figure path is affected.

**#90** — Sub-caption text between `\end{tikzpicture}` and `\caption{}`
inside a `\begin{figure}\begin{minipage}` is silently dropped. The
main caption survives but per-panel labels (`(a) ...`, `(b) ...`) and
verification-arithmetic blocks vanish. 5 instances (4 ch02 + 1 ch06)
in the same book.

## Cause

Both surface in `convert_html_figures` (after pandoc has already
emitted the figure as HTML). Different specific defects:

**#89** — pandoc emits `\citet{X}` / `\citep{X}` inside a caption as
an **empty** `<span>`:

```html
<figcaption>The DGM architecture of <span class="citation"
data-cites="sirignano2018dgm"></span>. ...</figcaption>
```

The key lives in the `data-cites` attribute; the span has zero text
content. The previous `extract_caption` ran a generic
`re.sub(r'<[^>]+>', '', cap)` to strip HTML tags last — dropping both
the empty span and the key with it. Pandoc collapses the variant
(`\citet` / `\citep` / `\citep[loc]`) into the same empty-span form,
so the variant information is lost regardless — only the key can be
recovered.

**#90** — pandoc preserves per-panel `\begin{minipage}` text as
`<div class="minipage">` siblings of `<figcaption>` inside `<figure>`:

```html
<figure id="fig:vol">
<div class="minipage"><p>(a) the unit ball ...</p></div>
<div class="minipage"><p>(b) ratio versus ...</p></div>
<figcaption>The volume paradox.</figcaption>
</figure>
```

The previous `convert_html_figures` only extracted `<figcaption>`,
discarding everything else in the figure block. The minipages — and
all the panel labels / verification arithmetic in them — were lost.

## Fix

Both fixes live in `scripts/transforms/figures.py::convert_html_figures`
and share the same refactor: factor the inner-HTML-to-MyST processing
into `_html_caption_to_myst(inner)`, then call it from two places.

**For #89**: in `_html_caption_to_myst`, *before* the HTML-tag strip,
rewrite citation spans to pandoc native cite markdown:

```python
def _replace_cite(m):
    keys = m.group(1).split()           # space-sep for multi-cite
    if len(keys) == 1:
        return '@' + keys[0]
    return '[' + '; '.join('@' + k for k in keys) + ']'
cap = re.sub(
    r'<span\b[^>]*\bdata-cites="([^"]+)"[^>]*>[^<]*</span>',
    _replace_cite, cap,
)
```

`convert_citations` (later in `process_text`) then resolves `@X` →
`{cite:t}`X`` and `[@a; @b]` → `{cite}`a,b``. NB: all variants
collapse to textual `{cite:t}` because pandoc dropped the variant in
the HTML — small fidelity loss vs losing the key.

**For #90**: scan the figure block for `<div class="minipage">…</div>`
content, pass each through `_html_caption_to_myst`, and fold the
results into the caption in source order ahead of the main figcaption:

```python
def extract_minipage_subcaptions(block):
    return [
        t for t in (_html_caption_to_myst(mp.group(1))
                    for mp in re.finditer(r'<div class="minipage">(.*?)</div>',
                                          block, re.DOTALL))
        if t
    ]
```

Both fixes are exercised by tests in `tests/test_figure_shapes.py`:
single + multi cite recovery, sub-caption ordering, the cross-bug
case of a cite inside a minipage.

## How to detect

After a pipeline run, two greps surface these:

```bash
# #89: a {figure} body ending an in-prose phrase with "of ." / "from ."
grep -nE '(of|from|reported by|by)\s+\.' mystmd/*.md
# #90: source has \begin{minipage} inside \begin{figure}, output has none
diff <(grep -c '\begin{minipage}' chapter.tex) \
     <(grep -c 'minipage' mystmd/chapter.md)   # expected: same count or N>0
```

A clean run after the fix has no hanging "of ." / "from ." in figure
captions and minipage source text reappears in the output.

## Generalizable rule

**Pandoc's HTML output uses attributes to carry semantic information
that the corresponding markdown output puts in text.** Any post-pandoc
transform that strips HTML tags is at risk of losing whatever lived
in the attributes. Cite keys (`data-cites`), ref labels
(`data-reference`), MathJax classes, footnote markers, alt-text —
each needs to be converted to a markdown-form sentinel *before* tag
stripping. The pattern from this lesson — "convert each attribute-
bearing span to its markdown analogue, then strip remaining tags" —
generalises to other pandoc-HTML extraction paths.

Also: **a figure's content is everything inside `<figure>`, not just
`<figcaption>`.** Pandoc preserves `\begin{minipage}` (and would
preserve other text-bearing wrappers) inside the figure block. An
extraction that only reads `<figcaption>` loses arbitrary author
content. When in doubt, walk the figure block and gather every
text-bearing sibling, not just the caption tag.

## Postscript: superseded by the figure-marker preprocessor (#92/#93)

The patches above (citation-span recovery + minipage-div folding in
`convert_html_figures`) only partially closed the class. Within a
single DL-book sprint, two more leaks surfaced: `[[CITEP:X]]` natbib
markers leaked unescaped inside `<figcaption>` (#92, because pandoc
doesn't escape brackets in HTML context), and bare `{\footnotesize ...}`
between `\end{tikzpicture}` and `\caption{}` was still dropped (#93,
not in a minipage). That's 4 bugs in 1 sprint — the same trajectory
signal that justified the `fix_spacing_superscript` rebuild.

The long-term solution mirrors the table-marker preprocessor (#51/#55):
`_apply_figure_markers.py` extracts `\begin{figure}` floats pre-pandoc
into HTML-comment markers with the structure base64-encoded inside.
Captions and sub-captions are batch-converted through pandoc once,
escaping brackets so `decode_natbib_markers` finds them. Pandoc never
sees the figure body, so its HTML emission quirks can't drop or
mangle anything. `convert_html_figures` is retained as fallback for
the shapes Phase 1 doesn't yet cover (subfigure — Phase 2, issue #94).

**Generalizable rule (updated):** when a post-pandoc HTML-extraction
path accumulates more than two specific-quirk patches, prefer the
marker-preprocessor rebuild over a fifth patch. Pandoc's HTML
emission is fundamentally lossy/quirky; the marker pattern moves the
truth back to the LaTeX source where it can't be lost.
