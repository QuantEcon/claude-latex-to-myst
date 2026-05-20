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

    # 2. Search-and-replace: { from: regex, to: replacement }
    for rule in pre.get('rewrites') or []:
        if not rule:
            continue
        text = re.sub(rule['from'], rule['to'], text)

    tex_file.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
