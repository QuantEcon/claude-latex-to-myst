#!/usr/bin/env python3
"""Reference-aware figure copying — convert.sh Stage 4 (#154).

Copies into ``output_dir/figures/`` only the assets the generated ``.md``
files actually reference, instead of blanket-copying every
``pdf/png/jpg/jpeg/svg`` in ``figures_dir``. The old blanket copy diverged
from the output whenever ``postprocess.rewrites`` retargeted includes to a
different format: book-dp1 serves pre-rendered SVGs committed in its output
dir, deleted the 85 source PDFs from ``mystmd/figures/`` — and every
pipeline run re-copied all 85 as untracked files.

Behaviour:

- **Scan first.** Every ``*.md`` in ``output_dir`` (including curated
  ``regen: false`` files — they are part of the served book) is scanned
  for ``figures/<name>.<ext>`` references. Paths are normalized first:
  worked-on output contains shapes like ``figures/../figures/x.pdf``.
  Only flat references (``figures/<basename>``) count — the copy step
  has never populated subdirectories.
- **Copy referenced ∩ present.** A referenced name is copied from
  ``figures_dir`` when the destination is missing or older (same
  missing-or-newer semantics as the old loop). The copy step no longer
  maintains its own extension list — the scan's image-format allowlist
  (``_REF_RE``, broader than the old copy list) is the single one,
  which also dissolves the "MUST match Stage 4" coupling that
  ``conversion_context.from_config``'s ``figure_ext_map`` scan used to
  carry.
- **Quietly skip referenced-but-not-in-source.** Pre-rendered assets
  committed directly in the output dir (dp1/dp2's SVGs, 82 of
  deep-learning's 88 referenced figures) never pass through the copy
  step; their references are normal, not errors. A summary count is
  printed, never a per-file warning.
- **Copy-only.** Nothing in the destination is ever deleted —
  hand-committed output assets must survive every run.

Usage:
    _copy_figures.py CONFIG_PATH
"""

from __future__ import annotations

import posixpath
import re
import shutil
import sys
from pathlib import Path

from _config import load

# The single image-format allowlist in the pipeline (the old copy loop
# kept its own). Deliberately an allowlist rather than any-extension:
# the scan is regex-over-prose, and an open match would treat path-like
# strings (``figures/notes.txt`` in a code listing) as assets to ship.
# Broader than the old copy list — gif/webp/avif work; extending it is
# this one edit. A stray ``figures/...`` image path inside a code fence
# can still trigger a copy of an existing source asset — harmless under
# copy-only semantics, so the scan stays fence-unaware.
_REF_RE = re.compile(
    r'(?:[\w.-]+/)*figures/[\w./-]+?\.(?:pdf|png|jpe?g|svg|gif|webp|avif)\b',
    re.IGNORECASE,
)


def scan_references(text: str) -> set[str]:
    """Return the basenames of all flat ``figures/<name>.<ext>``
    references in ``text``, normalizing ``..`` segments first."""
    names: set[str] = set()
    for raw in _REF_RE.findall(text):
        norm = posixpath.normpath(raw)
        base = posixpath.basename(norm)
        # Strictly flat after normalization: ``figures/../figures/x.pdf``
        # and ``./figures/x.pdf`` both reduce to ``figures/x.pdf``;
        # ``static/figures/x.png`` (some other tree) does not.
        if norm == f'figures/{base}':
            names.add(base)
    return names


def copy_referenced_figures(
    output_dir: Path, figures_src: Path
) -> tuple[int, int, int]:
    """Copy referenced assets from ``figures_src`` into
    ``output_dir/figures``. Returns ``(copied, current, not_in_source)``."""
    referenced: set[str] = set()
    for md in sorted(output_dir.glob('*.md')):
        referenced |= scan_references(md.read_text(encoding='utf-8'))

    dst_dir = output_dir / 'figures'
    copied = current = missing = 0
    for name in sorted(referenced):
        src = figures_src / name
        if not src.is_file():
            missing += 1
            continue
        dest = dst_dir / name
        if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime:
            current += 1
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied, current, missing


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: _copy_figures.py CONFIG_PATH')
    config_path = Path(sys.argv[1]).resolve()
    config = load(config_path)
    base = config_path.parent

    figdir_rel = config.get('figures_dir')
    if not figdir_rel:
        return
    output_dir = (base / config.get('output_dir', '.')).resolve()
    figures_src = (base / config.get('source_dir', '.') / figdir_rel).resolve()

    if not figures_src.is_dir():
        print(f'  WARN: {figures_src} not found')
        return

    copied, current, missing = copy_referenced_figures(output_dir, figures_src)
    summary = f'  Copied/updated {copied} referenced figures ({current} already current'
    if missing:
        summary += f'; {missing} referenced assets not in source dir — pre-rendered/committed output'
    print(summary + ')')


if __name__ == '__main__':
    main()
