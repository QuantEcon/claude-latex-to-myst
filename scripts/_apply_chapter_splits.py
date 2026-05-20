#!/usr/bin/env python3
"""Carve consolidated multi-chapter .tex files into per-chapter pieces.

Some books bundle several `\\chapter{...}` blocks into a single file
(e.g. dp1's ``book/appendix.tex`` holds Appendix A, B, and a
``\\shipoutAnswer`` block). The downstream pipeline expects one
.tex per chapter, so we split at ``\\chapter{...}`` boundaries here,
before the per-chapter preprocess pass.

Driven by ``config.preprocess.split`` (list of entries)::

    preprocess:
      split:
        - source: appendix              # stem of file in source_dir
          into: [appA, appB]            # produces tmp/appA.tex, tmp/appB.tex
          skip_extra: true              # discard trailing \\chapter blocks beyond `into`

For each entry the splitter:
  1. Copies ``source_dir/{source}.tex`` to ``tmp_dir/{source}.tex``.
  2. Locates every ``\\chapter{...}`` (or ``\\chapter*{...}``) boundary.
  3. Writes the Nth section to ``tmp_dir/{into[N-1]}.tex``.
  4. Removes the original ``tmp_dir/{source}.tex``.

Behaviour with extra chapters:
  - ``skip_extra: false`` (default): the splitter errors if more
    ``\\chapter`` blocks exist than ``into`` has slots.
  - ``skip_extra: true``: trailing blocks beyond ``into`` are discarded.

Usage:
    _apply_chapter_splits.py CONFIG_PATH SOURCE_DIR TMP_DIR
"""

import re
import sys
from pathlib import Path

from _config import load


_CHAPTER_RE = re.compile(r'^\\chapter\*?\{', re.MULTILINE)


def split_one(src_path: Path, targets: list[str], skip_extra: bool,
              tmp_dir: Path) -> None:
    text = src_path.read_text(encoding='utf-8')
    starts = [m.start() for m in _CHAPTER_RE.finditer(text)]
    if not starts:
        raise SystemExit(
            f"_apply_chapter_splits: {src_path} has no \\chapter{{}} blocks; "
            f"nothing to split"
        )

    if len(starts) < len(targets):
        raise SystemExit(
            f"_apply_chapter_splits: {src_path} has only {len(starts)} "
            f"\\chapter block(s) but config requires {len(targets)} "
            f"(into: {targets})"
        )
    if len(starts) > len(targets) and not skip_extra:
        raise SystemExit(
            f"_apply_chapter_splits: {src_path} has {len(starts)} "
            f"\\chapter blocks but config only lists {len(targets)} in "
            f"`into`. Set `skip_extra: true` to discard the trailing "
            f"block(s), or add more stems to `into`."
        )

    starts.append(len(text))
    for i, stem in enumerate(targets):
        section = text[starts[i]:starts[i + 1]]
        (tmp_dir / f"{stem}.tex").write_text(section, encoding='utf-8')

    src_path.unlink()


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit("usage: _apply_chapter_splits.py CONFIG SOURCE_DIR TMP_DIR")
    config = load(Path(sys.argv[1]))
    source_dir = Path(sys.argv[2])
    tmp_dir = Path(sys.argv[3])

    splits = (config.get('preprocess') or {}).get('split') or []
    if not isinstance(splits, list):
        raise SystemExit(
            f"config.preprocess.split must be a list, got {type(splits).__name__}"
        )

    for i, entry in enumerate(splits):
        if not isinstance(entry, dict):
            raise SystemExit(
                f"config.preprocess.split[{i}] must be a mapping"
            )
        source = entry.get('source')
        targets = entry.get('into')
        skip_extra = bool(entry.get('skip_extra', False))
        if not isinstance(source, str) or not source:
            raise SystemExit(
                f"config.preprocess.split[{i}].source must be a non-empty string"
            )
        if (not isinstance(targets, list) or not targets
                or not all(isinstance(t, str) and t for t in targets)):
            raise SystemExit(
                f"config.preprocess.split[{i}].into must be a non-empty list "
                f"of stem strings"
            )

        src_path = source_dir / f"{source}.tex"
        if not src_path.exists():
            raise SystemExit(
                f"_apply_chapter_splits: source not found: {src_path}"
            )
        dst_path = tmp_dir / f"{source}.tex"
        dst_path.write_text(src_path.read_text(encoding='utf-8'), encoding='utf-8')
        split_one(dst_path, targets, skip_extra, tmp_dir)
        print(f"  Split: {source}.tex → {', '.join(t + '.tex' for t in targets)}")


if __name__ == '__main__':
    main()
