#!/usr/bin/env python3
"""Apply preprocess.strip and preprocess.rewrites to a single .tex file.

Reads the config, finds the rules, applies them in place. All transforms are
Python re.sub — no sed (BSD/GNU portability traps) and no perl (extra dep).

Usage:
    _apply_rewrites.py CONFIG_PATH TEX_FILE
"""

import re
import sys
from pathlib import Path

from _config import load


# natbib variants pandoc cannot losslessly map.
#
# Pandoc handles ``\cite`` and ``\citep`` identically (both → ``[@key]``)
# and ``\citet`` / ``\citealt`` identically (both → ``@key``), losing the
# parenthetical-vs-textual / paren-vs-no-paren distinction. We rewrite
# the lossy variants to bracket-marker sentinels that survive pandoc
# unchanged; ``postprocess.convert_citations`` decodes them.
#
# Variants pandoc handles correctly (``\cite`` → ``{cite}``, ``\citet``
# → ``{cite:t}``) are left alone.
_NATBIB_REWRITES = [
    (r'\\citep\b\s*\{([^}]+)\}',       r'[[CITEP:\1]]'),
    (r'\\citealp\b\s*\{([^}]+)\}',     r'[[CITEALP:\1]]'),
    (r'\\citealt\b\s*\{([^}]+)\}',     r'[[CITEALT:\1]]'),
    (r'\\citeauthor\b\s*\{([^}]+)\}',  r'[[CITEAUTHOR:\1]]'),
    # \citeyearpar must precede \citeyear — both share a prefix and the
    # shorter pattern would otherwise win.
    (r'\\citeyearpar\b\s*\{([^}]+)\}', r'[[CITEYEARPAR:\1]]'),
    (r'\\citeyear\b\s*\{([^}]+)\}',    r'[[CITEYEAR:\1]]'),
]


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: _apply_rewrites.py CONFIG TEX_FILE")
    config = load(Path(sys.argv[1]))
    tex_file = Path(sys.argv[2])

    pre = config.get('preprocess') or {}
    text = tex_file.read_text(encoding='utf-8')

    # 1. Strip patterns: regexes to delete (replace with empty)
    for pat in pre.get('strip') or []:
        if not pat:
            continue
        text = re.sub(pat, '', text)

    # 2. natbib rewrites — built-in, run before user rewrites so a book
    # can still post-process the markers (or override) if needed.
    for pat, repl in _NATBIB_REWRITES:
        text = re.sub(pat, repl, text)

    # 3. Search-and-replace: { from: regex, to: replacement }
    for rule in pre.get('rewrites') or []:
        if not rule:
            continue
        text = re.sub(rule['from'], rule['to'], text)

    tex_file.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
