"""Small pure helpers shared across multiple transform modules."""

from __future__ import annotations


def convert_label_colons(label: str) -> str:
    """Convert colons to hyphens in a label: 'thm:main' → 'thm-main'.

    The universal label convention: pandoc preserves LaTeX colon-bearing
    labels verbatim; MyST anchor syntax does not accept ``:``; every
    transform that emits an anchor normalises via this helper.
    """
    return label.replace(':', '-')
