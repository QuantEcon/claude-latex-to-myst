#!/usr/bin/env python3
"""Structural validation: counts in LaTeX source vs MyST output.

Checks that conversion didn't silently drop equations, theorems, figures,
cross-references, or citations. Reports any per-chapter mismatch.

Usage:
    validate.py --config path/to/config.yaml
"""

import argparse
import re
import sys
from pathlib import Path

from _config import load


def _strip_latex_comments(text: str) -> str:
    """Drop whole-line LaTeX comments (a line whose first non-whitespace
    char is ``%``). Mid-line trailing comments are left alone so a line
    like ``\\begin{lemma} % TODO`` still counts the env. GH #14.
    """
    return re.sub(r'(?m)^[ \t]*%.*$', '', text)


# Markers the preprocessors leave in the source they hand to pandoc. For a
# book that uses ``preprocess.split:`` (e.g. Deep-Learning), ``validate`` reads
# this *preprocessed tmp* file — where ``\begin{figure}`` / ``\cite…`` have
# already been replaced by markers. Counting only the raw LaTeX would then
# under-count every marker-ized construct (figures dropping to 0, ~half the
# citations invisible), a pure measurement artifact. So count the markers too.
_FIGURE_MARKER_RE = re.compile(r'<!--FIGURE\s+payload=([A-Za-z0-9+/=]+)-->')
_CITE_MARKER_RE = re.compile(r'\[\[CITE[A-Z]*:')


def _figure_marker_count(text: str) -> int:
    """Figures contributed by ``<!--FIGURE payload=…-->`` markers — decode each
    to honour subfigure expansion (N panels → N figures), else 1."""
    try:
        from transforms.figures_from_latex import decode_marker
    except Exception:
        # Can't decode → count each marker as one figure (still better than 0).
        return len(_FIGURE_MARKER_RE.findall(text))
    n = 0
    for b64 in _FIGURE_MARKER_RE.findall(text):
        try:
            spec = decode_marker(b64)
            n += len(spec.subfigures) or 1
        except Exception:
            n += 1
    return n


def _count_figures_latex(text: str) -> int:
    """Count figures the pipeline will materialize on the MyST side.

    A ``\\begin{figure}`` block containing N ``\\begin{subfigure}`` blocks
    emits N ``{figure}`` directives (one per subfigure label, outer
    wrapper discarded). A ``\\begin{figure}`` with no subfigures emits
    one. GH #15. Figures already extracted to ``<!--FIGURE-->`` markers by
    the preprocessor (split-source books) are counted via the marker.
    """
    n = _figure_marker_count(text)
    for m in re.finditer(r'\\begin\{figure\}(.*?)\\end\{figure\}', text, flags=re.DOTALL):
        subs = len(re.findall(r'\\begin\{subfigure\}', m.group(1)))
        n += max(subs, 1)
    return n


def count_latex(text: str) -> dict:
    text = _strip_latex_comments(text)
    return {
        'equations':       len(re.findall(r'\\begin\{(equation|align|gather|multline)\*?\}', text)),
        'labeled_eqs':     len(re.findall(r'\\label\{eq:', text)),
        'theorems':        len(re.findall(r'\\begin\{(box)?(theorem|lemma|corollary|proposition|definition)\}', text)),
        'figures':         _count_figures_latex(text),
        # Match the full natbib family — every variant the pipeline
        # round-trips, with or without optional ``[prenote][postnote]``
        # args. The narrow ``\cite[pt]?{`` form caught only
        # ``\cite``/``\citet``/``\citep`` and missed
        # ``\citealp``/``\citealt``/``\citeauthor``/``\citeyear``/
        # ``\citeyearpar`` — each of which the pipeline converts to a
        # ``{cite:*}`` MyST role. The trailing ``{`` also has to allow
        # 0–2 optional bracket args between command and key, matching
        # ``_NATBIB_OPT`` in ``_apply_rewrites.py``; without that, any
        # cite written as ``\citep[see][ch. 2]{key}`` is under-counted
        # (1 instance in book-dp1, 1 in book-dp2, 28 in the
        # Deep_Learning corpus — #67's Copilot review).
        # Raw ``\cite…{`` commands PLUS natbib markers ``[[CITEP:…]]`` /
        # ``[[CITEALT:…]]`` that ``_apply_rewrites`` left in a split book's
        # preprocessed source (each marker is one citation command, decoded
        # to a ``{cite:*}`` role post-pandoc).
        'citations':       len(re.findall(
            r'\\cite[a-z]*(?:\s*\[[^\]]*\]){0,2}\s*\{', text
        )) + len(_CITE_MARKER_RE.findall(text)),
        'cross_refs':      len(re.findall(r'\\(cref|Cref|ref|eqref|autoref)\{', text)),
    }


def count_myst(text: str) -> dict:
    # An unlabeled equation block has two ``$$`` fence lines; a labeled
    # block has ``$$`` open + ``$$ (eq-foo)`` close, so the labeled
    # close doesn't match the bare-fence regex. Count both, then //2.
    # GH #16.
    bare_fence = len(re.findall(r'^\$\$\s*$', text, flags=re.MULTILINE))
    labeled_close = len(re.findall(r'^\$\$\s+\(eq-', text, flags=re.MULTILINE))
    # Starred (unnumbered) LaTeX display envs emit a ``{math}`` directive
    # with ``:enumerated: false`` instead of a bare ``$$`` block (#113) —
    # count those as equations too, else every starred env reads as a drop.
    math_directives = len(re.findall(r'^`{3,}\{math\}', text, flags=re.MULTILINE))
    return {
        'equations':       (bare_fence + labeled_close) // 2 + math_directives,
        'labeled_eqs':     labeled_close,
        'theorems':        len(re.findall(r'\{prf:(theorem|lemma|corollary|proposition|definition)\}', text)),
        'figures':         len(re.findall(r'\{figure\}', text)),
        # Match every ``{cite:*}`` role the pipeline emits — not just
        # ``{cite}`` / ``{cite:t}``. ``{cite:p}`` (from ``\citep``),
        # ``{cite:author}`` (from ``\citeauthor``), ``{cite:year}``
        # (from ``\citeyear`` / ``\citeyearpar`` / pandoc's ``[-@key]``)
        # were previously skipped, producing phantom validation
        # mismatches in every book that used those natbib variants (#67).
        'citations':       len(re.findall(r'\{cite(?::[a-z]+)?\}', text)),
        'cross_refs':      len(re.findall(r'\{(prf:)?(ref|eq|numref)\}', text)),
    }


# ── Cross-reference resolution check (P1a) ───────────────────────────────────
#
# Count-based validation (count_latex vs count_myst) catches gross drops but
# is blind to *name* mismatches: the source has 18 ``\label{eq:`` and the
# output has 18 ``(eq-``, counts match — but if one anchor was emitted as
# ``(eq-foo)=`` while a reference points at ``{eq}`eq-bar``, validation
# passes and the build silently produces a broken cross-reference.
#
# Every category-A regression in issues #30, #31, #33, #35, #37 escaped a
# clean count check and was caught only by a human reading the rendered
# HTML against the source PDF. This pass closes that gap.


# Anchor patterns. Each capture group 1 is the anchor name.
_ANCHOR_PATTERNS = [
    # ``(name)=`` standalone-target syntax (must be on its own line).
    re.compile(r'^\(([^)\s]+)\)=\s*$', re.MULTILINE),
    # ``:name: foo`` directive option (figures, code-blocks, prf blocks).
    re.compile(r'^\s*:name:\s+(\S+)\s*$', re.MULTILINE),
    # ``:label: foo`` (used by some prf directives).
    re.compile(r'^\s*:label:\s+(\S+)\s*$', re.MULTILINE),
    # Heading auto-ids: ``# Title {#slug}``. The slug is the first
    # whitespace-delimited token after ``#``.
    re.compile(r'^#{1,6}\s+.+?\s+\{#([^\s.}]+)[^}]*\}\s*$', re.MULTILINE),
    # Frontmatter ``label: foo`` (chapter-level anchor).
    re.compile(r'^label:\s+(\S+)\s*$', re.MULTILINE),
    # Trailing equation-block label ``$$ (eq-foo)`` (multline / labeled
    # align). The closing ``$$`` may have leading whitespace.
    re.compile(r'^\$\$\s+\(([^)\s]+)\)\s*$', re.MULTILINE),
]

# Reference patterns. Capture group 1 is the directive role
# (``ref`` / ``eq`` / ``numref`` / ``prf:ref``); group 2 is the
# target name (single, or comma-separated for ``{cite}``).
_XREF_RE = re.compile(r'\{(ref|eq|numref|prf:ref)\}`([^`]+)`')
_CITE_RE = re.compile(r'\{(cite(?::t|:p|:author|:year)?)\}`([^`]+)`')


def collect_anchors(text: str) -> set[str]:
    """Return every declared anchor name in ``text``. Includes
    ``(name)=``, ``:name:`` / ``:label:`` directive options, heading
    auto-ids, ``label:`` frontmatter, and trailing-paren equation
    labels."""
    anchors: set[str] = set()
    for pat in _ANCHOR_PATTERNS:
        for m in pat.finditer(text):
            anchors.add(m.group(1))
    return anchors


def collect_references(text: str) -> tuple[set[str], set[str]]:
    """Return ``(xref_targets, cite_targets)`` — the names every
    ``{ref|eq|numref|prf:ref}`` and every ``{cite*}`` directive points
    at. Multi-key ``{cite}`a,b,c``` are split on comma.

    Untyped — preserves the original name-only contract used by tests
    and downstream consumers. See ``collect_typed_references`` for
    the role-aware variant used by the type-compatibility check.
    """
    xrefs: set[str] = set()
    cites: set[str] = set()
    for m in _XREF_RE.finditer(text):
        for key in m.group(2).split(','):
            key = key.strip()
            if key:
                xrefs.add(key)
    for m in _CITE_RE.finditer(text):
        for key in m.group(2).split(','):
            key = key.strip()
            if key:
                cites.add(key)
    return xrefs, cites


def collect_typed_references(text: str) -> tuple[
    list[tuple[str, str]], set[str]
]:
    """Return ``(typed_xrefs, cite_targets)`` where ``typed_xrefs`` is
    a list of ``(role, target)`` pairs. Used by the type-compatibility
    check (P1a-prime, closes #38 class of bugs): a reference whose
    role doesn't match the routing-role for the target label's prefix
    is broken in MyST (``{ref}`eq-foo`` cannot target an equation
    anchor, ``{numref}`thm-X`` cannot target a theorem, etc.).
    """
    typed_xrefs: list[tuple[str, str]] = []
    cites: set[str] = set()
    for m in _XREF_RE.finditer(text):
        role = m.group(1)
        # Cross-refs are always single-target (comma-separated multi
        # forms only apply to {cite}).
        target = m.group(2).strip()
        if target:
            typed_xrefs.append((role, target))
    for m in _CITE_RE.finditer(text):
        for key in m.group(2).split(','):
            key = key.strip()
            if key:
                cites.add(key)
    return typed_xrefs, cites


# Bib-key parse. A real ``.bib`` file looks like::
#
#   @book{smith2020, ... }
#   @article{Bertsekas:2000:DPO:517430, ... }
#
# We only need the keys; ignore the body. The regex matches an entry-type
# token (``@article`` / ``@book`` / ``@inproceedings`` / etc.) followed by
# ``{KEY,`` — KEY can contain ``:``, ``.``, ``-`` per real-world
# generators (lesson 031).
_BIB_KEY_RE = re.compile(
    r'@\w+\s*\{\s*([A-Za-z][A-Za-z0-9_:./\-]+)\s*,',
)


def parse_bib_keys(bib_path: Path) -> set[str]:
    """Return the set of citation keys declared in ``bib_path``. Empty
    set if the file does not exist (the caller decides whether that's
    an error or expected)."""
    if not bib_path.is_file():
        return set()
    text = bib_path.read_text(encoding='utf-8', errors='replace')
    return set(_BIB_KEY_RE.findall(text))


# Lazy import to avoid circular at module load — validate.py is
# called from the CLI but also from tests that import it directly.
def _routing_role(target: str) -> str:
    """Local wrapper around ``transforms.refs.routing_role`` (which
    late-imports the per-book extras from ``postprocess``). Returns
    the MyST role name a label SHOULD be referenced through, based
    on its prefix."""
    from transforms.refs import routing_role
    return routing_role(target)


def check_resolution(text: str, filename: str,
                     bib_keys: set[str] | None = None,
                     check_types: bool = True) -> list[str]:
    """Return diagnostic lines for cross-refs and citations whose
    targets don't resolve OR whose directive type doesn't match the
    target. Empty list = clean.

    Three diagnostic classes:

    1. **Unresolved cross-reference** — a ``{ref|eq|numref|prf:ref}`X```
       to an anchor named ``X`` that doesn't exist anywhere.
    2. **Directive-type mismatch** (P1a-prime, closes #38 class) — the
       reference role doesn't match the routing-role for the target
       label's prefix. E.g. ``{ref}`eq-foo`` cannot target an
       equation anchor; should be ``{eq}`eq-foo``. Disable with
       ``check_types=False``.
    3. **Unresolved citation key** — a ``{cite*}`X``` to a key not
       declared in ``bib_keys``. Skipped when ``bib_keys`` is None
       (no bibliography configured).
    """
    diagnostics: list[str] = []
    anchors = collect_anchors(text)
    typed_xrefs, cites = collect_typed_references(text)

    # Pass 1 — name resolution. Sort uniquified pairs for determinism.
    unresolved = sorted(
        {(role, target) for role, target in typed_xrefs if target not in anchors}
    )
    for role, target in unresolved:
        diagnostics.append(
            f'{filename}: unresolved cross-reference: '
            f'{{{role}}}`{target}` (no such anchor)'
        )

    # Pass 2 — type compatibility. Only checks refs that DID resolve;
    # an unresolved ref's role-vs-routing mismatch is noise on top of
    # the bigger "missing anchor" problem.
    if check_types:
        resolved = {(r, t) for r, t in typed_xrefs if t in anchors}
        mismatches = sorted({
            (role, target, _routing_role(target))
            for role, target in resolved
            if role != _routing_role(target)
        })
        for role, target, expected in mismatches:
            diagnostics.append(
                f'{filename}: directive-type mismatch: '
                f'{{{role}}}`{target}` (label prefix expects {{{expected}}})'
            )

    if bib_keys is not None:
        for key in sorted(cites - bib_keys):
            diagnostics.append(
                f'{filename}: unresolved citation key: '
                f'{{cite*}}`{key}`'
            )

    # Pass 3 — backtick inside a backtick-fence info string (#122).
    # CommonMark forbids backticks in the info string of a backtick fence
    # (spec §4.5), so markdown-it/mystmd rejects the line as a fence opener,
    # the directive never opens, and its CLOSING fence then opens a literal
    # code block that swallows everything to the next fence — anchors and
    # equations inside vanish from the built AST. This is exactly the
    # blast pattern of an inline role emitted into a directive argument.
    for i, line in enumerate(text.split('\n'), 1):
        m = re.match(r'^`{3,}\{[^}]+\}([^\n]*)$', line)
        if m and '`' in m.group(1):
            diagnostics.append(
                f'{filename}:{i}: backtick in backtick-fence info string '
                f'(CommonMark rejects the fence; the directive will not '
                f'open): {line[:80]}'
            )

    return diagnostics


def find_broken_inline_math(text: str, filename: str) -> list[str]:
    """Detect inline math (``$...$``) split across a newline where the
    next line starts with ``>``. MyST interprets the leading ``>`` as
    a blockquote marker, silently breaking both the math and the
    surrounding paragraph.

    Returns a list of human-readable diagnostic lines; empty if clean.
    Skips inside fenced code blocks and ``$$`` display-math blocks so
    legitimate multi-line constructs don't trigger the check.

    Multi-line inline math whose continuation line is ordinary content
    (not a ``>``) renders correctly in MyST and is NOT flagged — that
    pattern is common when paragraphs wrap at column boundaries and
    isn't a bug. The narrow ``>`` case is the real trap.
    """
    diagnostics: list[str] = []
    lines = text.splitlines()
    in_fence = False
    in_math_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith('$$'):
            in_math_block = not in_math_block
            continue
        if in_math_block:
            continue

        clean = line.replace('\\$', '').replace('$$', '')
        if clean.count('$') % 2 == 0 or i + 1 >= len(lines):
            continue

        next_stripped = lines[i + 1].lstrip()
        if next_stripped.startswith('>'):
            diagnostics.append(
                f"{filename}:{i+1}: ...{line[-80:]}\n"
                f"{filename}:{i+2}: {lines[i+1][:80]}"
            )
    return diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()

    config = load(args.config)
    base = args.config.resolve().parent
    source_dir = (base / config.get('source_dir', '..')).resolve()
    output_dir = (base / config.get('output_dir', '.')).resolve()
    # ``preprocess.split:`` fans a monolithic source ``.tex`` out into
    # per-stem files under ``tmp_dir`` BEFORE pandoc runs. By Stage 6
    # (this script) those files are guaranteed present. We look for
    # each stem's ``.tex`` in ``source_dir`` first and fall back to
    # ``tmp_dir`` so the validator's per-chapter loop doesn't silently
    # skip every entry on books that use ``preprocess.split:`` (#68).
    tmp_dir = (base / (config.get('tmp_dir') or './tmp')).resolve()

    checks = config.get('validate') or {}
    fields = [k for k, v in [
        ('equations', checks.get('equations', True)),
        ('theorems',  checks.get('theorems', True)),
        ('figures',   checks.get('figures', True)),
        ('cross_refs', checks.get('cross_references', True)),
        ('citations', checks.get('citations', True)),
    ] if v]

    chapters = (config.get('chapters') or []) + (config.get('extra_files') or [])

    print(f"{'chapter':<28} " + ' '.join(f'{f:>12}' for f in fields))
    print('-' * (29 + 13 * len(fields)))

    any_mismatch = False
    broken_math_total = 0
    unresolved_total = 0
    type_mismatch_total = 0
    validated_count = 0  # tracks chapters that actually ran through the loop
    check_broken_math = checks.get('broken_inline_math', True)
    check_resolution_flag = checks.get('cross_ref_resolution', True)
    # Type-compatibility (P1a-prime) is opt-out separately because it
    # may surface pre-existing mismatches at first run that need
    # human triage. Default on.
    check_types_flag = checks.get('cross_ref_type_compatibility', True)

    # Apply the config (loads cross_ref_routing extras, etc.) so the
    # type-compatibility check honours per-book routing overrides.
    try:
        import postprocess
        postprocess.apply_config(config, base)
    except SystemExit:
        # validate_config inside apply_config may sys.exit on bad
        # config; the calling shell will have already failed before
        # we got here in practice. Re-raise rather than mask.
        raise

    # Cross-chapter anchor space: a ``{ref}\`X\``` in chapter A may resolve
    # to an anchor declared in chapter B. Build the union once.
    all_anchors: set[str] = set()
    if check_resolution_flag:
        for entry in chapters:
            md = output_dir / f"{entry['stem']}.md"
            if md.exists():
                all_anchors |= collect_anchors(md.read_text(encoding='utf-8'))

    # Bib keys (project-wide, parsed from the configured bibliography).
    bib_keys: set[str] | None = None
    if check_resolution_flag:
        bib_filename = config.get('bibliography')
        if bib_filename:
            bib_path = (source_dir / bib_filename).resolve()
            bib_keys = parse_bib_keys(bib_path)

    for entry in chapters:
        # ``regen: false`` files are curated outside the pipeline (#63);
        # the LaTeX↔MyST counts won't match by design. Their anchors are
        # still folded into ``all_anchors`` above so cross-refs resolve.
        if entry.get('regen') is False:
            continue
        stem = entry['stem']
        # Source ``.tex`` resolution: pristine source first, ``tmp_dir``
        # fallback for ``preprocess.split:`` per-stem files that don't
        # exist in ``source_dir`` (#68).
        tex = source_dir / f"{stem}.tex"
        if not tex.exists():
            tex = tmp_dir / f"{stem}.tex"
        md = output_dir / f"{stem}.md"
        # Warn rather than silently skip — the previous silent ``continue``
        # let the entire loop no-op on ``preprocess.split:`` books while
        # still printing the vacuous-pass summary at the end (#68).
        if not tex.exists():
            print(
                f"  WARN: {stem}.tex not found in source_dir or tmp_dir — "
                f"skipping validation for this stem",
                file=sys.stderr,
            )
            continue
        if not md.exists():
            print(
                f"  WARN: {md} not found — skipping validation for this stem",
                file=sys.stderr,
            )
            continue
        md_text = md.read_text(encoding='utf-8')
        lcounts = count_latex(tex.read_text(encoding='utf-8'))
        mcounts = count_myst(md_text)
        validated_count += 1
        cells = []
        for f in fields:
            l = lcounts.get(f, 0)
            m = mcounts.get(f, 0)
            mark = '' if l == m else '!'
            if l != m:
                any_mismatch = True
            cells.append(f'{l:>5}/{m:<5}{mark}')
        print(f'{stem:<28} ' + ' '.join(cells))

        if check_broken_math:
            for diag in find_broken_inline_math(md_text, md.name):
                print(diag)
                broken_math_total += 1

        if check_resolution_flag:
            # Resolution check uses the project-wide anchor pool, not just
            # the current chapter's, so cross-chapter refs resolve correctly.
            typed_xrefs, cites = collect_typed_references(md_text)

            # (1) Name resolution.
            unresolved_pairs = sorted({
                (role, target) for role, target in typed_xrefs
                if target not in all_anchors
            })
            for role, target in unresolved_pairs:
                print(f'{md.name}: unresolved cross-reference: '
                      f'{{{role}}}`{target}` (no such anchor)')
                unresolved_total += 1

            # (2) Type compatibility — only for refs that resolve.
            if check_types_flag:
                resolved_pairs = {
                    (role, target) for role, target in typed_xrefs
                    if target in all_anchors
                }
                mismatches = sorted({
                    (role, target, _routing_role(target))
                    for role, target in resolved_pairs
                    if role != _routing_role(target)
                })
                for role, target, expected in mismatches:
                    print(f'{md.name}: directive-type mismatch: '
                          f'{{{role}}}`{target}` '
                          f'(label prefix expects {{{expected}}})')
                    type_mismatch_total += 1

            # (3) Citation resolution.
            if bib_keys is not None:
                for key in sorted(cites - bib_keys):
                    print(f'{md.name}: unresolved citation key: '
                          f'{{cite*}}`{key}`')
                    unresolved_total += 1

    print()
    if broken_math_total:
        print(f'  {broken_math_total} broken inline-math pattern(s) detected.')
        print('  Fix by joining the split lines so the $...$ stays on one line.')
    if unresolved_total:
        print(f'  {unresolved_total} unresolved cross-reference(s) / citation(s).')
        print('  An anchor named in a {ref}/{eq}/{cite*} directive is missing.')
    if type_mismatch_total:
        print(f'  {type_mismatch_total} directive-type mismatch(es).')
        print('  Reference role does not match the target label\'s prefix '
              '(e.g. {ref}`eq-foo` should be {eq}`eq-foo`).')
    if any_mismatch:
        print('  Mismatches detected (marked with `!`). Investigate before shipping.')
    if any_mismatch or broken_math_total or unresolved_total or type_mismatch_total:
        sys.exit(1)
    # Vacuous-pass guard (#68). The previous unconditional "All counts
    # match" message printed even when every chapter's per-loop iteration
    # skipped — the silent ``preprocess.split:`` bug let books go
    # unvalidated for an entire round before the contradiction with
    # ``myst build`` warnings surfaced. Refuse to claim "all clean"
    # without having actually checked anything, and exit non-zero so
    # CI catches the misconfiguration.
    if validated_count == 0:
        print(
            '  ERROR: no chapters were validated — every entry was '
            'skipped before its counts could be checked. Verify '
            'source_dir / tmp_dir / output_dir paths in config.yaml '
            'and that preprocess.sh has run.',
            file=sys.stderr,
        )
        sys.exit(1)
    print('  All counts match. All cross-references resolve and are well-typed.')


if __name__ == '__main__':
    main()
