"""Project-specific TikZ resolution map for book-dp2.

Loaded by postprocess.py when config.yaml's `tikz_overrides` points here.

Keys in TIKZ_FIGURE_MAP are the `:name:` labels emitted by the preprocessor
for `\\input{tikz/...}` references; values are `(image_path, caption_override)`
tuples. Set caption_override to None to use the original caption.
"""

TIKZ_FIGURE_MAP = {
    # SVG figures rendered by a project-specific render_tikz.py
    'f-du_conditions':        ('figures/du_conditions.svg', None),
    'f-og_decisions':         ('figures/og_decisions.svg', None),
    'f-lattice':              ('figures/lattice.svg', None),
    'f-infsup':               ('figures/infsup.svg', None),
    'f-adp_three_policies':   ('figures/adp_three_policies.svg', None),
    'f-adp_three_policies_b': ('figures/adp_three_policies_fp.svg', None),
    'f-bellman_envelope_a':   ('figures/adp_three_policies_greedy.svg', None),
    'f-bellman_envelope_b':   ('figures/adp_three_policies_envelope.svg', None),
    'f-coase_subp':           ('figures/coase_subp.svg', None),
    'f-coase_no':             ('figures/coase_no.svg', None),
    'fig-eth_viz':            ('figures/eth_viz.svg',
                               r'Visualization of {prf:ref}`ex-eth` with $\Xsf = [0,1]$'),
    'fig-conj_semiconj':      ('figures/conj_semiconj.svg', None),
    'f-unit_circ':            ('figures/unit_circ.pdf', None),
    'f-gdecomp':              ('figures/gdecomp.pdf', None),
    'f-sa_damped_trajectory': ('figures/sa_damped_trajectory_standard.pdf',
                               r'Trajectories of standard and damped iteration. '
                               r'Left: Standard iteration. Right: Damped iteration '
                               r'($\alpha = 0.7$)'),
}

TIKZCD_INLINE_MAP = {
    'ch_transforms': [
        {
            'pattern': r'\$\$[\s%]*\\begin\{tikzcd\}.*?\\end\{tikzcd\}[\s%]*\$\$',
            'replacement': ('```{image} figures/tikzcd_conjugacy_inline.svg\n'
                            ':width: 300px\n:align: center\n```'),
        },
    ],
}
