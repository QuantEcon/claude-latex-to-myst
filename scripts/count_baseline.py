#!/usr/bin/env python3
"""Per-book structural-count baseline (Phase 1 §2b).

The full consumer books can't live in CI (gitignored, megabytes), but their
``validate.py`` *counts can*. This tool reuses validate.py's counting
primitives to emit — or check against — a tiny committed ``baseline.json`` of
per-chapter figure/table/equation/cite/ref counts plus the cross-ref / cite
resolution result, for each fixture.

The baseline catches **drops** (a figure silently lost shows up as a changed
count) — the cheap complement to the byte-diff ``golden_tex`` tier (attribute
degradation at constant count) and the §1b old-vs-new differential.

Usage::

    # write the baseline for one fixture (run after a known-good regen):
    count_baseline.py --config fixtures/book-dp1/regen/config.yaml \
        --write tests/baselines/dp1.json --book dp1

    # check a fresh regen against the committed baseline (CI):
    count_baseline.py --config fixtures/book-dp1/regen/config.yaml \
        --check tests/baselines/dp1.json --book dp1

``--check`` exits non-zero if any count drifts from the committed baseline.
This job is **label-gated / allowed-to-be-flaky** in CI (it needs a fixture
clone): it documents the per-book count surface, it is not the merge blocker
— the curated ``golden_tex`` corpus is.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import validate  # noqa: E402  reuse the counting primitives
from _config import load  # noqa: E402


_FIELDS = ('equations', 'theorems', 'figures', 'cross_refs', 'citations')


def compute(config_path: Path) -> dict:
    """Return ``{stem: {field: [latex, myst]}, ...}`` plus resolution totals,
    mirroring validate.py's main loop but collecting instead of printing."""
    config = load(config_path)
    base = config_path.resolve().parent
    source_dir = (base / config.get('source_dir', '..')).resolve()
    output_dir = (base / config.get('output_dir', '.')).resolve()
    tmp_dir = (base / (config.get('tmp_dir') or './tmp')).resolve()

    import postprocess
    postprocess.apply_config(config, base)

    chapters = (config.get('chapters') or []) + (config.get('extra_files') or [])

    all_anchors: set[str] = set()
    for entry in chapters:
        md = output_dir / f"{entry['stem']}.md"
        if md.exists():
            all_anchors |= validate.collect_anchors(md.read_text(encoding='utf-8'))

    bib_keys = None
    bib_filename = config.get('bibliography')
    if bib_filename:
        bib_keys = validate.parse_bib_keys((source_dir / bib_filename).resolve())

    per_chapter: dict[str, dict] = {}
    unresolved_total = 0
    type_mismatch_total = 0
    for entry in chapters:
        if entry.get('regen') is False:
            continue
        stem = entry['stem']
        tex = source_dir / f"{stem}.tex"
        if not tex.exists():
            tex = tmp_dir / f"{stem}.tex"
        md = output_dir / f"{stem}.md"
        if not tex.exists() or not md.exists():
            continue
        md_text = md.read_text(encoding='utf-8')
        lcounts = validate.count_latex(tex.read_text(encoding='utf-8'))
        mcounts = validate.count_myst(md_text)
        per_chapter[stem] = {f: [lcounts.get(f, 0), mcounts.get(f, 0)] for f in _FIELDS}

        typed_xrefs, cites = validate.collect_typed_references(md_text)
        unresolved_total += sum(1 for role, t in typed_xrefs if t not in all_anchors)
        resolved = {(role, t) for role, t in typed_xrefs if t in all_anchors}
        type_mismatch_total += sum(
            1 for role, t in resolved if role != validate._routing_role(t)
        )
        if bib_keys is not None:
            unresolved_total += len(cites - bib_keys)

    return {
        'chapters': per_chapter,
        'totals': {
            'unresolved': unresolved_total,
            'type_mismatches': type_mismatch_total,
        },
    }


def _diff(baseline: dict, current: dict) -> list[str]:
    drifts: list[str] = []
    b_ch, c_ch = baseline['chapters'], current['chapters']
    for stem in sorted(set(b_ch) | set(c_ch)):
        if stem not in c_ch:
            drifts.append(f'{stem}: present in baseline, missing now')
            continue
        if stem not in b_ch:
            drifts.append(f'{stem}: new stem not in baseline')
            continue
        for field in _FIELDS:
            b = b_ch[stem].get(field)
            c = c_ch[stem].get(field)
            if b != c:
                drifts.append(f'{stem}.{field}: baseline {b} -> now {c}')
    for k in ('unresolved', 'type_mismatches'):
        if baseline['totals'].get(k) != current['totals'].get(k):
            drifts.append(
                f'totals.{k}: baseline {baseline["totals"].get(k)} '
                f'-> now {current["totals"].get(k)}'
            )
    return drifts


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--book', default='book', help='book label for messages')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--write', type=Path, help='write the baseline JSON here')
    g.add_argument('--check', type=Path, help='compare regen against this baseline')
    args = p.parse_args()

    current = compute(args.config)

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(current, indent=2, sort_keys=True) + '\n',
                              encoding='utf-8')
        print(f'wrote baseline for {args.book} -> {args.write}')
        return

    baseline = json.loads(args.check.read_text(encoding='utf-8'))
    drifts = _diff(baseline, current)
    if drifts:
        print(f'COUNT DRIFT for {args.book} ({len(drifts)}):')
        for d in drifts:
            print(f'  {d}')
        sys.exit(1)
    print(f'{args.book}: counts match committed baseline.')


if __name__ == '__main__':
    main()
