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
    r"""``foo@example.com`` is an email address, not a citation. The
    lookbehind on ``(?<![\`\[@])`` doesn't cover this case (the
    char before ``@`` is a letter), but the boundary on a period or
    other domain-character would terminate the match at the wrong
    place. Documented as a known limitation."""
    # Today's behaviour: the @ followed by alpha-num matches and
    # captures up to the next non-key char. ``example`` becomes a
    # bogus cite. This test locks the current behaviour so a future
    # narrow-the-cite-regex change is visible — it's a *known
    # imperfection* the validator (P1a) catches via cross-ref
    # resolution.
    src = 'Contact me at foo@example.com'
    out = postprocess.convert_citations(src)
    # Current behaviour: ``@example`` is treated as a cite.
    assert '{cite:t}`example`' in out


@pytest.mark.parametrize("marker_role,decoded_role", [
    ('CITEP',       'cite:p'),
    ('CITEALP',     'cite:t'),
    ('CITEALT',     'cite:t'),
    ('CITEAUTHOR',  'cite:author'),
    ('CITEYEAR',    'cite:year'),
])
def test_natbib_marker_decoded_to_role(marker_role: str, decoded_role: str):
    """The natbib bracket markers (emitted by preprocess for natbib
    variants pandoc collapses ambiguously) decode to the right
    ``{cite:*}`` role. Lesson 020."""
    src = f'Per \\[\\[{marker_role}:smith2020\\]\\] we have.'
    out = postprocess.decode_natbib_markers(src)
    assert '{' + decoded_role + '}`smith2020`' in out


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


def test_textual_cite_in_mid_sentence_with_following_clause():
    """Common shape: ``..., per @KEY, the next ...`` — comma must
    terminate the key cleanly on both sides."""
    src = 'The seminal work, per @Smith2020, established this.'
    out = postprocess.convert_citations(src)
    assert ', per {cite:t}`Smith2020`, established this.' in out
