"""Phase-5 book-side override demo: a fence-aware POST_CONVERT hook.

Replaces ``@@BRAND@@`` with ``Acme`` in prose, but leaves it untouched inside
fenced code blocks — the conservatism the override surface requires (CLAUDE.md).
"""


def POST_CONVERT(text, stem, ctx):
    out, in_fence = [], False
    for line in text.split('\n'):
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            out.append(line)
            continue
        out.append(line if in_fence else line.replace('@@BRAND@@', 'Acme'))
    return '\n'.join(out)
