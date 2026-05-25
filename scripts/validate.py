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


def _count_figures_latex(text: str) -> int:
    """Count figures the pipeline will materialize on the MyST side.

    A ``\\begin{figure}`` block containing N ``\\begin{subfigure}`` blocks
    emits N ``{figure}`` directives (one per subfigure label, outer
    wrapper discarded). A ``\\begin{figure}`` with no subfigures emits
    one. GH #15.
    """
    n = 0
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
        'citations':       len(re.findall(r'\\cite[pt]?\{', text)),
        'cross_refs':      len(re.findall(r'\\(cref|Cref|ref|eqref|autoref)\{', text)),
    }


def count_myst(text: str) -> dict:
    # An unlabeled equation block has two ``$$`` fence lines; a labeled
    # block has ``$$`` open + ``$$ (eq-foo)`` close, so the labeled
    # close doesn't match the bare-fence regex. Count both, then //2.
    # GH #16.
    bare_fence = len(re.findall(r'^\$\$\s*$', text, flags=re.MULTILINE))
    labeled_close = len(re.findall(r'^\$\$\s+\(eq-', text, flags=re.MULTILINE))
    return {
        'equations':       (bare_fence + labeled_close) // 2,
        'labeled_eqs':     labeled_close,
        'theorems':        len(re.findall(r'\{prf:(theorem|lemma|corollary|proposition|definition)\}', text)),
        'figures':         len(re.findall(r'\{figure\}', text)),
        'citations':       len(re.findall(r'\{cite(?::t)?\}', text)),
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

# Reference patterns. Each capture group 1 is the target name (single key)
# or comma-separated keys (multi-key ``{cite}`` form).
_REF_PATTERNS = [
    # MyST cross-reference roles: {ref}, {eq}, {numref}, {prf:ref}.
    (re.compile(r'\{(?:ref|eq|numref|prf:ref)\}`([^`]+)`'),    'xref'),
    # Citation roles: {cite}, {cite:t}, {cite:p}, {cite:author},
    # {cite:year}. Body may be a comma-separated list of keys.
    (re.compile(r'\{cite(?::t|:p|:author|:year)?\}`([^`]+)`'), 'cite'),
]


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
    at. Multi-key ``{cite}`a,b,c``` are split on comma."""
    xrefs: set[str] = set()
    cites: set[str] = set()
    for pat, kind in _REF_PATTERNS:
        bucket = xrefs if kind == 'xref' else cites
        for m in pat.finditer(text):
            for key in m.group(1).split(','):
                key = key.strip()
                if key:
                    bucket.add(key)
    return xrefs, cites


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


def check_resolution(text: str, filename: str,
                     bib_keys: set[str] | None = None) -> list[str]:
    """Return diagnostic lines for cross-refs and citations whose
    targets don't resolve. Empty list = clean.

    - A cross-ref ``{ref}`X``` is unresolved if no anchor named ``X``
      was declared anywhere in ``text``.
    - A citation ``{cite*}`X``` is unresolved if ``X`` is not in the
      provided ``bib_keys``. If ``bib_keys`` is None (no bibliography
      configured), citation checks are skipped.
    """
    diagnostics: list[str] = []
    anchors = collect_anchors(text)
    xrefs, cites = collect_references(text)

    for target in sorted(xrefs - anchors):
        diagnostics.append(
            f'{filename}: unresolved cross-reference: '
            f'{{ref|eq|numref|prf:ref}}`{target}`'
        )

    if bib_keys is not None:
        for key in sorted(cites - bib_keys):
            diagnostics.append(
                f'{filename}: unresolved citation key: '
                f'{{cite*}}`{key}`'
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
    check_broken_math = checks.get('broken_inline_math', True)
    check_resolution_flag = checks.get('cross_ref_resolution', True)

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
        stem = entry['stem']
        tex = source_dir / f"{stem}.tex"
        md = output_dir / f"{stem}.md"
        if not tex.exists() or not md.exists():
            continue
        md_text = md.read_text(encoding='utf-8')
        lcounts = count_latex(tex.read_text(encoding='utf-8'))
        mcounts = count_myst(md_text)
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
            xrefs, cites = collect_references(md_text)
            for target in sorted(xrefs - all_anchors):
                print(f'{md.name}: unresolved cross-reference: '
                      f'{{ref|eq|numref|prf:ref}}`{target}`')
                unresolved_total += 1
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
    if any_mismatch:
        print('  Mismatches detected (marked with `!`). Investigate before shipping.')
    if any_mismatch or broken_math_total or unresolved_total:
        sys.exit(1)
    print('  All counts match. All cross-references resolve.')


if __name__ == '__main__':
    main()
