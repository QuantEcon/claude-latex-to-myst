"""Small pure helpers shared across multiple transform modules."""

from __future__ import annotations

import re


def convert_label_colons(label: str) -> str:
    """Convert colons to hyphens in a label: 'thm:main' → 'thm-main'.

    The universal label convention: pandoc preserves LaTeX colon-bearing
    labels verbatim; MyST anchor syntax does not accept ``:``; every
    transform that emits an anchor normalises via this helper.
    """
    return label.replace(':', '-')


# A line that opens (or closes) a backtick fence: optional indent then a
# run of three or more backticks. Tildes and colon fences are deliberately
# ignored — they can't terminate a backtick fence (lesson 040).
_FENCE_LINE_RE = re.compile(r'[ \t]*(`{3,})')


def outer_fence(content: str) -> str:
    """Pick a backtick fence at least one tick longer than the longest
    code fence inside ``content`` — CommonMark/MyST require an enclosing
    directive's fence to outrank any nested fence of the same character,
    else the inner ``` closes the directive early. Minimum three
    backticks; a body with a nested ```` ```python ```` block yields four
    (lesson 040, the lecture-source convention).

    Composes bottom-up (``code(3) ⊂ note(4) ⊂ exercise(5)``) only when the
    body's fence counts are final at call time. Fences injected into a
    directive body by a *later* pipeline stage are not accounted for — see
    the ordering limitation noted in issue #79.
    """
    inner = 0
    for line in content.splitlines():
        m = _FENCE_LINE_RE.match(line)
        if m:
            inner = max(inner, len(m.group(1)))
    return '`' * max(3, inner + 1)
