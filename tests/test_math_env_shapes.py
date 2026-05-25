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
