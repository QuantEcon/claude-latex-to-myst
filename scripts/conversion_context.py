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
    counters: FileCounters = field(default_factory=FileCounters)

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

        listing_source_base: Path | None = None
        if base_dir is not None:
            src_base = config.get('source_code_base') or config.get('source_dir', '.')
            listing_source_base = (base_dir / src_base).resolve()

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
            counters=FileCounters(),
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
