"""Citation transforms.

Decodes the bracket-marker sentinels emitted by the preprocess natbib
rewrite (``\\citep``, ``\\citealp``, ``\\citeauthor``, ``\\citeyear``,
``\\citeyearpar`` — pandoc collapses them ambiguously; plus
``\\cite[loc]{key}``, whose locator makes pandoc drop the key, GH #74),
then handles pandoc's native citation syntax (``[@key]``, ``@key``,
``[-@key]``).

Order constraint: ``decode_natbib_markers`` MUST run before
``convert_cross_references`` (lessons 002 / 020) and before
``convert_citations``.
"""

from __future__ import annotations

import re


_NATBIB_MARKER_ROLE = {
    'CITEP':        ('cite:p',      False),
    'CITEALP':      ('cite:t',      False),
    'CITEALT':      ('cite:t',      False),
    'CITEAUTHOR':   ('cite:author', False),
    'CITEYEAR':     ('cite:year',   False),
    'CITEYEARPAR':  ('cite:year',   True),   # year-with-parens
    'CITE':         ('cite',        False),  # \cite[loc]{key} (GH #74)
}


def decode_natbib_markers(text: str) -> str:
    """Decode ``\\[\\[CITEXXX:keys\\]\\]`` markers emitted by the
    preprocess natbib rewrite (``_apply_rewrites.py``) into MyST
    ``{cite:*}`` roles.

    Must run **before** ``convert_cross_references``, because the markers
    start with ``\\[\\[`` and the cross-ref regex matches ``[display](#x)
    {reference-type=...}`` greedily — the leading ``[`` of the marker
    would otherwise pair with a downstream eqref's closing ``](#…)``,
    swallowing entire paragraphs (lesson 002 / lesson 020).

    Tolerates **both** bracket forms. Pandoc escapes ``[[`` → ``\\[\\[``
    when it emits *markdown* (the figure-marker batch-convert path, #92),
    but leaves ``[[…]]`` **unescaped** when it emits the brackets into an
    *HTML* ``<figcaption>`` — which is what happens for a ``\\begin{figure}``
    wrapping a raw ``\\begin{tikzpicture}`` that bails the marker path
    (#98 #3) and flows through pandoc whole-file. The optional ``\\\\?``
    before each bracket matches either form; the ``(CITE…):`` prefix keeps
    the match tight enough that the unescaped form can't swallow ordinary
    ``[link]`` text.
    """
    def replace_marker(m):
        role, parenthesize = _NATBIB_MARKER_ROLE[m.group(1)]
        keys = ','.join(k.strip() for k in m.group(2).split(','))
        rendered = '{' + role + '}`' + keys + '`'
        return '(' + rendered + ')' if parenthesize else rendered

    # ``CITE`` is listed last: it is a prefix of the others, so the
    # longer, more-specific alternatives must be tried first (only
    # ``CITE:`` — with the colon — reaches the final branch). The key
    # group excludes ``]`` and ``\\`` so the non-greedy match stops at the
    # closing brackets in both the escaped and unescaped forms.
    return re.sub(
        r'\\?\[\\?\[(CITEP|CITEALP|CITEALT|CITEAUTHOR|CITEYEAR|CITEYEARPAR|CITE):'
        r'([^\]\\]+?)\\?\]\\?\]',
        replace_marker,
        text,
    )


def convert_citations(text: str) -> str:
    """Convert pandoc's native citation syntax to MyST.

    Handles the forms pandoc emits for ``\\cite`` and ``\\citet``::

        [@key]              → {cite}`key`
        [@key1; @key2]      → {cite}`key1,key2`
        [-@key]             → {cite:year}`key`   (suppress-author)
        @key                → {cite:t}`key`

    Natbib variants that pandoc collapses ambiguously (``\\citep``,
    ``\\citealp``, ``\\citeauthor``, etc.) are handled separately by
    ``decode_natbib_markers``, which must already have run by the time
    this function executes.
    """
    # Pandoc native suppress-author form [-@key] (emitted for
    # \citeyear / \citeyearpar when the marker rewrite is bypassed).
    # Decode before the generic [@key] pass below so the leading "-"
    # isn't accidentally folded into a multi-cite.
    text = re.sub(
        r'\[-@([a-zA-Z][a-zA-Z0-9_-]+(?:\d{4}[a-zA-Z]?)?)\]',
        r'{cite:year}`\1`',
        text,
    )

    # Multi-citation: [@key1; @key2; ...]
    def replace_multi_cite(m):
        keys = re.findall(r'@(\S+?)(?:;|\])', m.group(0))
        return '{cite}`' + ','.join(keys) + '`'

    text = re.sub(r'\[@[^\]]+\]', replace_multi_cite, text)

    # Inline/textual citation: @key (not preceded by [ or @, and not
    # inside backticks). Guards against email addresses and
    # already-converted citations. ``:`` is permitted *inside* keys
    # (JabRef/Mendeley/ACM-style ``Author:Year:Tag`` — #32) but the
    # last char must be alphanumeric — otherwise a trailing ``:`` in
    # prose like ``\citet{key}: explanation`` gets swallowed into the
    # capture group (closes #36). Boundary lookahead stays at the
    # pre-#32 form so ``:`` in prose can still terminate the match.
    text = re.sub(
        r'(?<![`\[@])@([a-zA-Z][a-zA-Z0-9_:]*[a-zA-Z0-9_])(?=[^a-zA-Z0-9_]|$)',
        r'{cite:t}`\1`',
        text
    )

    return text
