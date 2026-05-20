# Reference config: book-dp2

This is the configuration that produced the [`book-dp2`](https://github.com/QuantEcon/book-dp2)
MyST conversion. Use it as a template when setting up a new book.

## Files

- `config.yaml` — chapter list, custom-macro rewrites, TikZ overrides path
- `tikz_overrides.py` — the project-specific `TIKZ_FIGURE_MAP` and
  `TIKZCD_INLINE_MAP` for inline TikZ resolution

## To replicate

From the `book-dp2` repo:

```bash
cp -r ~/path/to/claude-latex-to-myst/examples/book-dp2/* mystmd/
bash ~/path/to/claude-latex-to-myst/scripts/convert.sh --config mystmd/config.yaml
```

## What's project-specific here

- 10 chapter stems (`ch_egs`, `ch_adps`, ...)
- `\navy{...}` → `\textbf{...}` rewrite (dp2 uses this macro for emphasis)
- 14 entries in `TIKZ_FIGURE_MAP` (one per TikZ diagram in the book)
- One inline `tikzcd` pattern for `ch_transforms`
