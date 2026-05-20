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


def count_latex(text: str) -> dict:
    return {
        'equations':       len(re.findall(r'\\begin\{(equation|align|gather|multline)\*?\}', text)),
        'labeled_eqs':     len(re.findall(r'\\label\{eq:', text)),
        'theorems':        len(re.findall(r'\\begin\{(box)?(theorem|lemma|corollary|proposition|definition)\}', text)),
        'figures':         len(re.findall(r'\\begin\{figure\}', text)),
        'citations':       len(re.findall(r'\\cite[pt]?\{', text)),
        'cross_refs':      len(re.findall(r'\\(cref|Cref|ref|eqref|autoref)\{', text)),
    }


def count_myst(text: str) -> dict:
    return {
        'equations':       len(re.findall(r'^\$\$\s*$', text, flags=re.MULTILINE)) // 2,
        'labeled_eqs':     len(re.findall(r'^\$\$\s+\(eq-', text, flags=re.MULTILINE)),
        'theorems':        len(re.findall(r'\{prf:(theorem|lemma|corollary|proposition|definition)\}', text)),
        'figures':         len(re.findall(r'\{figure\}', text)),
        'citations':       len(re.findall(r'\{cite(?::t)?\}', text)),
        'cross_refs':      len(re.findall(r'\{(prf:)?(ref|eq|numref)\}', text)),
    }


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
    for entry in chapters:
        stem = entry['stem']
        tex = source_dir / f"{stem}.tex"
        md = output_dir / f"{stem}.md"
        if not tex.exists() or not md.exists():
            continue
        lcounts = count_latex(tex.read_text(encoding='utf-8'))
        mcounts = count_myst(md.read_text(encoding='utf-8'))
        cells = []
        for f in fields:
            l = lcounts.get(f, 0)
            m = mcounts.get(f, 0)
            mark = '' if l == m else '!'
            if l != m:
                any_mismatch = True
            cells.append(f'{l:>5}/{m:<5}{mark}')
        print(f'{stem:<28} ' + ' '.join(cells))

    print()
    if any_mismatch:
        print('  Mismatches detected (marked with `!`). Investigate before shipping.')
        sys.exit(1)
    print('  All counts match.')


if __name__ == '__main__':
    main()
