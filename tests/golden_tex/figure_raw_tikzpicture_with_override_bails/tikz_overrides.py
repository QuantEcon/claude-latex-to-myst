# Consumer-supplied map: the raw tikzpicture figure is pre-rendered to SVG and
# keyed by its (colon→hyphen) label. resolve_tikz_figures substitutes this for
# the bailed figure's admonition placeholder.
TIKZ_FIGURE_MAP = {
    'f-coase_no': ('figures/coase_no.svg', None),
}

TIKZCD_INLINE_MAP = {}
