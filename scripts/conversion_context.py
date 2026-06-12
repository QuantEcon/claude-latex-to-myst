"""``ConversionContext`` — the post-pandoc pipeline's run state, threaded as
an argument instead of mutated module globals (Phase 3 — see
``notes/design/phase-3-conversion-context.md``).

## Why this exists

Before Phase 3 the whole post-pandoc pipeline funnelled through
module-level mutable globals on ``postprocess.py`` (``ENV_MAP``,
``TIKZ_FIGURE_MAP``, ``POSTPROCESS_REWRITES``, the per-file exercise
counters, …), read by seven transform modules via late ``import
postprocess``. That made the pipeline **non-reentrant** (two configs can't
coexist in one process) and was the root cause of 🔴 lesson 038 (the
``__main__``-vs-``postprocess`` double-load that froze every config-derived
map). Threading a context object removes both problems: state is an
argument, so it can't be a frozen singleton and two books can convert in
one process.

## Shape

``ConversionContext`` holds the config-derived state (built once by
``from_config``) plus a nested, explicitly-reset ``FileCounters`` for the
per-file exercise numbering. Transforms that need state take ``ctx``;
already-pure transforms (most of ``math``/``cite``) stay pure.

## The current-context registry (test-compat shim)

``process_text`` threads ``ctx`` explicitly, which is what makes the
pipeline reentrant. But ~600 unit tests call individual transforms and
``process_text`` *without* a ctx and configure state by assigning to the
old ``postprocess`` attribute names. ``current_context()`` /
``set_current_context()`` back that: ``apply_config`` registers the
config-derived context as current, ``postprocess`` proxies its former
globals onto it (see the module-proxy at the bottom of ``postprocess.py``),
and a transform called without an explicit ctx falls back to the current
one. The registry is a single rebindable pointer in *this* module (imported
once), not the web of mutated maps lesson 038 was about — and explicit
threading bypasses it entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def scan_heading_label_aliases(src_dir: Path) -> dict:
    """Scan every ``*.tex`` in ``src_dir`` for sectioning commands carrying
    multiple consecutive ``\\label{}``s and return ``{secondary: primary}``
    in hyphen (MyST) form (#108).

    Pandoc folds only the FIRST label into the heading id; mystmd accepts only
    ONE ``(name)=`` anchor per heading (stacking warns "label X replaced with
    Y" and drops the rest — verified against myst v1.9.1 in the dp1 build
    test). So secondary labels can't be targets at all: they alias the
    primary, and refs to them are rewritten by ``convert_cross_references``.

    Matches both #108 shapes — labels trailing the heading line and labels on
    immediately-following lines — by accepting whitespace / ``%`` comments
    between consecutive ``\\label{}``s. Purely syntactic and conservative:
    anything not matching the consecutive-labels shape contributes nothing.
    """
    import re

    section_re = re.compile(
        r'\\(?:chapter|section|subsection|subsubsection|paragraph)\*?\s*'
        r'(?:\[[^\]]*\])?\{'
    )
    label_re = re.compile(r'\s*(?:%[^\n]*\n\s*)*\\label\{([^}]+)\}')
    aliases: dict[str, str] = {}
    for tex in sorted(src_dir.glob('*.tex')):
        try:
            text = tex.read_text(encoding='utf-8')
        except OSError:
            continue
        for m in section_re.finditer(text):
            # Balance the title's brace group.
            depth, i = 1, m.end()
            while i < len(text) and depth:
                c = text[i]
                if c == '\\':
                    i += 2
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                i += 1
            labels = []
            while True:
                lm = label_re.match(text, i)
                if not lm:
                    break
                labels.append(lm.group(1).replace(':', '-'))
                i = lm.end()
            for secondary in labels[1:]:
                aliases[secondary] = labels[0]
    return aliases


# Default mapping from pandoc-emitted ``::: envname`` divs to MyST directive
# names. A book extends this via ``config.extra_environments`` (merged in
# ``from_config``); never edit per-book entries here. This is an immutable
# default — ``from_config`` copies it before merging, so the default is never
# mutated (the lesson-038 trap).
DEFAULT_ENV_MAP: dict[str, str] = {
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

# Environments whose ``:::`` div wrapper is stripped (content kept). Extended
# via ``config.skip_environments``.
DEFAULT_ENV_SKIP: frozenset[str] = frozenset({'multicols', 'minipage', 'center'})


@dataclass
class FileCounters:
    """Per-file mutable state for exercise numbering. Reset at the top of
    every ``process_text`` run (``reset_for``) exactly where the old globals
    were reset, so numbering never bleeds across files."""

    last_exercise_label: str | None = None
    exercise_counter: int = 0
    chapter_prefix: str = ''

    def reset_for(self, stem: str) -> None:
        self.last_exercise_label = None
        self.exercise_counter = 0
        # Chapter prefix for auto-generated labels: strip leading 'ch_'.
        self.chapter_prefix = stem[3:] if stem.startswith('ch_') else stem


@dataclass
class ConversionContext:
    """Everything the post-pandoc transforms need that used to be a global.

    Field names map 1:1 to the old ``postprocess`` attributes:
    ``env_map``→``ENV_MAP``, ``env_skip``→``ENV_SKIP``,
    ``tikz_figure_map``→``TIKZ_FIGURE_MAP``,
    ``cross_ref_routing``→``_EXTRA_CROSS_REF_ROUTING`` (the *extra* list, not
    the built-in routing in ``refs.py``), ``doubled_noun_refs``→
    ``_EXTRA_DOUBLED_NOUN_REFS``, ``listing_source_base``→
    ``_LISTING_SOURCE_BASE``, ``postprocess_rewrites``→``POSTPROCESS_REWRITES``,
    ``frontmatter_style``→``_FRONTMATTER_STYLE``, ``whitespace_style``→
    ``_WHITESPACE_STYLE``.
    """

    env_map: dict
    env_skip: set
    chapter_titles: dict
    chapter_styles: dict
    tikz_figure_map: dict
    tikzcd_inline_map: dict
    cross_ref_routing: list
    doubled_noun_refs: list
    listing_source_base: Path | None
    postprocess_rewrites: list
    frontmatter_style: str
    whitespace_style: str
    # ``postprocess.enumerate_style`` (#111): restyle LEVEL-1 ordered-list
    # markers to the configured form (e.g. ``(i)``/``(ii)`` for a book whose
    # preamble sets ``\setlist[enumerate,1]{label=(\roman*)}`` — preamble
    # styling the per-chapter conversion can't see). ``None`` = leave
    # pandoc's decimal markers (the default). Requires fancy-list support
    # in the publisher (QuantEcon/mystmd#50).
    enumerate_style: str | None = None
    counters: FileCounters = field(default_factory=FileCounters)
    # Map of figure-file stem → actual filename (with extension), built by
    # scanning the source ``figures_dir`` (#104). Lets the figure transforms
    # complete an extensionless ``\includegraphics{fig/foo}`` (valid LaTeX —
    # graphicx probes extensions) to the raster the copy step actually wrote.
    figure_ext_map: dict = field(default_factory=dict)
    # Map of secondary heading label → primary heading label (hyphen form),
    # built by scanning the source ``.tex`` for sectioning commands carrying
    # multiple consecutive ``\label{}``s (#108). mystmd keeps only ONE
    # ``(name)=`` anchor per heading ("label X replaced with Y"), so the fix
    # is alias-rewriting: only the primary anchor is emitted, and every ref
    # to a secondary label is rewritten to the primary — refs then render the
    # true section number. Global across the book (refs cross chapters).
    heading_label_aliases: dict = field(default_factory=dict)
    # Optional book-side post-hook (Phase 5). ``callable(text, stem, ctx) ->
    # text``, contributed by a ``project_overrides.py`` and invoked once at a
    # documented point near the end of ``process_text``. ``None`` for books
    # without one. Set by ``load_overrides``, never by config.
    post_convert: object | None = None

    @classmethod
    def default(cls) -> 'ConversionContext':
        """A context with the built-in defaults and no per-book config —
        matches the import-time state of the old module globals. Used as the
        initial current context so transforms called before ``apply_config``
        behave exactly as before."""
        return cls(
            env_map=dict(DEFAULT_ENV_MAP),
            env_skip=set(DEFAULT_ENV_SKIP),
            chapter_titles={},
            chapter_styles={},
            tikz_figure_map={},
            tikzcd_inline_map={},
            cross_ref_routing=[],
            doubled_noun_refs=[],
            listing_source_base=None,
            postprocess_rewrites=[],
            frontmatter_style='absorbed',
            whitespace_style='readable',
            counters=FileCounters(),
        )

    @classmethod
    def from_config(cls, config: dict, base_dir: Path | None = None) -> 'ConversionContext':
        """Build a context from a loaded (and already-validated) config dict.

        This is the pure-constructor successor to the old
        ``apply_config`` — same parsing, no module mutation. ``base_dir`` is
        the directory containing config.yaml; relative paths
        (``source_dir``, ``source_code_base``) resolve against it. Callers
        that need config-schema validation run ``validate_config`` first
        (``postprocess.apply_config`` does).
        """
        import re

        chapters_all = (config.get('chapters') or []) + (config.get('extra_files') or [])
        chapter_titles = {
            entry['stem']: entry.get('title', entry['stem']) for entry in chapters_all
        }
        chapter_styles = {
            entry['stem']: entry['frontmatter_style']
            for entry in chapters_all
            if 'frontmatter_style' in entry
        }

        # env map / skip — defaults + per-book extras (project entries win).
        extra_envs = config.get('extra_environments') or {}
        if not isinstance(extra_envs, dict):
            raise SystemExit(
                f"config.extra_environments must be a mapping, "
                f"got {type(extra_envs).__name__}"
            )
        env_map = {**DEFAULT_ENV_MAP, **extra_envs}

        skip_envs = config.get('skip_environments') or []
        if not isinstance(skip_envs, (list, tuple, set)):
            raise SystemExit(
                f"config.skip_environments must be a list, "
                f"got {type(skip_envs).__name__}"
            )
        env_skip = set(DEFAULT_ENV_SKIP) | set(skip_envs)

        # cross-ref routing extras.
        cross_ref_routing: list[tuple[tuple[str, ...], str]] = []
        for i, rule in enumerate(config.get('cross_ref_routing') or []):
            if not isinstance(rule, dict):
                raise SystemExit(f"config.cross_ref_routing[{i}] must be a mapping")
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
                prefixes = (f'{raw}:', f'{raw}-')
            elif isinstance(raw, list) and all(isinstance(p, str) for p in raw):
                prefixes = tuple(raw)
            else:
                raise SystemExit(
                    f"config.cross_ref_routing[{i}].prefix must be a string "
                    "or list of strings"
                )
            cross_ref_routing.append((prefixes, role))

        # doubled-noun extras.
        doubled_noun_refs: list[tuple[str, str]] = []
        for i, rule in enumerate(config.get('doubled_noun_refs') or []):
            if not isinstance(rule, dict):
                raise SystemExit(f"config.doubled_noun_refs[{i}] must be a mapping")
            noun = rule.get('noun')
            prefix = rule.get('prefix')
            if not isinstance(noun, str) or not isinstance(prefix, str):
                raise SystemExit(
                    f"config.doubled_noun_refs[{i}] requires string 'noun' "
                    "and 'prefix' keys"
                )
            doubled_noun_refs.append((noun, prefix))

        style = config.get('frontmatter_style', 'absorbed')
        if style not in ('absorbed', 'standalone'):
            raise SystemExit(
                f"config.frontmatter_style must be 'absorbed' or 'standalone', "
                f"got {style!r}"
            )

        ws = config.get('whitespace_compression', 'readable')
        if ws not in ('readable', 'compact'):
            raise SystemExit(
                f"config.whitespace_compression must be 'readable' or 'compact', "
                f"got {ws!r}"
            )

        # postprocess rewrites — compile once.
        post_section = config.get('postprocess') or {}
        if not isinstance(post_section, dict):
            raise SystemExit(
                f"config.postprocess must be a mapping, "
                f"got {type(post_section).__name__}"
            )
        raw_rewrites = post_section.get('rewrites') or []
        if not isinstance(raw_rewrites, list):
            raise SystemExit(
                f"config.postprocess.rewrites must be a list, "
                f"got {type(raw_rewrites).__name__}"
            )
        postprocess_rewrites: list = []
        for i, rule in enumerate(raw_rewrites):
            if not isinstance(rule, dict):
                raise SystemExit(f"config.postprocess.rewrites[{i}] must be a mapping")
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
            postprocess_rewrites.append((compiled, rule['to'], stems_set))

        # ``postprocess.enumerate_style`` (#111) — level-1 ordered-list
        # marker restyle. Validated here so a typo fails loudly at config
        # load, not silently at render.
        enumerate_style = post_section.get('enumerate_style')
        _ENUM_STYLES = (
            'lower-roman', 'lower-roman-parens',
            'lower-alpha', 'lower-alpha-parens',
        )
        if enumerate_style is not None and enumerate_style not in _ENUM_STYLES:
            raise SystemExit(
                f"config.postprocess.enumerate_style must be one of "
                f"{_ENUM_STYLES}, got {enumerate_style!r}"
            )

        listing_source_base: Path | None = None
        figure_ext_map: dict[str, str] = {}
        heading_label_aliases: dict[str, str] = {}
        if base_dir is not None:
            src_base = config.get('source_code_base') or config.get('source_dir', '.')
            listing_source_base = (base_dir / src_base).resolve()

            # Multi-label headings → secondary→primary alias map (#108);
            # ``convert_cross_references`` rewrites refs to secondaries.
            src_tex_dir = (base_dir / config.get('source_dir', '.'))
            if src_tex_dir.is_dir():
                heading_label_aliases = scan_heading_label_aliases(src_tex_dir)

            # Scan the source figures dir so an extensionless include can be
            # completed to the file the copy step writes (#104). The extension
            # set MUST match convert.sh Stage 4's copy loop — resolving to a
            # format the copy step doesn't carry (e.g. gif) would point at a
            # file absent from the output figures/ dir. Prefer web-renderable
            # formats when several share a stem (pdf last — mystmd can't
            # render it).
            figdir_rel = config.get('figures_dir')
            if figdir_rel:
                src_dir = config.get('source_dir', '.')
                figdir = (base_dir / src_dir / figdir_rel)
                if figdir.is_dir():
                    for ext in ('png', 'jpg', 'jpeg', 'svg', 'pdf'):
                        for f in sorted(figdir.glob(f'*.{ext}')):
                            figure_ext_map.setdefault(f.stem, f.name)

        return cls(
            env_map=env_map,
            env_skip=env_skip,
            chapter_titles=chapter_titles,
            chapter_styles=chapter_styles,
            tikz_figure_map={},
            tikzcd_inline_map={},
            cross_ref_routing=cross_ref_routing,
            doubled_noun_refs=doubled_noun_refs,
            listing_source_base=listing_source_base,
            postprocess_rewrites=postprocess_rewrites,
            frontmatter_style=style,
            whitespace_style=ws,
            enumerate_style=enumerate_style,
            counters=FileCounters(),
            figure_ext_map=figure_ext_map,
            heading_label_aliases=heading_label_aliases,
        )


# ── current-context registry (test-compat shim; see module docstring) ────────

_CURRENT_CONTEXT: ConversionContext = ConversionContext.default()


def current_context() -> ConversionContext:
    """The active context for transforms called without an explicit ``ctx``
    (unit tests, direct transform calls). ``process_text`` threads ``ctx``
    explicitly and does not depend on this for correctness."""
    return _CURRENT_CONTEXT


def set_current_context(ctx: ConversionContext) -> ConversionContext:
    """Register ``ctx`` as the current context (called by
    ``postprocess.apply_config``). Returns it for convenience."""
    global _CURRENT_CONTEXT
    _CURRENT_CONTEXT = ctx
    return ctx
