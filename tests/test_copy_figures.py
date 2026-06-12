"""Tests for the reference-aware Stage-4 figure copy (#154).

The old blanket copy shipped every pdf/png/jpg/jpeg/svg in figures_dir
regardless of what the generated .md referenced; book-dp1's deleted
source PDFs were re-copied as untracked files on every run. The new
step copies referenced ∩ present-in-source, never deletes, and treats
referenced-but-not-in-source as normal (pre-rendered assets committed
in the output dir are the dominant pattern across the books).
"""

from __future__ import annotations

import os

import _copy_figures as cf


# ── scan_references ──────────────────────────────────────────────────────────


def test_scan_directive_and_inline_references():
    text = (
        '```{figure} figures/plot.svg\n:name: f-plot\n```\n'
        '![inline](figures/photo.png)\n'
        '<img src="figures/raw.jpeg">\n'
    )
    assert cf.scan_references(text) == {'plot.svg', 'photo.png', 'raw.jpeg'}


def test_scan_normalizes_dot_dot_segments():
    """Worked-on output contains shapes like figures/../figures/x.pdf."""
    text = '```{figure} figures/../figures/rates.pdf\n```\n'
    assert cf.scan_references(text) == {'rates.pdf'}


def test_scan_ignores_subdirectory_references():
    """Only flat figures/<name> references count — the copy step has
    never populated subdirectories."""
    text = '![a](figures/sub/deep.png) ![b](figures/flat.png)'
    assert cf.scan_references(text) == {'flat.png'}


def test_scan_ignores_non_figures_paths():
    text = '![x](images/foo.png) and [a link](docs/figures.md)'
    assert cf.scan_references(text) == set()


def test_scan_ignores_other_trees_ending_in_figures():
    """A figures/ directory under some other root is not the output
    figures/ dir."""
    text = '![x](static/figures/foo.png) ![y](./figures/ok.png)'
    assert cf.scan_references(text) == {'ok.png'}


def test_scan_allowlist_broader_than_old_copy_loop():
    """The scan's allowlist supersedes the old copy loop's
    pdf/png/jpg/jpeg/svg set — gif/webp/avif references now work; a
    non-image extension stays excluded (conservative regex-over-prose:
    an open match would ship path-like strings from code listings)."""
    text = (
        '![a](figures/spin.gif) ![b](figures/photo.webp) '
        '![c](figures/art.avif) [data](figures/notes.txt)'
    )
    assert cf.scan_references(text) == {'spin.gif', 'photo.webp', 'art.avif'}


# ── copy_referenced_figures ──────────────────────────────────────────────────


def _setup(tmp_path, md_text, src_files):
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'ch1.md').write_text(md_text, encoding='utf-8')
    src = tmp_path / 'src_figs'
    src.mkdir()
    for name in src_files:
        (src / name).write_bytes(b'data-' + name.encode())
    return out, src


def test_copies_only_referenced_assets(tmp_path):
    out, src = _setup(
        tmp_path,
        '```{figure} figures/used.svg\n```\n',
        ['used.svg', 'unused.pdf'],
    )
    copied, current, missing = cf.copy_referenced_figures(out, src)
    assert (copied, current, missing) == (1, 0, 0)
    assert (out / 'figures' / 'used.svg').is_file()
    assert not (out / 'figures' / 'unused.pdf').exists()


def test_referenced_but_not_in_source_is_quietly_counted(tmp_path):
    """Pre-rendered assets committed in the output dir (dp1/dp2 SVGs,
    82/88 of deep-learning's references) are normal, not errors."""
    out, src = _setup(
        tmp_path,
        '![a](figures/prerendered.svg) ![b](figures/fromsrc.png)',
        ['fromsrc.png'],
    )
    copied, current, missing = cf.copy_referenced_figures(out, src)
    assert (copied, current, missing) == (1, 0, 1)


def test_current_destination_not_recopied(tmp_path):
    out, src = _setup(tmp_path, '![a](figures/a.png)', ['a.png'])
    assert cf.copy_referenced_figures(out, src) == (1, 0, 0)
    # copy2 preserves mtime, so dest is "current" on the second run.
    assert cf.copy_referenced_figures(out, src) == (0, 1, 0)


def test_newer_source_is_recopied(tmp_path):
    out, src = _setup(tmp_path, '![a](figures/a.png)', ['a.png'])
    cf.copy_referenced_figures(out, src)
    (src / 'a.png').write_bytes(b'updated')
    future = (src / 'a.png').stat().st_mtime + 5
    os.utime(src / 'a.png', (future, future))
    assert cf.copy_referenced_figures(out, src) == (1, 0, 0)
    assert (out / 'figures' / 'a.png').read_bytes() == b'updated'


def test_never_deletes_committed_destination_assets(tmp_path):
    """Copy-only: hand-committed output assets survive every run even
    when unreferenced and absent from the source dir."""
    out, src = _setup(tmp_path, '![a](figures/a.png)', ['a.png'])
    figdir = out / 'figures'
    figdir.mkdir()
    (figdir / 'hand_added.svg').write_text('committed')
    cf.copy_referenced_figures(out, src)
    assert (figdir / 'hand_added.svg').read_text() == 'committed'


def test_scans_every_md_in_output_dir(tmp_path):
    """Curated regen:false files are part of the served book — their
    references count too."""
    out, src = _setup(tmp_path, '![a](figures/a.png)', ['a.png', 'b.png'])
    (out / 'curated.md').write_text('![b](figures/b.png)', encoding='utf-8')
    copied, _, _ = cf.copy_referenced_figures(out, src)
    assert copied == 2
