"""Shape catalogue: math environments × label-position variants.

Sibling-parity guard for the family of math env handlers. Issues
#26 / #30 / #37 all had the same shape of bug, surfaced one env at
a time across three months: ``\\label{}`` outside the leading
position was not extracted. This file exercises every (env × shape)
combination so a future bug in one is caught against all siblings.

The handlers themselves are in ``postprocess.convert_equations``;
see lessons 024, 032, 037.
"""

from __future__ import annotations

import re

import pytest

import postprocess


# Math env families currently handled by ``convert_equations``.
ENVS = ['equation', 'align', 'multline', 'gather']

# Label-position shapes. Some combinations are vacuous (per_row makes
# no sense for ``equation`` — single line) and excluded below.
SHAPES = [
    'no_label',
    'label_after_begin',     # \label{} immediately after \begin{X}
    'label_mid_body',        # \label{} between expression lines
    'label_at_end',          # \label{} on last line before \end{X}
    'label_per_row',         # one \label{} per ``\\``-separated row
]


def _per_row_meaningful(env: str) -> bool:
    """Per-row labels only make sense for multi-line align/gather.
    Equation is single-line; multline is conceptually one equation
    even if it wraps."""
    return env in ('align', 'gather')


def _wrap(env: str, body: str) -> str:
    """Wrap a body in the pandoc-shape ``$$\\begin{ENV}…\\end{ENV}$$``."""
    return '$$\\begin{' + env + '}\n' + body + '\n\\end{' + env + '}$$\n'


def _build_source(env: str, shape: str) -> tuple[str, list[str]]:
    """Build a pandoc-shape ``$$\\begin{ENV}...\\end{ENV}$$`` snippet.
    Returns ``(source, labels)`` where ``labels`` is the list of
    label names that should resolve to anchors in the output."""
    if shape == 'no_label':
        if env == 'equation':
            body = 'x = y'
        elif env == 'multline':
            body = 'a + b\\\\\n+ c = d'
        elif env == 'align':
            body = 'a &= 1\\\\\nb &= 2'
        else:  # gather
            body = 'a = 1\\\\\nb = 2'
        return _wrap(env, body), []

    if shape == 'label_after_begin':
        labels = ['eq:foo']
        if env == 'equation':
            body = '\\label{eq:foo}\nx = y'
        elif env == 'multline':
            body = '\\label{eq:foo}\na + b\\\\\n+ c = d'
        elif env == 'align':
            body = '\\label{eq:foo}\na &= 1\\\\\nb &= 2'
        else:  # gather
            body = '\\label{eq:foo}\na = 1\\\\\nb = 2'

    elif shape == 'label_mid_body':
        labels = ['eq:foo']
        if env == 'equation':
            body = 'x \\label{eq:foo} = y'
        elif env == 'multline':
            body = 'a + b \\label{eq:foo}\\\\\n+ c = d'
        elif env == 'align':
            body = 'a &= 1 \\label{eq:foo}\\\\\nb &= 2'
        else:  # gather
            body = 'a = 1 \\label{eq:foo}\\\\\nb = 2'

    elif shape == 'label_at_end':
        labels = ['eq:foo']
        if env == 'equation':
            body = 'x = y\n\\label{eq:foo}'
        elif env == 'multline':
            body = 'a + b\\\\\n+ c = d\n\\label{eq:foo}'
        elif env == 'align':
            body = 'a &= 1\\\\\nb &= 2 \\label{eq:foo}'
        else:  # gather
            body = 'a = 1\\\\\nb = 2 \\label{eq:foo}'

    elif shape == 'label_per_row':
        labels = ['eq:a', 'eq:b']
        if env == 'align':
            body = 'a &= 1 \\label{eq:a}\\\\\nb &= 2 \\label{eq:b}'
        else:  # gather
            body = 'a = 1 \\label{eq:a}\\\\\nb = 2 \\label{eq:b}'
    else:
        raise ValueError(f'unknown shape: {shape}')

    return _wrap(env, body), labels


def _has_anchor(text: str, label: str) -> bool:
    """A label name resolves to an anchor in ``text`` if either:
    - ``(eq-X)=`` appears on its own line (stacked-anchor form, used
      by align extras / per-row), OR
    - ``$$ (eq-X)`` appears on its own line (trailing-paren form,
      used by equation / multline / leading-label align).
    """
    converted = label.replace(':', '-')
    if re.search(rf'^\({re.escape(converted)}\)=\s*$', text, re.MULTILINE):
        return True
    if re.search(rf'^\$\$\s+\({re.escape(converted)}\)\s*$', text, re.MULTILINE):
        return True
    return False


_CELLS = [
    (env, shape)
    for env in ENVS
    for shape in SHAPES
    if shape != 'label_per_row' or _per_row_meaningful(env)
]


@pytest.mark.parametrize("env,shape", _CELLS)
def test_math_env_shape(env: str, shape: str):
    """For every meaningful (env, shape) combination, the pipeline
    must:

    1. Emit a MyST anchor for every declared ``\\label{}`` (in either
       the trailing-paren or stacked-anchor form).
    2. Strip every ``\\label{}`` from the math body — KaTeX silently
       drops them otherwise, breaking ``\\eqref{}``.
    3. Preserve a distinguishing token from the math content (sanity
       guard — the regex should not be eating the body).
    """
    src, labels = _build_source(env, shape)
    out = postprocess.convert_equations(src)

    # (1) Every declared label has an anchor.
    for label in labels:
        assert _has_anchor(out, label), (
            f'env={env} shape={shape}: no MyST anchor found for {label!r}\n'
            f'output:\n{out}'
        )

    # (2) No surviving \label{} in the output.
    assert '\\label{' not in out, (
        f'env={env} shape={shape}: \\label{{}} survived into output\n'
        f'output:\n{out}'
    )

    # (3) Math content survives — pick a token unique to this body.
    if env == 'equation' and shape != 'label_after_begin':
        assert 'x' in out
    elif env == 'equation':
        # label_after_begin's body starts with \label, then x = y
        assert 'x = y' in out
    elif env == 'multline':
        assert '+ c = d' in out
    elif env in ('align', 'gather'):
        # both have a = 1 or a &= 1 depending on env
        assert '= 1' in out
        assert '= 2' in out


def test_labeled_align_star_anchor_not_fused_into_prose():
    """GH #48 — ``\\begin{align*}\\label{eq:foo}…\\end{align*}`` must emit a
    block-level ``(eq-foo)=`` anchor with surrounding blank lines, so MyST
    parses it as a block anchor rather than fusing it into the preceding
    paragraph (which would render the anchor as literal text and lose the
    cross-ref target)."""
    src = (
        'which in turn holds if and only if\n'
        '$$\\begin{align*}\\label{eq:vgctp}\n'
        'a &= b\\\\\n'
        'c &= d\n'
        '\\end{align*}$$\n'
    )
    out = postprocess.convert_equations(src)
    # The anchor must not be glued onto the prose line (no horizontal
    # whitespace between "if and only if" and "(eq-vgctp)=" — must be
    # separated by at least one newline).
    assert not re.search(r'if and only if[ \t]*\(eq-vgctp\)=', out), (
        f'anchor fused with prose:\n{out}'
    )
    # And it must be preceded by a blank line so MyST parses it as a
    # block-level anchor rather than inline text.
    assert re.search(r'\n\n\(eq-vgctp\)=', out), (
        f'expected block-isolated anchor:\n{out}'
    )


def test_labeled_align_extra_per_row_anchors_not_fused_into_prose():
    """Same fusion concern for the labeled-align (non-`*`) extra-anchor path:
    when ``\\begin{align}\\label{first}…\\label{second}\\end{align}``, the
    leading label becomes the trailing ``(first)``, and ``second`` stacks
    as an anchor above — which must also have blank-line isolation."""
    src = (
        'preceding prose\n'
        '$$\\begin{align}\\label{eq:first}\n'
        'a &= b \\label{eq:second}\\\\\n'
        'c &= d\n'
        '\\end{align}$$\n'
    )
    out = postprocess.convert_equations(src)
    assert not re.search(r'preceding prose[ \t]*\(eq-second\)=', out), (
        f'extra anchor fused with prose:\n{out}'
    )
    assert re.search(r'\n\n\(eq-second\)=', out), (
        f'expected block-isolated extra anchor:\n{out}'
    )


def test_split_align_leading_label_anchor_not_fused_into_prose():
    """Same fusion concern for #70's per-row split path: when an align
    body has 2+ per-row labels AND a leading ``\\begin{align}\\label{}``,
    the split path emits the leading label as a ``(name)=`` anchor
    above the first per-row block. That anchor must still be
    block-isolated (preceded by ``\\n\\n``) so it doesn't fuse into
    a preceding prose paragraph and silently break the outer
    ``{eq}``/``{ref}`` cross-reference.

    Surfaced by Copilot's review of PR #77."""
    src = (
        'introductory prose with no blank line\n'
        '$$\\begin{align}\\label{eq:outer}\n'
        'a &= b, \\label{eq:row_a}\\\\\n'
        'c &= d, \\label{eq:row_b}\n'
        '\\end{align}$$\n'
    )
    out = postprocess.convert_equations(src)
    # Leading anchor must not be glued onto the prose line.
    assert not re.search(r'no blank line[ \t]*\(eq-outer\)=', out), (
        f'leading anchor fused with prose:\n{out}'
    )
    # And the leading anchor must be preceded by ``\n\n`` so MyST
    # parses it as a block-level anchor.
    assert re.search(r'\n\n\(eq-outer\)=', out), (
        f'expected block-isolated leading anchor:\n{out}'
    )


def test_split_align_first_row_extras_anchor_not_fused_into_prose():
    """Defensive: the same split path also stacks extras for any row
    that carries 2+ labels. If the FIRST row's extras land before the
    first ``$$...$$`` block, they must be block-isolated too — same
    Copilot-flagged failure mode as the leading-label case."""
    src = (
        'introductory prose with no blank line\n'
        '$$\\begin{align}\n'
        'a &= b \\label{eq:row_a_primary}\\label{eq:row_a_extra}\\\\\n'
        'c &= d \\label{eq:row_b}\n'
        '\\end{align}$$\n'
    )
    out = postprocess.convert_equations(src)
    # The stacked extra anchor for row 0 must be block-isolated.
    assert re.search(r'\n\n\(eq-row_a_extra\)=', out), (
        f'expected block-isolated extra anchor on first row:\n{out}'
    )


def test_math_env_no_label_does_not_emit_spurious_anchors():
    """Regression guard: unlabelled envs must NOT produce a
    ``(eq-)=`` line. A bug that emits anchors for every block would
    pass shape-catalogue tests above but blow up cross-ref
    resolution."""
    for env in ENVS:
        src, _ = _build_source(env, 'no_label')
        out = postprocess.convert_equations(src)
        # No standalone-anchor lines anywhere.
        assert not re.search(r'^\(eq-\)=\s*$', out, re.MULTILINE)
        assert not re.search(r'^\$\$\s+\(\)\s*$', out, re.MULTILINE)


# ── \,^ → \,{}^ KaTeX spacing-superscript fix (issue #45) ────────────────────


@pytest.mark.parametrize("src,want", [
    # The canonical degrees-Celsius case (8 sites in the DL climate ch).
    (r'$T = 3\,^\circ\mathrm{C}$', r'$T = 3\,{}^\circ\mathrm{C}$'),
    (r'$2.5\,^\circ\mathrm{C}$',   r'$2.5\,{}^\circ\mathrm{C}$'),
    # The break is general to any superscript after \, — not just ^\circ.
    (r'$x\,^*$',                   r'$x\,{}^*$'),
    (r'$A\,^\dagger$',             r'$A\,{}^\dagger$'),
    (r'$M\,^\top$',                r'$M\,{}^\top$'),
    (r'$y\,^{2}$',                 r'$y\,{}^{2}$'),
])
def test_fix_spacing_superscript_inserts_empty_base(src, want):
    """``\\,^X`` → ``\\,{}^X`` gives the superscript an explicit empty
    base so KaTeX stops erroring with 'unknown type: internal' (#45)."""
    assert postprocess.fix_spacing_superscript(src) == want


def test_fix_spacing_superscript_is_idempotent():
    """``\\,{}^`` no longer contains ``\\,^`` — re-running is a no-op
    (the pipeline must stay re-runnable)."""
    once = postprocess.fix_spacing_superscript(r'$3\,^\circ\mathrm{C}$')
    assert postprocess.fix_spacing_superscript(once) == once


def test_fix_spacing_superscript_leaves_plain_constructs_untouched():
    """No ``\\,^`` sequence → unchanged. A thin space not followed by a
    superscript, and a superscript not preceded by a thin space, are
    both fine in KaTeX and must be left alone."""
    for src in (r'$a\,b$', r'$x^2$', r'$x^\circ$', r'$3\,\mathrm{C}$',
                'plain prose, no math'):
        assert postprocess.fix_spacing_superscript(src) == src
