#!/usr/bin/env python3
"""Post-process pandoc markdown output into MyST Markdown.

Transforms pandoc's markdown syntax into proper MyST Markdown:
- ::: envname ... ::: → ```{prf:envname} ... ```
- pandoc cross-refs → MyST {ref}, {eq}, {prf:ref}, {numref}
- pandoc citations → MyST {cite} / {cite:t}
- $$\\begin{equation}...\\end{equation}$$ → $$ ... $$ (label)
- ![cap](path){attrs} → ```{figure} ... ```
- labels: colons → hyphens

This is the generic transform library from claude-latex-to-myst. Project-specific
data (chapter titles, TikZ resolution maps) is loaded from a YAML config and an
optional Python overrides file — never hard-coded here.

Usage:
    postprocess.py --config path/to/config.yaml [INPUT_FILE ...]

If INPUT_FILE args are given, only those files are processed. Otherwise every
chapter listed in the config is processed.
"""

import argparse
import base64
import importlib.util
import re
import sys
from pathlib import Path

# Phase 3 — run state lives in a ``ConversionContext``, not module globals.
# ``apply_config`` builds one and registers it as the *current context*;
# the former module attributes (``ENV_MAP``, ``TIKZ_FIGURE_MAP``, …) are now
# transparent VIEWS on that context, provided by the module-proxy installed
# at the bottom of this file (test-compat shim). This is why lesson 038's
# ``sys.modules['postprocess'] = sys.modules[__name__]`` alias is GONE: the
# state no longer lives in ``postprocess`` (so a second module copy can't
# freeze it) — it lives in ``conversion_context`` (imported once) and is
# threaded explicitly through ``process_text``. See
# ``notes/design/phase-3-conversion-context.md``.
import types  # noqa: E402  (module-proxy install, bottom of file)

import conversion_context as _ctxmod  # noqa: E402
from conversion_context import (  # noqa: E402
    ConversionContext,
    current_context,
    set_current_context,
)

# ── Environment mapping ──────────────────────────────────────────────────────
#
# The default env→directive map and skip set are constants on
# ``conversion_context`` (``DEFAULT_ENV_MAP`` / ``DEFAULT_ENV_SKIP``);
# ``ConversionContext.from_config`` merges in the per-book extras. The
# former module globals ``ENV_MAP`` / ``ENV_SKIP`` (and the per-file
# counters ``_last_exercise_label`` / ``_exercise_counter`` /
# ``_chapter_prefix``) are now views on the current context via the
# module-proxy at the bottom of this file.

# Prose nouns that get doubled by writers in front of a {prf:ref}. Sphinx-proof
# auto-renders the noun (e.g. "Theorem 1.2"), so leaving the prose noun produces
# "Theorem Theorem 1.2" in the output. The second column is the label prefix
# that confirms the ref points to that kind of object — guards against stripping
# "Theorem ..." in front of a ref to something unrelated.
#
# Plural forms are listed alongside singulars so prose like
# ``Chapters {prf:ref}`c-X` and {prf:ref}`c-Y```` (sphinx-proof renders
# each ref as "Chapter N") also gets de-doubled. Multi-target shapes
# (range/list separators) don't need extra handling: only the leading
# plural-noun token is redundant; the refs between separators have no
# intervening noun for sphinx-proof to collide with.
from transforms._helpers import convert_label_colons  # re-export (P3a)


from transforms.typography import (  # noqa: E402  (re-exports for P3a)
    strip_pandoc_html_separators,
    convert_pandoc_spans,
    convert_epigraphs,
    convert_latex_dashes,
    convert_enumerate_style,
    cleanup_typography,
    compress_directive_whitespace,
)
from transforms.math import (  # noqa: E402  (re-exports for P3a)
    fix_text_dollar,
    fix_spacing_superscript,
    convert_equations,
    collapse_inline_math_newlines,
    join_split_inline_math,
    strip_blank_lines_in_math,
    ensure_blank_after_display_math,
)
from transforms.cite import (  # noqa: E402  (re-exports for P3a)
    decode_natbib_markers,
    convert_citations,
)
from transforms.refs import (  # noqa: E402  (re-exports for P3a)
    convert_cross_references,
    strip_doubled_noun_refs,
    strip_doubled_section_symbol,
    strip_footnote_refs,
    routing_role,
)
from transforms.tables import convert_simple_tables  # noqa: E402  (P3a)
from transforms.tables_from_latex import resolve_table_markers  # noqa: E402  (#51)
from transforms.figures_from_latex import resolve_figure_markers  # noqa: E402  (#89/#90/#92/#93)
from transforms.multicols import resolve_multicols_grid  # noqa: E402  (#170)
from transforms.code import (  # noqa: E402  (re-exports for P3a)
    convert_pandoc_attr_code_blocks,
    resolve_listings,
)
from transforms.figures import (  # noqa: E402  (re-exports for P3a)
    convert_figures,
    convert_html_figures,
    resolve_tikz_figures,
)
from transforms.envs import (  # noqa: E402  (re-exports for P3a)
    convert_environment_divs,
    convert_description_lists,
    resolve_exercise_markers,
)
from transforms.algorithms import (  # noqa: E402  (re-exports for P3a)
    resolve_algorithms,
    resolve_algorithmics,
    _algo_find_balanced,
    _unwrap_text_macro,
    _algpseudo_tokenize,
    _algpseudo_inline,
    _algpseudo_convert_body,
    _algo_convert_body,
)
from transforms.frontmatter import (  # noqa: E402  (re-exports for P3a)
    convert_section_labels,
    convert_standalone_labels,
    hoist_consecutive_heading_labels,
    apply_postprocess_rewrites,
    add_frontmatter,
)

# Run state below (cross-ref routing extras, TikZ maps, doubled-noun extras,
# listing base, postprocess rewrites, chapter titles/styles, frontmatter /
# whitespace style) is now held on the current ``ConversionContext`` and
# reached through the module-proxy at the bottom of this file. The comments
# documenting each field are kept here for orientation; the assignments are
# gone (the data is built by ``ConversionContext.from_config``).


# ── TikZ figure resolution ───────────────────────────────────────────────────

# Map TikZ admonition placeholder labels to actual figure paths.
#
# Populated from the project's tikz_overrides.py file at load time (see
# config.yaml: `tikz_overrides`). Keys are the `:name:` labels emitted by the
# preprocessor for `\input{tikz/...}` references; values are
# `(image_path, optional_caption_override)` tuples.
#
# Empty by default; projects without TikZ leave it empty.

# Inline tikzcd math blocks to replace with image directives.
# Keyed by chapter stem; each entry matches a $$ tikzcd $$ block.
# Populated from tikz_overrides.py.


# Per-book extension of the doubled-noun list. Populated by
# ``apply_config`` from ``doubled_noun_refs`` in config.yaml. Books
# with custom theorem-class nouns extend without forking.


# Label-prefix families for which qe-v5 auto-renders a noun ("Section
# X.Y" / "Paragraph X.Y" / "Example X.Y") before the ref. Authors
# sometimes prefix the ref with a literal ``§`` (LaTeX's ``\S``); the
# combination renders as "§ Section X.Y" / "§ Example X.Y" which
# double-counts the noun.
#
# Mostly section-style prefixes, plus ``eg-`` after a dp2 instance of
# the author writing ``\S\ref{eg:foo}`` (semantic mismatch — `\S` is the
# section symbol, but they pointed it at an example). See lesson 016.

# ── minted listings → {code-block} ───────────────────────────────────────────
#
# Listing bodies are intercepted before pandoc by
# scripts/_apply_listing_markers.py, which emits an HTML-comment marker
# carrying the language, source path, line range, label, and caption.
# Here we decode the marker, read the referenced source file, slice the
# requested line range, and emit a MyST ``code-block`` directive whose
# ``:name:`` enables ``{numref}`list-foo``` cross-references.
#
# Reference: book-dp1/mystmd/scripts/postprocess.py::resolve_listings.

# Base directory for resolving ``\inputminted`` paths. Populated by
# apply_config() from config.yaml's ``source_code_base`` (default: source_dir).


# ── algorithm2e → {prf:algorithm} ────────────────────────────────────────────
#
# Algorithm bodies are intercepted before pandoc by
# scripts/_apply_algorithm_markers.py, which base64-encodes them inside an
# HTML comment marker. Here we decode the markers, parse the algorithm2e
# control commands (``\While``, ``\For``, ``\KwIn`` etc.) into nested bullet
# lists, and emit a {prf:algorithm} directive.
#
# Reference: book-dp1/mystmd/scripts/postprocess.py.

# Algorithm parsers moved to transforms/algorithms.py (P3a)
#  _algo_find_balanced, _unwrap_text_macro,
#  _algpseudo_tokenize, _algpseudo_inline, _algpseudo_convert_body,
#  _algo_convert_body, resolve_algorithms, resolve_algorithmics


# Book-specific Markdown rewrites applied after the generic transforms.
# Each entry is ``(compiled_regex, replacement, stems_or_None)``.
# - ``stems_or_None=None``: rewrite applies to every chapter (global).
# - ``stems_or_None={'a', 'b'}``: rewrite applies only to those stems.
# Populated from ``config.postprocess.rewrites`` at runtime.


# Chapter titles mapping — populated from config.yaml at runtime.

# Per-stem frontmatter_style override. A book with mixed conventions (e.g.
# dp1: numbered chapters in ``standalone``, front-matter in ``absorbed``)
# can opt individual stems out of the global default. Populated from
# ``chapters[].frontmatter_style`` / ``extra_files[].frontmatter_style``
# in config.yaml. Stems not present here inherit ``_FRONTMATTER_STYLE``.

# Frontmatter style: 'absorbed' (YAML block, dp2 style — the default) or
# 'standalone' ((label)= + # heading, dp1 style). Populated by apply_config.

# Whitespace compression: 'readable' (default; keep blank lines around
# directives for source readability) or 'compact' (dp1 style; strip blank
# lines after :label: and between adjacent directives). Populated by
# apply_config.


# ── Config loading ───────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load YAML config. Uses PyYAML if available, else a minimal fallback."""
    text = config_path.read_text(encoding='utf-8')
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        # Minimal YAML fallback for the subset we use (no anchors, no flow style).
        # Recommend installing PyYAML for production use.
        raise SystemExit(
            "PyYAML is required to load config. Install with: pip install pyyaml"
        )


def load_overrides(overrides_path: Path, ctx: ConversionContext | None = None) -> None:
    """Load a book-side ``project_overrides.py`` into the conversion context
    (Phase 5). The override file is a **closed** surface — the loader reads
    these attributes if present and ignores the rest; there is no
    registration API, no hook ordering, no lifecycle (that is the
    plugin-framework the project has declined):

      - ``TIKZ_FIGURE_MAP``   — label → ``(path, caption?)`` (already supported)
      - ``TIKZCD_INLINE_MAP`` — inline tikzcd → image (already supported)
      - ``EXTRA_REWRITES``    — ``[(pattern, repl) | (pattern, repl, stems), …]``
        extra postprocess rewrites, *appended* to ``ctx.postprocess_rewrites``
        (book-only — the same shape as ``config.postprocess.rewrites`` but
        living in code rather than YAML, for when the fix needs a real
        pattern the YAML layer can't express cleanly)
      - ``POST_CONVERT``      — ``callable(text, stem, ctx) -> text``, held on
        ``ctx`` and run once near the end of ``process_text``. MUST be
        fence-aware / conservative (it runs on already-converted MyST) — see
        the graduation rule + conservatism note in CLAUDE.md.

    ``tikz_overrides.py`` still loads under this same function (it just has
    the two maps) — the filename is the consumer's choice; the loader is
    filename-agnostic. The override *contributes* to the context; it never
    mutates module globals (lesson 038 / Phase 3).
    """
    ctx = ctx if ctx is not None else current_context()
    spec = importlib.util.spec_from_file_location("project_overrides", overrides_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load overrides file: {overrides_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ctx.tikz_figure_map = getattr(mod, 'TIKZ_FIGURE_MAP', {})
    ctx.tikzcd_inline_map = getattr(mod, 'TIKZCD_INLINE_MAP', {})

    # EXTRA_REWRITES — compile and append to the context's rewrite list, in
    # the same ``(compiled, repl, stems_or_None)`` shape config rewrites use.
    extra_rewrites = getattr(mod, 'EXTRA_REWRITES', None)
    if extra_rewrites:
        for i, rule in enumerate(extra_rewrites):
            if not (isinstance(rule, (tuple, list)) and len(rule) in (2, 3)):
                raise SystemExit(
                    f"{overrides_path}: EXTRA_REWRITES[{i}] must be "
                    "(pattern, repl) or (pattern, repl, stems)"
                )
            pat, repl = rule[0], rule[1]
            stems = None
            if len(rule) == 3 and rule[2]:
                stems_field = rule[2]
                # Guard the footgun: a bare string ``'ch_only'`` would become
                # ``frozenset('ch_only')`` = {'c','h',…} and silently never
                # match. Require a list/tuple of stem strings (same contract
                # as config.postprocess.rewrites[].stems).
                if (not isinstance(stems_field, (list, tuple))
                        or not all(isinstance(s, str) for s in stems_field)):
                    raise SystemExit(
                        f"{overrides_path}: EXTRA_REWRITES[{i}] stems must be a "
                        f"list of stem strings, got {stems_field!r}"
                    )
                stems = frozenset(stems_field)
            ctx.postprocess_rewrites.append((re.compile(pat, re.MULTILINE), repl, stems))

    # POST_CONVERT — the one optional named hook. Held on the context and
    # invoked at a single documented point in process_text.
    post_convert = getattr(mod, 'POST_CONVERT', None)
    if post_convert is not None:
        if not callable(post_convert):
            raise SystemExit(
                f"{overrides_path}: POST_CONVERT must be callable(text, stem, ctx)"
            )
        ctx.post_convert = post_convert


# Top-level config schema. Keys map to ``(allowed_types, required?)``. A
# tuple of types means "one of these"; ``type(None)`` is allowed for keys
# that may be nullable. The validator's main value is catching typos
# (e.g. ``whitespace_comression``) — easy mistake, silent today.
_CONFIG_SCHEMA: dict = {
    'source_dir':             ((str,),               True),
    'output_dir':             ((str,),               False),
    'tmp_dir':                ((str,),               False),
    'chapters':               ((list, type(None)),   False),
    'extra_files':            ((list, type(None)),   False),
    'bibliography':           ((str, type(None)),    False),
    'figures_dir':            ((str, type(None)),    False),
    'source_code_base':       ((str, type(None)),    False),
    'frontmatter_style':      ((str,),               False),
    'whitespace_compression': ((str,),               False),
    'extra_environments':     ((dict, type(None)),   False),
    'skip_environments':      ((list, type(None)),   False),
    'cross_ref_routing':      ((list, type(None)),   False),
    'doubled_noun_refs':      ((list, type(None)),   False),
    'preprocess':             ((dict, type(None)),   False),
    'postprocess':            ((dict, type(None)),   False),
    'tikz_overrides':         ((str, type(None)),    False),
    'project_overrides':      ((str, type(None)),    False),
    'validate':               ((dict, type(None)),   False),
}


def validate_config(config: dict) -> None:
    """Reject unknown keys and bad types. Surfaces config typos that
    would otherwise be silently ignored (``whitespace_comression``,
    ``front_matter_style``, etc.).
    """
    if not isinstance(config, dict):
        raise SystemExit(
            f"config root must be a mapping, got {type(config).__name__}"
        )

    unknown = sorted(set(config) - set(_CONFIG_SCHEMA))
    if unknown:
        # Suggest the closest known key for each unknown one, à la cargo.
        from difflib import get_close_matches
        hints = []
        for k in unknown:
            suggestions = get_close_matches(k, _CONFIG_SCHEMA.keys(), n=1)
            if suggestions:
                hints.append(f"  {k!r}  (did you mean {suggestions[0]!r}?)")
            else:
                hints.append(f"  {k!r}")
        raise SystemExit(
            "config has unknown top-level keys:\n" + "\n".join(hints)
        )

    for key, (types, required) in _CONFIG_SCHEMA.items():
        if key not in config:
            if required:
                raise SystemExit(f"config is missing required key: {key!r}")
            continue
        value = config[key]
        if not isinstance(value, types):
            type_names = " or ".join(
                'null' if t is type(None) else t.__name__ for t in types
            )
            raise SystemExit(
                f"config.{key} must be {type_names}, got {type(value).__name__}"
            )

    # Nested validation for chapters / extra_files: each entry needs at
    # minimum a ``stem``. ``frontmatter_style`` is optional but, when
    # present, must be one of the two recognised styles — same vocabulary
    # as the top-level ``frontmatter_style`` key. ``regen`` is optional
    # and must be a bool when present; it gates whether convert.sh
    # regenerates the file from LaTeX or leaves the curated copy alone
    # (see #63).
    for list_key in ('chapters', 'extra_files'):
        for i, entry in enumerate(config.get(list_key) or []):
            if not isinstance(entry, dict) or 'stem' not in entry:
                raise SystemExit(
                    f"config.{list_key}[{i}] must be a mapping with a 'stem' key"
                )
            style = entry.get('frontmatter_style')
            if style is not None and style not in ('absorbed', 'standalone'):
                raise SystemExit(
                    f"config.{list_key}[{i}].frontmatter_style must be "
                    f"'absorbed' or 'standalone', got {style!r}"
                )
            regen = entry.get('regen')
            if regen is not None and not isinstance(regen, bool):
                raise SystemExit(
                    f"config.{list_key}[{i}].regen must be a boolean, "
                    f"got {type(regen).__name__}"
                )


def apply_config(config: dict, base_dir: Path | None = None) -> ConversionContext:
    """Validate ``config``, build a :class:`ConversionContext` from it, and
    register it as the current context (so transforms called without an
    explicit ``ctx`` — and the ~600 unit tests — see this book's state).
    Returns the context for callers that want to thread it explicitly.

    ``base_dir`` is the directory containing config.yaml; relative paths in
    config (``source_dir``, ``source_code_base``) resolve against it. Tests
    that call ``apply_config`` without a base_dir won't get listing
    resolution, which is fine — listings are an opt-in feature.

    Phase 3: this is now a thin wrapper. The parsing that used to mutate a
    dozen module globals lives in ``ConversionContext.from_config``; this
    function keeps the ``validate_config`` schema check (whose ``_CONFIG_SCHEMA``
    lives here) and registers the result.
    """
    validate_config(config)
    ctx = ConversionContext.from_config(config, base_dir)
    set_current_context(ctx)
    return ctx


def process_text(text: str, stem: str, title: str | None = None,
                 *, style: str | None = None,
                 ctx: ConversionContext | None = None) -> str:
    """Pure in-memory transform pipeline. Same order as ``process_file``;
    no file I/O. Extracted so golden-file tests can exercise the full
    pipeline against checked-in fixtures (P0c).

    ``ctx`` is the :class:`ConversionContext` for this run. When given it is
    registered as the current context (so any transform that still falls back
    to it sees this book's state) and threaded explicitly to the stateful
    transforms below; when omitted the current context is used (the test /
    single-book path). Passing two different contexts across two
    ``process_text`` calls in one process is what makes the pipeline
    reentrant.

    Order matters:
      - fix_text_dollar first (before eq conversion changes $$ structure)
      - epigraphs (removes ::: blocks before env conversion)
      - environments before labels (directive labels handled in context)
      - equations before cross-refs (so labels are extracted first)
      - cross-refs before figures (captions may contain cross-refs)

    The canonical sequence is locked in ``tests/test_pipeline_order.py``
    (lesson 008). Update both places together if you intentionally reorder.
    """
    if ctx is not None:
        set_current_context(ctx)
    ctx = current_context()
    # Per-file exercise numbering — reset exactly where the old module-global
    # counters were reset, so numbering never bleeds across files.
    ctx.counters.reset_for(stem)

    text = strip_pandoc_html_separators(text)
    text = fix_text_dollar(text)
    text = convert_epigraphs(text)
    # convert_simple_tables MUST run before convert_environment_divs (GH #27):
    # tabulars wrapped in \begin{center}…\end{center} are rendered by pandoc
    # as multiline_tables inside ``::: center`` fenced divs, and the #24
    # bound-scan fix relies on the ``:::`` boundary to know where the table
    # region ends. convert_environment_divs strips ``::: center`` (via
    # ENV_SKIP), so once it has run the boundary is gone and the scan fuses
    # adjacent tables again. Order the two passes so the boundary survives
    # until the table pass has used it.
    text = convert_pandoc_attr_code_blocks(text)   # lstlisting → {code-block} (closes #31)
    # resolve_table_markers handles ``\begin{table}`` floats that the
    # ``_apply_table_markers.py`` preprocessor extracted before pandoc
    # ran — those bypass pandoc's lossy LaTeX-tabular reader entirely
    # (closes #51, R3 from PR #41). convert_simple_tables remains the
    # fallback for non-float shapes (``\begin{center}\begin{tabular}``
    # directly, no ``\begin{table}`` wrapper) where pandoc preserves
    # enough structure for the existing path to work.
    text = resolve_table_markers(text)
    # resolve_figure_markers handles ``\begin{figure}`` floats that the
    # ``_apply_figure_markers.py`` preprocessor extracted before pandoc
    # ran. MUST run before ``decode_natbib_markers`` (line below) so the
    # markdown-escaped ``\[\[CITEP:X\]\]`` in figure captions emerges
    # into the post-resolve text where the decoder regex can match it
    # (closes #92). Phase 1 — subfigure shapes still fall through to
    # ``convert_html_figures`` (Phase 2 — issue #94).
    text = resolve_figure_markers(text, ctx)
    text = convert_simple_tables(text)
    # convert_equations MUST run before convert_environment_divs /
    # resolve_exercise_markers (#113 review): starred display envs now emit
    # 3-backtick ```{math} directives, and the env/exercise emitters size
    # their enclosing fence via outer_fence() over the body *at emission
    # time*. With equations converted first, a theorem containing a starred
    # display gets a 4-backtick fence; converted after, the inner ```{math}
    # closer would terminate the theorem early (the issue-#79 ordering
    # limitation outer_fence documents).
    text = convert_equations(text)
    text = convert_environment_divs(text, ctx)
    text = convert_description_lists(text)         # decode DESCITEM markers (lesson 022)
    text = resolve_exercise_markers(text)          # decode EXERCISE markers (closes #69)
    # resolve_multicols_grid decodes MULTICOLSGRID markers into {grid} (#170).
    # AFTER convert_environment_divs (so its ::: grid fences aren't taken for
    # pandoc env divs) and BEFORE the cross-ref / cite passes (so any ref/cite
    # in a grid cell is still processed).
    text = resolve_multicols_grid(text, ctx)
    text = decode_natbib_markers(text)              # before cross-refs (lesson 020)
    text = convert_cross_references(text, ctx)
    text = strip_doubled_noun_refs(text, ctx)      # needs MyST refs in place
    text = strip_doubled_section_symbol(text)      # qe-v5 § Section dedupe
    text = convert_figures(text)
    text = convert_html_figures(text, ctx)
    text = resolve_tikz_figures(text, stem, ctx)
    text = convert_section_labels(text)
    text = hoist_consecutive_heading_labels(text)  # #108 secondary heading \labels
    text = convert_citations(text)
    text = convert_standalone_labels(text)
    # Listings and algorithms run LATE so source-code bodies don't get
    # touched by the citation / cross-ref / typography transforms above
    # (Julia ``@views`` etc. would otherwise be eaten by convert_citations).
    text = resolve_listings(text, ctx)             # decode minted markers
    text = resolve_algorithms(text)                # decode algorithm2e markers
    text = resolve_algorithmics(text)              # decode standalone algorithmicx markers (lesson 023)
    text = fix_spacing_superscript(text)           # \,^ → \,{}^ for KaTeX — runs AFTER decoders so table-cell math is visible (closes #45, #85)
    text = collapse_inline_math_newlines(text)     # inline $…$ spanning a hard line break → single space (#168)
    text = join_split_inline_math(text)
    text = ensure_blank_after_display_math(text)   # adds blank lines
    text = convert_pandoc_spans(text)              # [x]{.smallcaps} → X (#124)
    text = convert_latex_dashes(text)              # --/--- → –/— in prose; AFTER decoders (markers carry '--'), fence/math/comment-aware (#1)
    text = convert_enumerate_style(text, ctx)      # level-1 ordered markers → configured (i)/(a) form; AFTER decoders, prf:algorithm-excluded (#111)
    text = cleanup_typography(text)                # caps blank-line runs; strips \qedhere
    text = strip_blank_lines_in_math(text)         # MUST run AFTER \qedhere removal (issue #11)
    text = strip_footnote_refs(text)               # operates on cleaned text
    text = compress_directive_whitespace(text, ctx)  # opt-in (compact mode)

    resolved_title = title if title is not None else stem
    text = add_frontmatter(text, resolved_title, style=style, ctx=ctx)
    text = apply_postprocess_rewrites(text, stem, ctx)

    # Book-side POST_CONVERT hook (Phase 5) — the single documented insertion
    # point: last, on fully-converted MyST. Contributed by a
    # project_overrides.py via load_overrides; None for books without one.
    # The hook must be fence-aware / conservative (CLAUDE.md) — it runs book
    # code on final output, so a blunt regex could corrupt code/math.
    if ctx.post_convert is not None:
        text = ctx.post_convert(text, stem, ctx)
    return text


def process_file(input_path: Path, output_path: Path = None,
                 ctx: ConversionContext | None = None):
    """Process a single pandoc markdown file into MyST."""
    ctx = ctx if ctx is not None else current_context()
    stem = input_path.stem
    text = input_path.read_text(encoding='utf-8')
    title = ctx.chapter_titles.get(stem, stem)
    style = ctx.chapter_styles.get(stem)
    text = process_text(text, stem, title, style=style, ctx=ctx)

    out = output_path or input_path
    out.write_text(text, encoding='utf-8')
    print(f'  Processed: {input_path.name} → {out.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, required=True,
                        help='Path to config.yaml')
    parser.add_argument('inputs', nargs='*', type=Path,
                        help='Specific .md files to process (default: all chapters in config)')
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    base_dir = config_path.parent
    ctx = apply_config(config, base_dir)
    output_dir = (base_dir / config.get('output_dir', '.')).resolve()

    # Load book-side overrides if configured. ``project_overrides`` is the
    # Phase-5 name (closed surface: TIKZ maps + EXTRA_REWRITES + POST_CONVERT);
    # ``tikz_overrides`` is the retained alias (one release) — same loader.
    overrides_rel = config.get('project_overrides') or config.get('tikz_overrides')
    if overrides_rel:
        overrides_path = (base_dir / overrides_rel).resolve()
        if overrides_path.exists():
            load_overrides(overrides_path, ctx)
        else:
            print(f'  WARN: overrides file not found: {overrides_path}', file=sys.stderr)

    if args.inputs:
        for path in args.inputs:
            process_file(path, ctx=ctx)
        return

    # Process every chapter + extra file from config. Entries marked
    # ``regen: false`` are skipped — they're curated outside the regen
    # flow (#63).
    all_files = (config.get('chapters') or []) + (config.get('extra_files') or [])
    for entry in all_files:
        if entry.get('regen') is False:
            continue
        md = output_dir / f"{entry['stem']}.md"
        if md.exists():
            process_file(md, ctx=ctx)
        else:
            print(f'  WARN: {md} not found, skipping', file=sys.stderr)


# ── Backward-compat module proxy (test-compat shim) ──────────────────────────
#
# The former module globals (``ENV_MAP``, ``TIKZ_FIGURE_MAP``,
# ``POSTPROCESS_REWRITES``, the per-file counters, …) no longer exist as real
# attributes — the run state lives on the current ``ConversionContext``
# (``conversion_context``). To keep the ~600 unit tests (and any external
# caller) that read / mutate / rebind ``postprocess.<NAME>`` working, this
# proxy forwards those specific names to the current context. Tests do e.g.
# ``postprocess.TIKZ_FIGURE_MAP['fig-x'] = …`` (in-place mutate — the getattr
# returns the live ctx dict) and ``postprocess._FRONTMATTER_STYLE = "absorbed"``
# (rebind — the setattr writes onto the ctx). Production code threads ``ctx``
# explicitly and does not rely on this. Installed last so the load-time
# ``def``/``import`` attribute sets use the normal module ``__setattr__``.
_CTX_ATTRS = {
    'ENV_MAP': 'env_map',
    'ENV_SKIP': 'env_skip',
    'CHAPTER_TITLES': 'chapter_titles',
    'CHAPTER_STYLES': 'chapter_styles',
    'TIKZ_FIGURE_MAP': 'tikz_figure_map',
    'TIKZCD_INLINE_MAP': 'tikzcd_inline_map',
    '_EXTRA_CROSS_REF_ROUTING': 'cross_ref_routing',
    '_EXTRA_DOUBLED_NOUN_REFS': 'doubled_noun_refs',
    '_LISTING_SOURCE_BASE': 'listing_source_base',
    'POSTPROCESS_REWRITES': 'postprocess_rewrites',
    '_FRONTMATTER_STYLE': 'frontmatter_style',
    '_WHITESPACE_STYLE': 'whitespace_style',
}
_COUNTER_ATTRS = {
    '_last_exercise_label': 'last_exercise_label',
    '_exercise_counter': 'exercise_counter',
    '_chapter_prefix': 'chapter_prefix',
}


class _ContextProxyModule(types.ModuleType):
    """Module subclass that maps the legacy global names onto the current
    ``ConversionContext`` (and its ``counters``)."""

    def __getattr__(self, name):  # only invoked when normal lookup fails
        if name in _CTX_ATTRS:
            return getattr(_ctxmod.current_context(), _CTX_ATTRS[name])
        if name in _COUNTER_ATTRS:
            return getattr(_ctxmod.current_context().counters, _COUNTER_ATTRS[name])
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    def __setattr__(self, name, value):
        if name in _CTX_ATTRS:
            setattr(_ctxmod.current_context(), _CTX_ATTRS[name], value)
        elif name in _COUNTER_ATTRS:
            setattr(_ctxmod.current_context().counters, _COUNTER_ATTRS[name], value)
        else:
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ContextProxyModule


if __name__ == '__main__':
    main()
