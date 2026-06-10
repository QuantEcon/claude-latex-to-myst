#!/usr/bin/env python3
"""Render-gate smoke test (lesson 046): does the regenerated book still
*build* cleanly?

The structural gates (unit/golden suites, ``validate.py`` counts, the
``_snapshot`` byte-diff) all operate on the markdown TEXT. Five bugs in the
PR #103 series were invisible to every one of them and only surfaced in a
real ``myst build`` — stacked heading anchors mystmd drops, backtick roles
in fence info strings (CommonMark §4.5) swallowing whole sections, pandoc
``[x]{.smallcaps}`` spans rendering literally, a TIKZCD_INLINE_MAP match
broken by a directive re-shape, and dangling directory-qualified figure
paths. *Structural parity is not render parity.*

This tool codifies the manual procedure that caught them:

1. copy the fixture's worked-on ``mystmd/`` project to a temp dir (config,
   figures, bib, hand-curated files — everything a real build needs);
2. overlay the regenerated ``regen/*.md`` stems;
3. run ``myst build --html``;
4. extract the ``⚠️``/``⛔`` lines, normalize away run-specific noise
   (numbers, temp paths, content hashes), sort;
5. ``--check``: diff against the committed per-book baseline
   (``tests/baselines/build-<book>.txt``). NEW lines fail; vanished lines
   pass with a re-baseline hint. ``--write``: (re)capture the baseline
   after a reviewed run.

Like ``count_baseline.py``, the baseline is tiny and committed while the
fixtures themselves stay local. Skips cleanly (exit 0) when ``myst`` or the
fixture is absent, so it is safe in environments without the render stack.

Usage:
    build_smoke.py --fixture fixtures/book-dp1 --check tests/baselines/build-dp1.txt
    build_smoke.py --fixture fixtures/book-dp1 --write tests/baselines/build-dp1.txt
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_MARKER_RE = re.compile(r'(⚠️|⛔️?)')
# Order matters: hashes before generic digit-folding.
_NORM_SUBS = [
    # webp/asset cache names carry content hashes: foo-<32hex>.png
    (re.compile(r'-[0-9a-f]{8,}\.(png|jpe?g|webp|gif)'), r'-HASH.\1'),
    # temp build dirs (macOS /private/tmp alias included)
    (re.compile(r'(/private)?/tmp/[^\s"\']+'), 'TMPDIR'),
    (re.compile(r'[0-9]+'), 'N'),
    (re.compile(r'\s+'), ' '),
]


def normalize(log_text: str) -> list[str]:
    """Extract the warning/error lines and fold run-specific noise so two
    builds of the same content normalize identically."""
    out = []
    for line in log_text.splitlines():
        m = _MARKER_RE.search(line)
        if not m:
            continue
        s = line[m.end():]
        for pat, repl in _NORM_SUBS:
            s = pat.sub(repl, s)
        out.append(s.strip())
    return sorted(out)


def run_build(fixture: Path) -> tuple[int, str]:
    """Overlay ``regen/*.md`` onto a temp copy of ``mystmd/`` and run
    ``myst build --html``; return ``(returncode, combined output)``."""
    mystmd = fixture / 'mystmd'
    regen = fixture / 'regen'
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / 'book'
        shutil.copytree(mystmd, proj,
                        ignore=shutil.ignore_patterns('_build', 'tmp'))
        for md in sorted(regen.glob('*.md')):
            shutil.copy2(md, proj / md.name)
        res = subprocess.run(
            ['myst', 'build', '--html'],
            cwd=proj, capture_output=True, text=True,
        )
        return res.returncode, res.stdout + res.stderr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', required=True, type=Path)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', type=Path)
    mode.add_argument('--write', type=Path)
    args = ap.parse_args()

    if shutil.which('myst') is None:
        print('build_smoke: SKIP — myst not on PATH')
        return
    if not (args.fixture / 'mystmd').is_dir() or not (args.fixture / 'regen').is_dir():
        print(f'build_smoke: SKIP — {args.fixture} missing mystmd/ or regen/ '
              '(run setup_fixtures.sh + convert.sh first)')
        return

    rc, log = run_build(args.fixture)
    lines = normalize(log)
    if rc != 0:
        # A crashed build can emit zero warning lines — without this marker a
        # failure would false-PASS against an empty baseline (Copilot, #129).
        lines = sorted(lines + ['myst build exited non-zero'])
        print('build_smoke: NOTE — myst build exited non-zero; log tail:',
              file=sys.stderr)
        for raw in log.splitlines()[-5:]:
            print(f'    {raw}', file=sys.stderr)

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text('\n'.join(lines) + ('\n' if lines else ''),
                              encoding='utf-8')
        print(f'build_smoke: wrote {len(lines)} baseline line(s) -> {args.write}')
        return

    baseline = []
    if args.check.exists():
        baseline = [l for l in args.check.read_text(encoding='utf-8').splitlines() if l]
    else:
        sys.exit(f'build_smoke: FAIL — baseline {args.check} missing; '
                 'run with --write after a reviewed build')

    # Multiset diff (Counter), not set diff: identical warnings recur (the
    # deep-learning baseline holds 15 "missing heading depth" lines), so a
    # count INCREASE is a regression a set-difference would miss (Copilot,
    # #129).
    cur, base = Counter(lines), Counter(baseline)
    new, gone = cur - base, base - cur
    if new:
        total = sum(new.values())
        print(f'build_smoke: FAIL — {total} NEW build warning/error line(s):')
        for l, n in sorted(new.items()):
            print(f'  + {l}' + (f'   (x{n})' if n > 1 else ''))
        if gone:
            print(f'  (and {sum(gone.values())} baseline line(s) no longer present)')
        sys.exit(1)
    if gone:
        print(f'build_smoke: PASS — build improved ({sum(gone.values())} baseline '
              f'line(s) gone); consider re-baselining with --write')
    else:
        print(f'build_smoke: PASS — build warnings match baseline '
              f'({len(lines)} line(s))')


if __name__ == '__main__':
    main()
