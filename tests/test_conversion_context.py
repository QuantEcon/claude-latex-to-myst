"""Phase 3 reentrancy proofs for ``ConversionContext`` (see
``notes/design/phase-3-conversion-context.md``).

The whole point of threading state through a context instead of mutating
module globals is that two books can convert in one process without one
freezing or bleeding into the other — the thing lesson 038's global-state
singleton made impossible. These tests assert exactly that.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import postprocess  # noqa: E402
from conversion_context import ConversionContext  # noqa: E402


def _ctx(**config) -> ConversionContext:
    base = {'source_dir': '.'}
    base.update(config)
    return ConversionContext.from_config(base)


def test_two_books_one_process_do_not_bleed():
    """Two configs converted in one process, each with explicit ctx, produce
    their own config's output — and interleaving doesn't corrupt either."""
    # Book A: a custom env ``ClaimA`` → prf:theorem, standalone frontmatter.
    ctx_a = _ctx(extra_environments={'ClaimA': 'prf:theorem'},
                 frontmatter_style='standalone')
    # Book B: a custom env ``ClaimB`` → prf:lemma, absorbed frontmatter.
    ctx_b = _ctx(extra_environments={'ClaimB': 'prf:lemma'},
                 frontmatter_style='absorbed')

    src_a = '::: ClaimA\nA claim.\n:::\n'
    src_b = '::: ClaimB\nA claim.\n:::\n'

    out_a1 = postprocess.process_text(src_a, stem='ch_a', title='A', ctx=ctx_a)
    out_b = postprocess.process_text(src_b, stem='ch_b', title='B', ctx=ctx_b)
    # Re-run A after B: must be identical to the first A run (no B bleed).
    out_a2 = postprocess.process_text(src_a, stem='ch_a', title='A', ctx=ctx_a)

    assert out_a1 == out_a2, 'book A output changed after converting book B'
    # A's env maps to theorem; B's to lemma — each only knows its own env.
    assert '{prf:theorem}' in out_a1
    assert '{prf:lemma}' in out_b
    assert '{prf:lemma}' not in out_a1
    assert '{prf:theorem}' not in out_b
    # Frontmatter style differs per book: standalone leaves a ``# Title``
    # heading in the body (no YAML); absorbed pulls it into a YAML block.
    assert out_a1.lstrip().startswith('# A'), 'book A should use standalone heading'
    assert not out_a1.lstrip().startswith('---'), 'book A should have no YAML block'
    assert out_b.lstrip().startswith('---'), 'book B should use absorbed YAML'


def test_from_config_contexts_are_independent():
    """Building a second context must not share mutable maps with the first
    (the lesson-038 frozen-singleton class)."""
    ctx_a = _ctx(extra_environments={'OnlyA': 'prf:remark'})
    ctx_b = _ctx()
    assert 'OnlyA' in ctx_a.env_map
    assert 'OnlyA' not in ctx_b.env_map
    # Mutating one does not touch the other.
    ctx_a.tikz_figure_map['x'] = ('a.svg', None)
    assert ctx_b.tikz_figure_map == {}
    ctx_a.env_map is not ctx_b.env_map


def test_exercise_counter_does_not_bleed_across_files():
    """The per-file exercise numbering resets at each ``process_text`` —
    auto-labels restart per chapter, and converting a second chapter never
    continues the first's counter (FileCounters.reset_for)."""
    ctx = _ctx()
    two_ex = '::: Exercise\nFirst.\n:::\n\n::: Exercise\nSecond.\n:::\n'

    out1 = postprocess.process_text(two_ex, stem='ch_one', title='One', ctx=ctx)
    out2 = postprocess.process_text(two_ex, stem='ch_two', title='Two', ctx=ctx)

    # Each chapter numbers its own exercises from 1, prefixed by its own stem.
    assert 'ex-one-auto-1' in out1
    assert 'ex-one-auto-2' in out1
    assert 'ex-two-auto-1' in out2
    assert 'ex-two-auto-2' in out2
    # No bleed: chapter two does not carry chapter one's prefix or continue
    # its counter (no ex-one-auto-3 / ex-two-auto-3).
    assert 'ex-one' not in out2
    assert 'ex-two-auto-3' not in out2
    assert 'ex-one-auto-3' not in out1


def test_apply_config_registers_current_context():
    """``apply_config`` returns the context and registers it as current, so
    the legacy ``postprocess.<global>`` proxy and no-ctx transform calls see
    this book's state."""
    from conversion_context import current_context
    ctx = postprocess.apply_config(
        {'source_dir': '.', 'extra_environments': {'Widget': 'prf:definition'}}
    )
    assert current_context() is ctx
    # The backward-compat proxy reflects the registered context.
    assert postprocess.ENV_MAP['Widget'] == 'prf:definition'


# ── doubled_noun_refs role: ref (chapter-ref doubling, #184) ─────────────────


def test_doubled_noun_refs_default_role_targets_prf_numref():
    """A doubled_noun_refs entry with no explicit role keeps the historical
    behaviour: it lands in ``doubled_noun_refs`` (the {prf:ref}/{numref}
    matcher), not the {ref}-role section table."""
    ctx = _ctx(doubled_noun_refs=[{'noun': 'Algorithm', 'prefix': 'alg-'}])
    assert ('Algorithm', 'alg-') in ctx.doubled_noun_refs
    assert ctx.doubled_section_noun_refs == []


def test_doubled_noun_refs_role_ref_targets_section_table():
    """``role: ref`` routes the entry to ``doubled_section_noun_refs`` (the
    plain {ref} matcher) so Chapter/Chapters can opt in for a book under
    qe-v8 numbering.book mode (#184)."""
    ctx = _ctx(doubled_noun_refs=[
        {'noun': 'Chapter',  'prefix': 'ch-', 'role': 'ref'},
        {'noun': 'Chapters', 'prefix': 'ch-', 'role': 'ref'},
    ])
    assert ctx.doubled_noun_refs == []
    assert ('Chapter', ('ch-',)) in ctx.doubled_section_noun_refs
    assert ('Chapters', ('ch-',)) in ctx.doubled_section_noun_refs


def test_doubled_noun_refs_bad_role_rejected():
    import pytest
    with pytest.raises(SystemExit):
        _ctx(doubled_noun_refs=[{'noun': 'X', 'prefix': 'x-', 'role': 'bogus'}])


def test_strip_chapter_noun_ref_with_role_ref_ctx():
    """End-to-end: with the Chapter/ch- role:ref opt-in, prose 'Chapter
    {ref}`ch-x`' (and the ~-tie NBSP form) is de-doubled; a genuine section
    ref and an unrelated longer word are left alone."""
    ctx = _ctx(doubled_noun_refs=[
        {'noun': 'Chapter',  'prefix': 'ch-', 'role': 'ref'},
        {'noun': 'Chapters', 'prefix': 'ch-', 'role': 'ref'},
    ])
    assert postprocess.strip_doubled_noun_refs(
        'proceed to Chapter\xa0{ref}`ch-deqn`, where', ctx
    ) == 'proceed to {ref}`ch-deqn`, where'
    assert postprocess.strip_doubled_noun_refs(
        'Chapters {ref}`ch-a`–{ref}`ch-b`', ctx
    ) == '{ref}`ch-a`–{ref}`ch-b`'
    # Word-boundary guard: 'Subchapter' must not be truncated to 'Sub'.
    assert postprocess.strip_doubled_noun_refs(
        'Subchapter {ref}`ch-deqn`', ctx
    ) == 'Subchapter {ref}`ch-deqn`'
    # Without the opt-in, the built-in table leaves Chapter alone.
    assert postprocess.strip_doubled_noun_refs(
        'Chapter {ref}`ch-deqn`', _ctx()
    ) == 'Chapter {ref}`ch-deqn`'
