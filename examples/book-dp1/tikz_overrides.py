"""Project-specific TikZ resolution map for book-dp1.

Loaded by postprocess.py when config.yaml's `tikz_overrides` points here.

dp1 has ~10 TikZ diagrams referenced from the chapter sources:

    state_action_reward, js_two_period, js_decisions, jump_chain,
    flint, worker_switching, fixed_point_monotonicity_{1,2},
    infsup, triangle2

To resolve any of them to a rendered image, add an entry below mapping the
preprocessor label (``f-<stem>`` or ``fig-<stem>`` depending on how the
\\caption is labelled) to ``(image_path, caption_override)``. Until then
the postprocessor leaves them as placeholder admonitions so a reviewer can
see they need manual work.

Render the SVGs with whatever pipeline the project uses (dp1's repo has
a ``mystmd/scripts/render_tikz.py``); this config-file only needs to
tell our postprocessor where the rendered files ended up.
"""

TIKZ_FIGURE_MAP: dict = {
    # 'f-state_action_reward': ('figures/state_action_reward.svg', None),
    # 'f-js_two_period':       ('figures/js_two_period.svg', None),
    # ... fill in as renders become available
}

TIKZCD_INLINE_MAP: dict = {
    # 'ch_transforms': [
    #     {'pattern': r'...', 'replacement': '...'},
    # ],
}
