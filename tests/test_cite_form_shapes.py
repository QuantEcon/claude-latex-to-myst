"""Shape catalogue: citation forms × boundary characters × key types.

Sibling-parity guard for the citation regex family. Issues #32 / #36
both had boundary-character bugs that surfaced only when prose
punctuation followed a key. This file parametrises across every
boundary char the regex must terminate on, crossed with every cite
form, crossed with both plain and colon-bearing keys (the JabRef
case from lesson 031).

Handlers in ``postprocess.convert_citations`` and
``postprocess.decode_natbib_markers``. See lessons 031, 035.
"""

from __future__ import annotations

import pytest

import postprocess


# Boundary characters that mark the end of a key in prose. Each one
# must terminate the cite-capture without being pulled into the key.
BOUNDARY_CHARS = [
    ' ',     # whitespace
    ',',     # mid-clause comma
    '.',     # sentence period
    ';',     # semicolon
    ':',     # colon (the #36 case)
    '!',     # exclamation
    '?',     # question
    ')',     # closing paren
    ']',     # closing bracket (unlikely but possible)
]

# Key types. ``plain`` is the simple ``Author2020`` shape; ``colon`` is
# the JabRef/Mendeley/ACM ``Author:Year:Tag`` shape (lesson 031).
KEY_TYPES = {
    'plain':  'Smith2020',
    'colon':  'Bertsekas:2000:DPO:517430',
    'lowercase_only': 'marcet_marshall',
    'mixed_case': 'ECTA:ECTA1716',
}


@pytest.mark.parametrize("key_label,key", list(KEY_TYPES.items()))
@pytest.mark.parametrize("boundary", BOUNDARY_CHARS)
def test_textual_cite_boundary(boundary: str, key_label: str, key: str):
    """``@KEY<boundary>...`` must capture ``KEY`` without including the
    boundary char. Issues #32 / #36."""
    src = f'See @{key}{boundary} continues.'
    out = postprocess.convert_citations(src)
    expected = '{cite:t}`' + key + '`'
    assert expected in out, (
        f'key_type={key_label} boundary={boundary!r}:\n'
        f'  expected ``{expected}`` in:\n  {out}'
    )
    # The boundary char itself stays where it was.
    assert boundary + ' continues.' in out


@pytest.mark.parametrize("key_label,key", list(KEY_TYPES.items()))
def test_bracketed_cite_single_key(key_label: str, key: str):
    """``[@KEY]`` produces ``{cite}`KEY```. All key types."""
    src = f'See [@{key}] for details.'
    out = postprocess.convert_citations(src)
    assert '{cite}`' + key + '`' in out


@pytest.mark.parametrize("key_label,key", list(KEY_TYPES.items()))
def test_bracketed_multi_cite_with_key_type(key_label: str, key: str):
    """``[@KEY1; @KEY2]`` produces ``{cite}`KEY1,KEY2```. Mix of plain
    and the parametrised key type."""
    src = f'See [@{key}; @other2019] for both.'
    out = postprocess.convert_citations(src)
    # The order pandoc emits them — KEY first, other2019 second.
    assert '{cite}`' + key + ',other2019`' in out


@pytest.mark.parametrize("key_label,key", list(KEY_TYPES.items()))
def test_textual_cite_at_end_of_string(key_label: str, key: str):
    """End-of-string is a valid boundary."""
    src = f'Per @{key}'
    out = postprocess.convert_citations(src)
    assert '{cite:t}`' + key + '`' in out


def test_textual_cite_does_not_match_email():
    r"""``foo@example.com`` is an email address, not a citation (#179).
    The ``@`` is glued to a preceding word char, so the widened
    lookbehind rejects it — matching pandoc's own rule for telling a
    ``@key`` citation apart from an email."""
    src = 'Contact me at foo@example.com'
    out = postprocess.convert_citations(src)
    assert '{cite:t}' not in out
    assert 'foo@example.com' in out  # email survives verbatim


def test_textual_cite_does_not_match_mailto_link_or_url():
    r"""#179: an email inside a ``mailto:`` link / autolink / inline
    code, and a URL with an ``@``, all keep their ``@`` — pandoc emits
    it verbatim; only our over-greedy cite regex mangled it."""
    src = (
        'Write to [`jane.doe@unil.ch`](mailto:jane.doe@unil.ch). '
        'Or <jane.doe@unil.ch>. '
        'Or visit <https://example.com/user@host>.'
    )
    out = postprocess.convert_citations(src)
    assert '{cite' not in out
    assert '[`jane.doe@unil.ch`](mailto:jane.doe@unil.ch)' in out
    assert '<jane.doe@unil.ch>' in out
    assert '<https://example.com/user@host>' in out


def test_textual_cite_still_converts_real_citation():
    r"""Guard: narrowing the email lookbehind (#179) must not stop a
    genuine textual ``@key`` (preceded by a boundary) from converting."""
    assert postprocess.convert_citations('see @smith2020 for details') == (
        'see {cite:t}`smith2020` for details'
    )
    # start-of-string and after '(' are also boundaries
    assert postprocess.convert_citations('@jones1999 shows') == (
        '{cite:t}`jones1999` shows'
    )
    assert postprocess.convert_citations('(@doe2001)') == '({cite:t}`doe2001`)'


@pytest.mark.parametrize("marker_role,decoded_role", [
    ('CITEP',       'cite:p'),
    ('CITEALP',     'cite:t'),
    ('CITEALT',     'cite:t'),
    ('CITEAUTHOR',  'cite:author'),
    ('CITEYEAR',    'cite:year'),
    ('CITE',        'cite'),       # \cite[loc]{key} (GH #74)
])
def test_natbib_marker_decoded_to_role(marker_role: str, decoded_role: str):
    """The natbib bracket markers (emitted by preprocess for natbib
    variants pandoc collapses ambiguously) decode to the right
    ``{cite:*}`` role. Lesson 020 / GH #74."""
    src = f'Per \\[\\[{marker_role}:smith2020\\]\\] we have.'
    out = postprocess.decode_natbib_markers(src)
    assert '{' + decoded_role + '}`smith2020`' in out


def test_cite_marker_does_not_collide_with_citep_prefix():
    """``CITE`` is a prefix of ``CITEP``: the decode alternation must
    still resolve ``CITEP:`` to ``{cite:p}`` (not ``{cite}`` + leftover
    ``p``). Regression guard for the prefix ordering (GH #74)."""
    src = r'\[\[CITEP:smith2020\]\] and \[\[CITE:jones2019\]\].'
    out = postprocess.decode_natbib_markers(src)
    assert '{cite:p}`smith2020`' in out
    assert '{cite}`jones2019`' in out


@pytest.mark.parametrize("marker_role,decoded_role", [
    ('CITEP',       'cite:p'),
    ('CITEALP',     'cite:t'),
])
def test_natbib_marker_multi_key(marker_role: str, decoded_role: str):
    """Multi-key form passes through the bracket marker too."""
    src = (f'Per \\[\\[{marker_role}:smith2020,jones2019,brown2018\\]\\] '
           f'we have.')
    out = postprocess.decode_natbib_markers(src)
    expected = '{' + decoded_role + '}`smith2020,jones2019,brown2018`'
    assert expected in out


def test_natbib_marker_citeyearpar_wraps_in_parens():
    """``\\citeyearpar`` renders as ``(year)`` — the bracket-marker
    decoder must wrap the cite role with literal parens."""
    src = "Bellman's \\[\\[CITEYEARPAR:bellman1957\\]\\] monograph"
    out = postprocess.decode_natbib_markers(src)
    assert '({cite:year}`bellman1957`)' in out


@pytest.mark.parametrize("marker_role,decoded_role", [
    ('CITEP',  'cite:p'),
    ('CITE',   'cite'),
])
def test_natbib_marker_unescaped_brackets_decoded(marker_role, decoded_role):
    """#98 #3 regression: a ``\\begin{figure}`` wrapping a raw
    ``\\begin{tikzpicture}`` bails the marker path and flows through pandoc
    whole-file, which emits the caption into an HTML ``<figcaption>`` with
    the natbib bracket marker **unescaped** (``[[CITEP:key]]``) rather than
    the markdown-escaped ``\\[\\[CITEP:key\\]\\]`` the marker path produces.
    The decoder must handle both, or the marker leaks verbatim into the
    rendered caption (DL ch01/02/04, re-opened by the #98 #3 tikz bail)."""
    src = f'concentrate [[{marker_role}:aggarwal2001surprising]]; this is why'
    out = postprocess.decode_natbib_markers(src)
    assert '{' + decoded_role + '}`aggarwal2001surprising`' in out
    assert '[[' not in out


def test_natbib_marker_unescaped_multi_key():
    """Unescaped multi-key form (comma-separated, as it appears in a
    bailed figure caption) decodes with keys normalised."""
    out = postprocess.decode_natbib_markers(
        'again [[CITEP:belkin2019reconciling, nakkiran2020deep]].'
    )
    assert '{cite:p}`belkin2019reconciling,nakkiran2020deep`' in out


def test_natbib_decode_leaves_plain_double_brackets_alone():
    """The unescaped-form tolerance must not match ordinary ``[[text]]``
    that lacks a ``CITE…:`` prefix (no false positives)."""
    src = 'see [link](#eq-x) and a [[wiki style]] note'
    assert postprocess.decode_natbib_markers(src) == src


def test_textual_cite_in_mid_sentence_with_following_clause():
    """Common shape: ``..., per @KEY, the next ...`` — comma must
    terminate the key cleanly on both sides."""
    src = 'The seminal work, per @Smith2020, established this.'
    out = postprocess.convert_citations(src)
    assert ', per {cite:t}`Smith2020`, established this.' in out
