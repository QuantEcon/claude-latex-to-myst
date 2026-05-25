"""Cross-reference and ref-cleanup transforms.

Converts pandoc cross-ref syntax to MyST roles (``{ref}``, ``{eq}``,
``{numref}``, ``{prf:ref}``); strips prose nouns that MyST/sphinx-proof
auto-render (lesson 011), drops the literal ``§`` before section-family
refs (lesson 016), removes unresolvable footnote refs (lesson 013).

State coupling: the routing tables and doubled-noun list have a
mutable "extras" half populated by ``apply_config`` from
``cross_ref_routing`` / ``doubled_noun_refs`` in config.yaml. The
extras live as module-level state on ``postprocess`` — late-import
inside the function avoids the circular-import that would otherwise
happen at package load (P3a / P1b).
"""

from __future__ import annotations

import re

from ._helpers import convert_label_colons


# Default English noun-prefix pairs for ``strip_doubled_noun_refs``.
# Books with custom theorem classes extend via ``doubled_noun_refs``
# in config.yaml.
#
# Plural forms are listed alongside singulars so prose like
# ``Chapters {prf:ref}`c-X` and {prf:ref}`c-Y```` (sphinx-proof renders
# each ref as "Chapter N") also gets de-doubled. Multi-target shapes
# (range/list separators) don't need extra handling: only the leading
# plural-noun token is redundant; the refs between separators have no
# intervening noun for sphinx-proof to collide with.
_DOUBLED_NOUN_REFS = [
    ('Algorithm',    'algo-'),
    ('Algorithms',   'algo-'),
    ('Assumption',   'a-'),
    ('Assumptions',  'a-'),
    ('Chapter',      'c-'),
    ('Chapters',     'c-'),
    ('Corollary',    'c-'),
    ('Corollaries',  'c-'),
    ('Example',      'eg-'),
    ('Examples',     'eg-'),
    ('Exercise',     'ex-'),
    ('Exercises',    'ex-'),
    ('Lemma',        'l-'),
    ('Lemmas',       'l-'),
    # Code-block listings: authors typically write "Listing X" in
    # prose, but MyST's default kind name for code-blocks is "Program",
    # so a ``{numref}`list-foo``` renders as "Program N". Strip both
    # noun forms (Listing/Program — singular and plural) so the
    # rendered text isn't doubled. Project-level "Listing N" wording
    # is configured in ``myst.yml``, not here.
    ('Listing',      'list-'),
    ('Listings',     'list-'),
    ('Program',      'list-'),
    ('Programs',     'list-'),
    ('Proposition',  'p-'),
    ('Propositions', 'p-'),
    ('Remark',       'r-'),
    ('Remarks',      'r-'),
    ('Theorem',      't-'),
    ('Theorems',     't-'),
]


_DEFAULT_CROSS_REF_ROUTING: list[tuple[tuple[str, ...], str]] = [
    (('eq:', 'eq-'),                                'eq'),
    (('f:', 'fig:'),                                'numref'),
    (('tab:', 'tbl:'),                              'numref'),
    # Code-block listings (``{code-block}`` with ``:name: list-…``) are
    # enumerable; ``{numref}`` lets MyST render the auto-counter (default
    # "Program N") rather than dumping the caption inline (issue #8).
    (('list:', 'list-'),                            'numref'),
    # Theorem-like family. ``alg:`` / ``algo:`` target ``prf:algorithm``
    # (book-dp1 convention `\label{algo:foo}` → `algo-foo`). ``eg:``
    # targets ``prf:example``. Both full-word forms were missed by the
    # original short-form abbreviations — issue #9.
    (('t:', 'thm:', 'l:', 'lem:', 'p:', 'pr:', 'prop:',
      'd:', 'def:', 'c:', 'cor:', 'ex:', 'r:', 'rem:',
      'a:', 'as:',
      'alg:', 'algo:', 'algo-',
      'eg:', 'eg-'),                                'prf:ref'),
    (('s:', 'ss:', 'sss:', 'sec:', 'ch:', 'c-', 'c:'), 'ref'),
]


# Label-prefix families for which qe-v5 auto-renders a noun ("Section
# X.Y" / "Paragraph X.Y" / "Example X.Y") before the ref. Authors
# sometimes prefix the ref with a literal ``§`` (LaTeX's ``\S``); the
# combination renders as "§ Section X.Y" / "§ Example X.Y" which
# double-counts the noun.
#
# Mostly section-style prefixes, plus ``eg-`` after a dp2 instance of
# the author writing ``\S\ref{eg:foo}`` (semantic mismatch — `\S` is the
# section symbol, but they pointed it at an example). See lesson 016.
_DOUBLED_SECTION_SYMBOL_PREFIXES = ('s-', 'ss-', 'sss-', 'sec-', 'eg-')


def convert_cross_references(text: str) -> str:
    """Convert pandoc cross-reference syntax to MyST.

    Patterns:
    - [display](#target){reference-type="eqref" reference="target"} → {eq}`target`
    - [display](#target){reference-type="ref+label" reference="target"} → {ref/numref/prf:ref}`target`
    - [display](#target){reference-type="ref" reference="target"} → {ref}`target`
    """
    # Late-import the mutable extras (populated by apply_config).
    import postprocess
    extras = postprocess._EXTRA_CROSS_REF_ROUTING

    def make_ref(target):
        """Generate the appropriate MyST ref role for a single target.

        Routing rules come from ``_EXTRA_CROSS_REF_ROUTING`` (per-book
        config) merged with ``_DEFAULT_CROSS_REF_ROUTING`` (built-ins).
        First match wins; falls back to ``{ref}`` for unrecognised
        prefixes."""
        target_converted = convert_label_colons(target)
        for prefixes, role in extras + _DEFAULT_CROSS_REF_ROUTING:
            if target.startswith(prefixes):
                return '{' + role + '}`' + target_converted + '`'
        return '{ref}`' + target_converted + '`'

    def replace_ref(m):
        display = m.group(1)  # not used — MyST generates its own display
        target = m.group(2)
        ref_type = m.group(3)

        if ref_type == 'eqref':
            target_converted = convert_label_colons(target)
            return '{eq}`' + target_converted + '`'

        # Handle comma-separated targets: \cref{a,b} → {role}`a` and {role}`b`
        if ',' in target:
            parts = [t.strip() for t in target.split(',')]
            return ' and '.join(make_ref(p) for p in parts)

        return make_ref(target)

    # Match [display](#target){reference-type="type" reference="ref"}
    # Pandoc escapes brackets in display text: [\[eq:firec\]]
    # Also handle ref+Label (capital L variant)
    # IMPORTANT: Use [^\]\n$] (not [^\]]) to prevent matching across lines
    # or through math boundaries — otherwise [0,1) in math could pair with
    # a cross-ref many characters later on the same line.
    text = re.sub(
        r'\[([^\]\n$]*(?:\\\][^\]\n$]*)*)\]\(#([^)\n]+)\)\{reference-type="([^"]+)"(?:\s+reference="[^"]*")?\}',
        replace_ref,
        text
    )

    return text


def strip_doubled_noun_refs(text: str) -> str:
    """Drop the prose noun before a MyST ref that auto-expands to that noun.

    Sphinx-proof renders ``{prf:ref}`t-foo``` as "Theorem 1.2", so prose like
    "Theorem {prf:ref}`t-foo`" renders as "Theorem Theorem 1.2". LaTeX writers
    ubiquitously prefix the noun before ``\\cref{...}`` because LaTeX's cref
    doesn't always auto-name; in MyST it always does, so the noun must go.

    Handles both ``{prf:ref}`` (sphinx-proof directives — theorem, lemma,
    algorithm, exercise, …) and ``{numref}`` (enumerable directives —
    code-block listings render as "Program N" by default). The prefix
    match in ``_DOUBLED_NOUN_REFS`` ensures only related noun/role
    combinations get rewritten.

    Matches either a regular space or a non-breaking space (U+00A0) between
    the noun and the ref, since pandoc emits NBSP for LaTeX ``~`` ties.
    """
    # Late-import the mutable extras.
    import postprocess
    extras = postprocess._EXTRA_DOUBLED_NOUN_REFS

    for noun, prefix in extras + _DOUBLED_NOUN_REFS:
        # Negative lookbehind on a word char so we don't strip inside a longer
        # word (e.g. avoid touching a hypothetical "Subtheorem").
        text = re.sub(
            rf'(?<!\w){re.escape(noun)}[ \xa0]+'
            rf'(\{{(?:prf:ref|numref)\}}`{re.escape(prefix)}[^`]+`)',
            r'\1',
            text,
        )
    return text


def strip_doubled_section_symbol(text: str) -> str:
    """Drop a literal ``§`` before a ``{ref}`` to a section-style label.

    Under qe-v5 book-mode (``injectBookSectionDefaults`` enables
    ``numbering.heading_2.enabled``..``heading_6.enabled``), refs to
    headings render as "Section X.Y" / "Paragraph X.Y". LaTeX writers
    ubiquitously prefix ``\\S`` (or ``§``) before ``\\ref{ss:foo}`` to
    provide the noun manually, which then double-counts.

    Parallel to ``strip_doubled_noun_refs`` for theorem-style nouns
    (lesson 011); applies after ``convert_cross_references`` so the
    target syntax is already in MyST form.
    """
    pattern = re.compile(
        r'(?<!\w)§[ \xa0]*'
        r'(\{ref\}`(?:'
        + '|'.join(re.escape(p) for p in _DOUBLED_SECTION_SYMBOL_PREFIXES)
        + r')[^`]+`)'
    )
    return pattern.sub(r'\1', text)


def strip_footnote_refs(text: str) -> str:
    """Remove ``{ref}`fn-...``` cross-references that MyST cannot resolve.

    MyST footnote anchors (``[^1]: ...``) live in a separate identifier
    namespace from the cross-reference system, so ``{ref}`fn-NAME``` always
    fails to resolve. Drop the unresolvable role and replace the phrase with
    "the previous footnote", preserving the original LaTeX target in an HTML
    comment for round-trip inspection.
    """
    pattern = re.compile(r'\bfootnote\s+\{ref\}`fn-([A-Za-z0-9_-]+)`')

    def repl(m: re.Match) -> str:
        name = m.group(1)
        original = name.replace('-', ':')
        return f'the previous footnote <!-- LaTeX-source: \\ref{{fn:{original}}} -->'

    return pattern.sub(repl, text)
