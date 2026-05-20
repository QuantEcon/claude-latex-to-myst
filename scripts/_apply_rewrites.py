#!/usr/bin/env python3
"""Apply preprocess.rewrites and preprocess.perl_scripts to a single .tex file.

Reads the config, finds the rewrite rules, applies them in place.

Usage:
    _apply_rewrites.py CONFIG_PATH TEX_FILE
"""

import re
import subprocess
import sys
from pathlib import Path

from _config import load


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: _apply_rewrites.py CONFIG TEX_FILE")
    config = load(Path(sys.argv[1]))
    tex_file = Path(sys.argv[2])

    pre = config.get('preprocess') or {}

    # Simple rewrites: { from: pattern, to: replacement }
    text = tex_file.read_text(encoding='utf-8')
    for rule in pre.get('rewrites') or []:
        if not rule:
            continue
        text = re.sub(rule['from'], rule['to'], text)
    tex_file.write_text(text, encoding='utf-8')

    # Perl one-liners (some patterns need lookahead / multi-line)
    for script in pre.get('perl_scripts') or []:
        if not script:
            continue
        subprocess.run(['perl', '-i', '-0pe', script, str(tex_file)], check=True)


if __name__ == '__main__':
    main()
