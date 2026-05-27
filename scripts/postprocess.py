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

# When invoked as ``python3 postprocess.py …`` this module loads under the
# name ``__main__``. Transforms in ``scripts/transforms/`` late-import via
# ``import postprocess`` to read module-level state (TIKZ_FIGURE_MAP,
# ENV_MAP, CHAPTER_TITLES, …) populated by apply_config / load_overrides.
# Without this alias, that import loads a *second* copy of the module
# under the name ``postprocess`` with the defaults frozen and every
# mutation done in ``__main__`` invisible — TikZ figures, extra env
# mappings, custom cross-ref routing all silently no-op. See lesson 038
# and GH issue #42.
if __name__ == '__main__':
    sys.modules['postprocess'] = sys.modules[__name__]

# ── Environment mapping ──────────────────────────────────────────────────────

# Default mapping from pandoc-emitted ``::: envname`` divs to MyST directive
# names. Extended per-project via ``config.extra_environments`` / consumed
# (skip-only) via ``config.skip_environments``. Both lists are merged into
# the module-level dicts by ``apply_config`` — never edit per-book entries
# in this file.
ENV_MAP = {
    # sphinx-proof environments
    'theorem':        'prf:theorem',
    'boxtheorem':     'prf:theorem',
    'lemma':          'prf:lemma',
    'proof':          'prf:proof',
    'definition':     'prf:definition',
    'boxdefinition':  'prf:definition',
    'proposition':    'prf:proposition',
    'boxproposition': 'prf:proposition',
    'corollary':      'prf:corollary',
    'boxcorollary':   'prf:corollary',
    'example':        'prf:example',
    'remark':         'prf:remark',
    'assumption':     'prf:assumption',
    'algorithm':      'prf:algorithm',
    # MyST exercise directive
    'Exercise':       'exercise',
    'Answer':         'solution',
}

# Track the last exercise label so we can associate solutions
_last_exercise_label = None

# Counter for auto-generated exercise labels (reset per file)
_exercise_counter = 0

# Chapter prefix for auto-generated labels (set per file)
_chapter_prefix = ''

# Environments to skip (remove the div wrapper, keep content)
ENV_SKIP = {'multicols', 'minipage', 'center'}

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
    convert_epigraphs,
    cleanup_typography,
    compress_directive_whitespace,
)
from transforms.math import (  # noqa: E402  (re-exports for P3a)
    fix_text_dollar,
    convert_equations,
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
    apply_postprocess_rewrites,
    add_frontmatter,
)

# Per-book extension of the routing table. Populated by ``apply_config``
# from ``cross_ref_routing`` in config.yaml. Extras take precedence over
# defaults so a book can override the role for a prefix the defaults
# already match.
_EXTRA_CROSS_REF_ROUTING: list[tuple[tuple[str, ...], str]] = []





# ── TikZ figure resolution ───────────────────────────────────────────────────

# Map TikZ admonition placeholder labels to actual figure paths.
#
# Populated from the project's tikz_overrides.py file at load time (see
# config.yaml: `tikz_overrides`). Keys are the `:name:` labels emitted by the
# preprocessor for `\input{tikz/...}` references; values are
# `(image_path, optional_caption_override)` tuples.
#
# Empty by default; projects without TikZ leave it empty.
TIKZ_FIGURE_MAP: dict = {}

# Inline tikzcd math blocks to replace with image directives.
# Keyed by chapter stem; each entry matches a $$ tikzcd $$ block.
# Populated from tikz_overrides.py.
TIKZCD_INLINE_MAP: dict = {}


# Per-book extension of the doubled-noun list. Populated by
# ``apply_config`` from ``doubled_noun_refs`` in config.yaml. Books
# with custom theorem-class nouns extend without forking.
_EXTRA_DOUBLED_NOUN_REFS: list[tuple[str, str]] = []


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
_LISTING_SOURCE_BASE: Path | None = None


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
POSTPROCESS_REWRITES: list = []


# Chapter titles mapping — populated from config.yaml at runtime.
CHAPTER_TITLES: dict = {}

# Per-stem frontmatter_style override. A book with mixed conventions (e.g.
# dp1: numbered chapters in ``standalone``, front-matter in ``absorbed``)
# can opt individual stems out of the global default. Populated from
# ``chapters[].frontmatter_style`` / ``extra_files[].frontmatter_style``
# in config.yaml. Stems not present here inherit ``_FRONTMATTER_STYLE``.
CHAPTER_STYLES: dict = {}

# Frontmatter style: 'absorbed' (YAML block, dp2 style — the default) or
# 'standalone' ((label)= + # heading, dp1 style). Populated by apply_config.
_FRONTMATTER_STYLE: str = 'absorbed'

# Whitespace compression: 'readable' (default; keep blank lines around
# directives for source readability) or 'compact' (dp1 style; strip blank
# lines after :label: and between adjacent directives). Populated by
# apply_config.
_WHITESPACE_STYLE: str = 'readable'


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


def load_overrides(overrides_path: Path) -> None:
    """Load TIKZ_FIGURE_MAP and TIKZCD_INLINE_MAP from a project .py file."""
    global TIKZ_FIGURE_MAP, TIKZCD_INLINE_MAP
    spec = importlib.util.spec_from_file_location("project_overrides", overrides_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load overrides file: {overrides_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    TIKZ_FIGURE_MAP = getattr(mod, 'TIKZ_FIGURE_MAP', {})
    TIKZCD_INLINE_MAP = getattr(mod, 'TIKZCD_INLINE_MAP', {})


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


def apply_config(config: dict, base_dir: Path | None = None) -> None:
    """Populate module-level state from a loaded config dict.

    ``base_dir`` is the directory containing config.yaml; relative paths in
    config (``source_dir``, ``source_code_base``) are resolved against it.
    Tests that call ``apply_config`` without a base_dir won't get listing
    resolution, which is fine — listings are an opt-in feature.
    """
    global CHAPTER_TITLES, CHAPTER_STYLES, POSTPROCESS_REWRITES
    global _LISTING_SOURCE_BASE, _FRONTMATTER_STYLE, _WHITESPACE_STYLE
    global ENV_MAP, ENV_SKIP
    validate_config(config)
    CHAPTER_TITLES = {
        entry['stem']: entry.get('title', entry['stem'])
        for entry in (config.get('chapters') or []) + (config.get('extra_files') or [])
    }
    CHAPTER_STYLES = {
        entry['stem']: entry['frontmatter_style']
        for entry in (config.get('chapters') or []) + (config.get('extra_files') or [])
        if 'frontmatter_style' in entry
    }

    # Extend the env→directive map with project-specific environments. Use
    # for theorem-like environments not in the default ENV_MAP (e.g.
    # ``Conjecture: prf:conjecture``, ``Notation: prf:remark``). Project
    # entries override defaults if the same key appears in both.
    extra_envs = config.get('extra_environments') or {}
    if not isinstance(extra_envs, dict):
        raise SystemExit(
            f"config.extra_environments must be a mapping, got {type(extra_envs).__name__}"
        )
    ENV_MAP = {**ENV_MAP, **extra_envs}

    # Extend the "div wrappers to strip" set with project-specific
    # environments — e.g. layout commands that pandoc preserves as ``:::``
    # blocks but have no MyST equivalent (``columns``, ``framed`` …).
    skip_envs = config.get('skip_environments') or []
    if not isinstance(skip_envs, (list, tuple, set)):
        raise SystemExit(
            f"config.skip_environments must be a list, got {type(skip_envs).__name__}"
        )
    ENV_SKIP = ENV_SKIP | set(skip_envs)

    # Per-book extension of the label-prefix → role routing used by
    # ``convert_cross_references.make_ref``. Each entry: ``{prefix: "X",
    # role: "numref|ref|eq|prf:ref"}``. ``prefix`` may be a string
    # ("lst" expands to ("lst:", "lst-")) or an explicit list. Useful
    # when a book uses a non-default label convention (e.g. ``lst:`` for
    # listings instead of the QuantEcon default ``list:``).
    global _EXTRA_CROSS_REF_ROUTING
    _EXTRA_CROSS_REF_ROUTING = []
    for i, rule in enumerate(config.get('cross_ref_routing') or []):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"config.cross_ref_routing[{i}] must be a mapping"
            )
        if 'prefix' not in rule or 'role' not in rule:
            raise SystemExit(
                f"config.cross_ref_routing[{i}] requires 'prefix' and 'role'"
            )
        role = rule['role']
        if not isinstance(role, str):
            raise SystemExit(
                f"config.cross_ref_routing[{i}].role must be a string"
            )
        raw = rule['prefix']
        if isinstance(raw, str):
            # ``"lst"`` expands to both colon- and hyphen-bearing forms,
            # mirroring how labels arrive after ``convert_label_colons``.
            prefixes = (f'{raw}:', f'{raw}-')
        elif isinstance(raw, list) and all(isinstance(p, str) for p in raw):
            prefixes = tuple(raw)
        else:
            raise SystemExit(
                f"config.cross_ref_routing[{i}].prefix must be a string "
                "or list of strings"
            )
        _EXTRA_CROSS_REF_ROUTING.append((prefixes, role))

    # Per-book extension of the doubled-noun list used by
    # ``strip_doubled_noun_refs``. Each entry: ``{noun: "X", prefix: "x-"}``.
    # Useful when a book defines custom theorem classes with their own
    # display nouns ("Claim", "Conjecture", "Fact" …).
    global _EXTRA_DOUBLED_NOUN_REFS
    _EXTRA_DOUBLED_NOUN_REFS = []
    for i, rule in enumerate(config.get('doubled_noun_refs') or []):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"config.doubled_noun_refs[{i}] must be a mapping"
            )
        noun = rule.get('noun')
        prefix = rule.get('prefix')
        if not isinstance(noun, str) or not isinstance(prefix, str):
            raise SystemExit(
                f"config.doubled_noun_refs[{i}] requires string 'noun' "
                "and 'prefix' keys"
            )
        _EXTRA_DOUBLED_NOUN_REFS.append((noun, prefix))

    style = config.get('frontmatter_style', 'absorbed')
    if style not in ('absorbed', 'standalone'):
        raise SystemExit(
            f"config.frontmatter_style must be 'absorbed' or 'standalone', got {style!r}"
        )
    _FRONTMATTER_STYLE = style

    ws = config.get('whitespace_compression', 'readable')
    if ws not in ('readable', 'compact'):
        raise SystemExit(
            f"config.whitespace_compression must be 'readable' or 'compact', got {ws!r}"
        )
    _WHITESPACE_STYLE = ws

    # Book-specific Markdown rewrites. Each entry: { from: regex, to: repl,
    # stems?: [stem1, stem2] }. Compile patterns once at config load.
    post_section = config.get('postprocess') or {}
    if not isinstance(post_section, dict):
        raise SystemExit(
            f"config.postprocess must be a mapping, got {type(post_section).__name__}"
        )
    raw_rewrites = post_section.get('rewrites') or []
    if not isinstance(raw_rewrites, list):
        raise SystemExit(
            f"config.postprocess.rewrites must be a list, got {type(raw_rewrites).__name__}"
        )
    POSTPROCESS_REWRITES = []
    for i, rule in enumerate(raw_rewrites):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"config.postprocess.rewrites[{i}] must be a mapping"
            )
        if 'from' not in rule or 'to' not in rule:
            raise SystemExit(
                f"config.postprocess.rewrites[{i}] requires 'from' and 'to' keys"
            )
        if not isinstance(rule['from'], str) or not isinstance(rule['to'], str):
            raise SystemExit(
                f"config.postprocess.rewrites[{i}]: 'from' and 'to' must be strings"
            )
        stems_field = rule.get('stems')
        if stems_field is not None:
            if (not isinstance(stems_field, list)
                    or not all(isinstance(s, str) for s in stems_field)):
                raise SystemExit(
                    f"config.postprocess.rewrites[{i}].stems must be a list of strings"
                )
            stems_set = frozenset(stems_field)
        else:
            stems_set = None
        try:
            compiled = re.compile(rule['from'], re.MULTILINE)
        except re.error as exc:
            raise SystemExit(
                f"config.postprocess.rewrites[{i}]: bad regex {rule['from']!r}: {exc}"
            )
        POSTPROCESS_REWRITES.append((compiled, rule['to'], stems_set))

    if base_dir is not None:
        # source_code_base anchors paths inside \inputminted{lang}{path}.
        # Defaults to source_dir so dp1-style layouts (``\inputminted{julia}
        # {../source_code_jl/foo.jl}`` from a tex file in ``book/``) work
        # without extra config.
        src_base = config.get('source_code_base') or config.get('source_dir', '.')
        _LISTING_SOURCE_BASE = (base_dir / src_base).resolve()


def process_text(text: str, stem: str, title: str | None = None,
                 *, style: str | None = None) -> str:
    """Pure in-memory transform pipeline. Same order as ``process_file``;
    no file I/O. Extracted so golden-file tests can exercise the full
    pipeline against checked-in fixtures (P0c).

    Order matters:
      - fix_text_dollar first (before eq conversion changes $$ structure)
      - epigraphs (removes ::: blocks before env conversion)
      - environments before labels (directive labels handled in context)
      - equations before cross-refs (so labels are extracted first)
      - cross-refs before figures (captions may contain cross-refs)

    The canonical sequence is locked in ``tests/test_pipeline_order.py``
    (lesson 008). Update both places together if you intentionally reorder.
    """
    global _last_exercise_label, _exercise_counter, _chapter_prefix
    _last_exercise_label = None
    _exercise_counter = 0
    # Chapter prefix for auto-generated labels: strip leading 'ch_' if present.
    _chapter_prefix = stem[3:] if stem.startswith('ch_') else stem

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
    text = convert_simple_tables(text)
    text = convert_environment_divs(text)
    text = convert_description_lists(text)         # decode DESCITEM markers (lesson 022)
    text = resolve_exercise_markers(text)          # decode EXERCISE markers (closes #69)
    text = convert_equations(text)
    text = decode_natbib_markers(text)              # before cross-refs (lesson 020)
    text = convert_cross_references(text)
    text = strip_doubled_noun_refs(text)           # needs MyST refs in place
    text = strip_doubled_section_symbol(text)      # qe-v5 § Section dedupe
    text = convert_figures(text)
    text = convert_html_figures(text)
    text = resolve_tikz_figures(text, stem)
    text = convert_section_labels(text)
    text = convert_citations(text)
    text = convert_standalone_labels(text)
    # Listings and algorithms run LATE so source-code bodies don't get
    # touched by the citation / cross-ref / typography transforms above
    # (Julia ``@views`` etc. would otherwise be eaten by convert_citations).
    text = resolve_listings(text)                  # decode minted markers
    text = resolve_algorithms(text)                # decode algorithm2e markers
    text = resolve_algorithmics(text)              # decode standalone algorithmicx markers (lesson 023)
    text = join_split_inline_math(text)
    text = ensure_blank_after_display_math(text)   # adds blank lines
    text = cleanup_typography(text)                # caps blank-line runs; strips \qedhere
    text = strip_blank_lines_in_math(text)         # MUST run AFTER \qedhere removal (issue #11)
    text = strip_footnote_refs(text)               # operates on cleaned text
    text = compress_directive_whitespace(text)     # opt-in (compact mode)

    resolved_title = title if title is not None else stem
    text = add_frontmatter(text, resolved_title, style=style)
    text = apply_postprocess_rewrites(text, stem)
    return text


def process_file(input_path: Path, output_path: Path = None):
    """Process a single pandoc markdown file into MyST."""
    stem = input_path.stem
    text = input_path.read_text(encoding='utf-8')
    title = CHAPTER_TITLES.get(stem, stem)
    style = CHAPTER_STYLES.get(stem)
    text = process_text(text, stem, title, style=style)

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
    apply_config(config, base_dir)
    output_dir = (base_dir / config.get('output_dir', '.')).resolve()

    # Load TikZ overrides if configured
    tikz_overrides = config.get('tikz_overrides')
    if tikz_overrides:
        overrides_path = (base_dir / tikz_overrides).resolve()
        if overrides_path.exists():
            load_overrides(overrides_path)
        else:
            print(f'  WARN: tikz_overrides file not found: {overrides_path}', file=sys.stderr)

    if args.inputs:
        for path in args.inputs:
            process_file(path)
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
            process_file(md)
        else:
            print(f'  WARN: {md} not found, skipping', file=sys.stderr)


if __name__ == '__main__':
    main()
