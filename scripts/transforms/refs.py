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

from conversion_context import current_context
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
    ('Appendix',     'c-'),
    ('Appendices',   'c-'),
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
    # Figures route to ``{numref}`` (renders "Figure N"), so the prose
    # "Figure" before the ref double-counts — "Figure Figure 1.1" (#110).
    ('Figure',       'f-'),
    ('Figures',      'f-'),
    ('Figure',       'fig-'),
    ('Figures',      'fig-'),
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
    # Tables route to ``{numref}`` (renders "Table N") just like figures,
    # so prose "Table~\ref{tab:…}" doubles to "Table Table N" (#131).
    # Both default table prefixes (``tab-``/``tbl-``) are covered,
    # mirroring the Figure ``f-``/``fig-`` pair.
    ('Table',        'tab-'),
    ('Tables',       'tab-'),
    ('Table',        'tbl-'),
    ('Tables',       'tbl-'),
    ('Remark',       'r-'),
    ('Remarks',      'r-'),
    ('Theorem',      't-'),
    ('Theorems',     't-'),
]


# Each tuple maps a set of label-prefix families to a MyST role. The
# prefix list is uniform across colon-form (``eq:``) and hyphen-form
# (``eq-``) so ``routing_role`` works regardless of whether the label
# arrives as raw pandoc output (colon-form) or post-``convert_label_colons``
# (hyphen-form). Callers used to need to pick the form carefully —
# don't anymore.
_DEFAULT_CROSS_REF_ROUTING: list[tuple[tuple[str, ...], str]] = [
    (('eq:', 'eq-'),                                'eq'),
    (('f:', 'f-', 'fig:', 'fig-'),                  'numref'),
    (('tab:', 'tab-', 'tbl:', 'tbl-'),              'numref'),
    # Code-block listings (``{code-block}`` with ``:name: list-…``) are
    # enumerable; ``{numref}`` lets MyST render the auto-counter (default
    # "Program N") rather than dumping the caption inline (issue #8).
    (('list:', 'list-'),                            'numref'),
    # Theorem-like family. ``alg:`` / ``algo:`` target ``prf:algorithm``
    # (book-dp1 convention `\label{algo:foo}` → `algo-foo`). ``eg:``
    # targets ``prf:example``. Both full-word forms were missed by the
    # original short-form abbreviations — issue #9.
    (('t:',    't-',
      'thm:',  'thm-',
      'l:',    'l-',
      'lem:',  'lem-',
      'p:',    'p-',
      'pr:',   'pr-',
      'prop:', 'prop-',
      'd:',    'd-',
      'def:',  'def-',
      # ``c:`` / ``c-`` historically routed to ``prf:ref`` (corollary
      # shorthand). Books using ``c:`` for chapter should override via
      # ``cross_ref_routing:`` config.
      'c:',    'c-',
      'cor:',  'cor-',
      'ex:',   'ex-',
      'r:',    'r-',
      'rem:',  'rem-',
      'a:',    'a-',
      'as:',   'as-',
      'alg:',  'alg-',  'algo:', 'algo-',
      'eg:',   'eg-'),                              'prf:ref'),
    (('s:',   's-',
      'ss:',  'ss-',
      'sss:', 'sss-',
      'sec:', 'sec-',
      'ch:',  'ch-'),                               'ref'),
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


# Prose nouns before ``{ref}``-routed section targets (#150). Under
# qe-v5 book-mode numbering (same premise as
# ``strip_doubled_section_symbol``), a ``{ref}`` to a numbered heading
# auto-renders "Section X.Y", so prose ``Section~\ref{s:fps}`` doubles
# to "Section Section 1.2". These targets route to plain ``{ref}`` (see
# ``_DEFAULT_CROSS_REF_ROUTING``), so the ``{prf:ref}``/``{numref}``
# table above can never fire on them. Kept as a separate hard-coded
# family — tying the noun to the ``ref`` role only here avoids
# over-stripping when a book reroutes a theorem-style prefix to
# ``{ref}`` (where the ref renders the target title and the prose noun
# is needed).
#
# ``Chapter``/``ch-`` is deliberately absent from the *built-in* table:
# under qe-v5 ``injectBookSectionDefaults`` (``numbering.heading_2``..
# ``heading_6`` only, lesson 016) a ``{ref}`` to a chapter-level heading
# renders the chapter *title*, so the prose noun isn't doubled and must
# stay (the ``table_caption_with_inline_role_backticks`` golden pins this).
# But under qe-v8 ``numbering.book.enabled`` + ``chapters.label: "Chapter
# %s"`` the same ``{ref}`` renders "Chapter N", so ``Chapter {ref}`ch-x```
# doubles to "Chapter Chapter N" (#184). Whether that holds depends on the
# book's ``myst.yml`` numbering mode — which the converter can't know
# unilaterally — so Chapter is opt-in per book via a ``doubled_noun_refs``
# entry carrying ``role: ref`` (``ctx.doubled_section_noun_refs``), never a
# built-in default here.
_DOUBLED_SECTION_NOUN_REFS = [
    ('Section',  ('s-', 'ss-', 'sss-', 'sec-')),
    ('Sections', ('s-', 'ss-', 'sss-', 'sec-')),
]


def routing_role(target: str, ctx=None) -> str:
    """Return the MyST role name (``eq`` / ``numref`` / ``prf:ref`` /
    ``ref``) for a label, honouring per-book extras from
    ``ctx.cross_ref_routing``.

    Single source of truth for label-prefix → role mapping. Callers
    compose the role name with the directive syntax themselves —
    e.g. ``'{' + routing_role(label) + '}`' + label + '`'``. Used by
    ``convert_cross_references`` for body refs and by
    ``transforms.figures.extract_caption`` for HTML caption refs
    (closes the directive-type-mismatch class of bugs, GH #38).

    The target string may carry either the source ``thm:foo`` shape
    or the converted ``thm-foo`` shape — both are recognised by the
    default routing table. ``ctx`` defaults to the current context
    (Phase 3) so existing callers without a ctx keep working.
    """
    ctx = ctx if ctx is not None else current_context()
    extras = ctx.cross_ref_routing
    for prefixes, role in extras + _DEFAULT_CROSS_REF_ROUTING:
        if target.startswith(prefixes):
            return role
    return 'ref'


def convert_cross_references(text: str, ctx=None) -> str:
    """Convert pandoc cross-reference syntax to MyST.

    Patterns:
    - [display](#target){reference-type="eqref" reference="target"} → {eq}`target`
    - [display](#target){reference-type="ref+label" reference="target"} → {ref/numref/prf:ref}`target`
    - [display](#target){reference-type="ref" reference="target"} → {ref}`target`
    """
    ctx = ctx if ctx is not None else current_context()

    def make_ref(target):
        """Generate the appropriate MyST ref role for a single target.
        Routing is delegated to ``routing_role`` (module-level) so the
        same prefix→role table services both body and caption refs.

        A ref to a *secondary* heading label is rewritten to the primary
        (#108): mystmd keeps only one ``(name)=`` anchor per heading
        ("label X replaced with Y"), so the secondary has no target of its
        own — the alias map (scanned from the sources at config time)
        redirects the ref so it renders the real section number."""
        target_converted = convert_label_colons(target)
        target_converted = ctx.heading_label_aliases.get(
            target_converted, target_converted
        )
        return '{' + routing_role(target_converted, ctx) + '}`' + target_converted + '`'

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
    #
    # The opening ``[`` must NOT be backslash-escaped (``(?<!\\)``): a literal
    # LaTeX bracket run — e.g. ``[Hint: … \cref{c:supineq}]`` — reaches pandoc
    # as ``\[Hint: … [\[c:supineq\]](#c:supineq){…}.\]``. Without the
    # lookbehind the match starts at the escaped ``\[Hint`` bracket and
    # swallows "Hint: …" as discarded display text, leaving a stranded
    # ``\{prf:ref}`` (escaped brace → literal) and a dangling ``]`` (#158B).
    # Pandoc only escapes *literal* brackets; a real cross-ref link opener is
    # always an unescaped ``[``, so the lookbehind never blocks a true match.
    text = re.sub(
        r'(?<!\\)\[([^\]\n$]*(?:\\\][^\]\n$]*)*)\]\(#([^)\n]+)\)\{reference-type="([^"]+)"(?:\s+reference="[^"]*")?\}',
        replace_ref,
        text
    )

    return text


def strip_doubled_noun_refs(text: str, ctx=None) -> str:
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

    Also handles the ``{ref}``-routed section family (#150): prose
    ``Section``/``Sections`` before a ``{ref}`` to a section-style label
    doubles under qe-v5 book-mode heading numbering, which auto-renders
    "Section X.Y". These pairs live in ``_DOUBLED_SECTION_NOUN_REFS``
    and match the ``ref`` role only. A book can extend this ``ref``-role
    family from config — a ``doubled_noun_refs`` entry with ``role: ref``
    lands in ``ctx.doubled_section_noun_refs``. That is how ``Chapter``/
    ``ch-`` opts in for a book under qe-v8 ``numbering.book`` mode, where a
    chapter ``{ref}`` renders "Chapter N" and ``Chapter {ref}`ch-x``` would
    otherwise double to "Chapter Chapter N" (#184).

    Matches either a regular space or a non-breaking space (U+00A0) between
    the noun and the ref, since pandoc emits NBSP for LaTeX ``~`` ties.

    Reads ``ctx.doubled_noun_refs`` / ``ctx.doubled_section_noun_refs``
    (Phase 3); falls back to the current context when called without an
    explicit ``ctx``.
    """
    ctx = ctx if ctx is not None else current_context()
    extras = ctx.doubled_noun_refs

    for noun, prefix in extras + _DOUBLED_NOUN_REFS:
        # Negative lookbehind on a word char so we don't strip inside a longer
        # word (e.g. avoid touching a hypothetical "Subtheorem").
        #
        # An optional ``§`` between the noun and the ref is also swallowed:
        # authors write ``Appendix~\S\ref{c:areal}`` (pandoc → "Appendix
        # §{role}`c-areal`"), but the role already auto-renders "Appendix A",
        # so both the prose noun and the stray section symbol are redundant
        # (#110).
        text = re.sub(
            rf'(?<!\w){re.escape(noun)}[ \xa0]+(?:§[ \xa0]*)?'
            rf'(\{{(?:prf:ref|numref)\}}`{re.escape(prefix)}[^`]+`)',
            r'\1',
            text,
        )

    # Section/chapter nouns before plain {ref} targets (#150, #184). Same
    # separator and optional-§ handling as above, but matching the
    # ``ref`` role only — see _DOUBLED_SECTION_NOUN_REFS for why the
    # role is constrained per noun family. Per-book extras
    # (``ctx.doubled_section_noun_refs``, e.g. ``Chapter``/``ch-`` for a
    # book under qe-v8 book-mode numbering) extend the built-in list.
    for noun, prefixes in ctx.doubled_section_noun_refs + _DOUBLED_SECTION_NOUN_REFS:
        alternation = '|'.join(re.escape(p) for p in prefixes)
        text = re.sub(
            rf'(?<!\w){re.escape(noun)}[ \xa0]+(?:§[ \xa0]*)?'
            rf'(\{{ref\}}`(?:{alternation})[^`]+`)',
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
