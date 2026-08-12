# Reference config: book-dp1

Configuration for converting [`book-dp1`](https://github.com/QuantEcon/book-dp1)
(Dynamic Programming Volume I — Finite States) from LaTeX to MyST.

`book-dp1` now runs this pipeline directly: its `mystmd-conversion`
branch carries a vendored `mystmd/convert.sh` + `.tool-version` pin, and
the live config lives there. This directory is the frozen reference
config from the original migration (which reproduced dp1's earlier
hand-forked conversion byte-for-byte on its algorithm and listing
directives).

## Files

- `config.yaml` — chapter list, custom-macro rewrites, pageref strip rules
- `tikz_overrides.py` — empty `TIKZ_FIGURE_MAP` stub; populate when the
  project's TikZ render pipeline produces SVG outputs

## To replicate

From the `book-dp1` repo:

```bash
cp -r ~/path/to/claude-latex-to-myst/examples/book-dp1/* mystmd/
bash ~/path/to/claude-latex-to-myst/scripts/convert.sh --config mystmd/config.yaml
```

## What's project-specific here

- 10 chapter stems (`ch_intro` … `ch_ctime`) + `common_symbols`
- Source under `book/` (not the repo root, unlike dp2)
- `\navy{...}` → `\textbf{...}` rewrite (custom emphasis macro)
- 6 `\pageref` strip variants (dp1 uses page references heavily; they're
  meaningless on the web)
- xfig `.pdf_t` figure imports → plain `\includegraphics`
- 10 TikZ inputs that get placeholders; `tikz_overrides.py` is the place
  to wire those up to rendered SVGs when available

## Verification status (2026-05-20)

Byte-identical to dp1's committed `mystmd/` output for:

- **Algorithms** (`{prf:algorithm}`): all 8 across ch_intro, ch_mdps,
  ch_rdps, ch_state_dep, ch_ctime
- **Listings** (`{code-block}`): all 21 across ch_intro, ch_mcs, ch_mdps,
  ch_val, ch_ctime

Remaining diffs to dp1's hand-tuned output are stylistic (frontmatter
form, blank-line stripping); see `reports/book-dp1-parity.md`.
