"""Regression tests for the pipeline transforms.

These cover the load-bearing transforms most likely to break under future
refactoring. Run with ``uv run pytest`` (or ``bash scripts/test.sh``).

The tests don't shell out to pandoc — they feed pandoc-shaped strings
directly to the post-processor functions, the same as
``scripts/convert.sh`` does via ``process_file``. Keeps the test suite
fast and hermetic.
"""

from __future__ import annotations

import base64
import re

import pytest

import postprocess
import validate


# ── Algorithm2e (gap #014) ───────────────────────────────────────────────────


def _algo_marker(body: str, name: str = "algo-test", title: str = "T") -> str:
    """Build a pandoc-escaped ALGORITHM marker the way `_apply_algorithm_markers.py`
    would emit and pandoc would pass through."""
    b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
    return f"\\<!--ALGORITHM name={name} title={title} body={b64}--\\>"


def test_resolve_algorithms_simple_body():
    body = (
        "input $X_0$ \\;\n"
        "$t \\leftarrow 0$ \\;\n"
        "\\While{$t < T$}\n"
        "{\n"
        "    observe $X_t$ \\;\n"
        "    choose $A_t$ \\;\n"
        "}\n"
    )
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "```{prf:algorithm} T" in out
    assert ":label: algo-test" in out
    # Statements emit as bullets
    assert "- input $X_0$" in out
    assert "- $t \\leftarrow 0$" in out
    # While header + indented inner bullets
    assert "- while $t < T$:" in out
    assert "  - observe $X_t$" in out
    assert "  - choose $A_t$" in out


def test_resolve_algorithms_kwin_kwout_return():
    body = (
        "\\KwIn{a function $f$}\n"
        "\\KwOut{a fixed point}\n"
        "$k \\leftarrow 0$ \\;\n"
        "\\Return{$u_k$}\n"
    )
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "- input: a function $f$" in out
    assert "- output: a fixed point" in out
    assert "- return $u_k$" in out


def test_resolve_algorithms_lif_single_line():
    body = "\\lIf{$x > 0$}{break}\n"
    out = postprocess.resolve_algorithms(_algo_marker(body))
    # Single-line if: "if cond: body" flattened
    assert "- if $x > 0$: break" in out


def test_resolve_algorithms_repeat_with_inner():
    body = (
        "\\Repeat{\n"
        "    $u \\leftarrow Tu$ \\;\n"
        "    $k \\leftarrow k + 1$ \\;\n"
        "}\n"
    )
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "- repeat:" in out
    assert "  - $u \\leftarrow Tu$" in out


def test_resolve_algorithms_strips_textnormal():
    """FOLLOWUP #014, Gap B: ``\\textnormal{true}`` (LaTeX's "drop into
    text mode inside math") should be unwrapped — algorithm conditions
    aren't math, so the wrapper has no markdown equivalent."""
    body = "\\While{\\textnormal{true}}\n{\n    do stuff \\;\n}\n"
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "- while true:" in out
    assert "\\textnormal" not in out


def test_resolve_algorithms_unbraced_return():
    """FOLLOWUP #014, Gap C: ``\\Return $\\theta$`` (no braces) should
    render as ``- return $\\theta$``. The existing parser only handled
    ``\\Return{x}``."""
    body = "$\\theta \\leftarrow 0$ \\;\n\\Return $\\theta$\n"
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "- return $\\theta$" in out
    # The literal LaTeX shouldn't survive
    assert "\\Return" not in out


def test_resolve_algorithms_unbraced_kwin():
    """Same unbraced fallback applies to \\KwIn / \\KwOut / \\KwResult."""
    body = "\\KwIn data $\\Dsf$ and tolerance $\\tau$ \\;\n"
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "- input: data $\\Dsf$ and tolerance $\\tau$" in out
    assert "\\KwIn" not in out


def test_resolve_algorithms_braced_return_still_works():
    """Regression check: the braced form must keep working alongside
    the new unbraced fallback."""
    body = "\\Return{$u_k$}\n"
    out = postprocess.resolve_algorithms(_algo_marker(body))
    assert "- return $u_k$" in out


def test_resolve_algorithms_handles_unescaped_marker():
    """pandoc usually escapes < and > to \\<, \\>, but sometimes doesn't.
    The regex must tolerate both forms."""
    body = "$x \\leftarrow 0$ \\;"
    b64 = base64.b64encode(body.encode()).decode()
    unescaped = f"<!--ALGORITHM name=algo-x title=Foo body={b64}-->"
    out = postprocess.resolve_algorithms(unescaped)
    assert "```{prf:algorithm} Foo" in out
    assert ":label: algo-x" in out


# ── Minted listings (gap #015) ───────────────────────────────────────────────


def test_resolve_listings_inlines_source(tmp_path):
    src = tmp_path / "src.jl"
    src.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    # Point the listing resolver at our temp dir.
    postprocess._LISTING_SOURCE_BASE = tmp_path

    marker = (
        f"\\<!--LISTING-START name=list-foo lang=julia path=src.jl "
        f"first=2 last=4--\\>\n"
        f"My caption\n"
        f"\\<!--LISTING-END--\\>"
    )
    out = postprocess.resolve_listings(marker)

    assert "```{code-block} julia" in out
    assert ":name: list-foo" in out
    assert ":caption: My caption" in out
    assert ":linenos:" in out
    assert "line2" in out and "line3" in out and "line4" in out
    # Line 1 / 5 excluded by the range
    assert "line1" not in out
    assert "line5" not in out


def test_resolve_listings_missing_source_emits_todo(tmp_path):
    postprocess._LISTING_SOURCE_BASE = tmp_path
    marker = (
        "\\<!--LISTING-START name=list-x lang=python path=missing.py "
        "first= last=--\\>\nCap\n\\<!--LISTING-END--\\>"
    )
    out = postprocess.resolve_listings(marker)
    assert "# TODO: source not found: missing.py" in out
    assert "```{code-block} python" in out


def test_resolve_listings_no_base_configured_emits_todo():
    """When source_code_base is unconfigured, fall back to a placeholder
    rather than swallowing the listing silently."""
    postprocess._LISTING_SOURCE_BASE = None
    marker = (
        "\\<!--LISTING-START name=list-x lang=python path=any.py "
        "first= last=--\\>\nCap\n\\<!--LISTING-END--\\>"
    )
    out = postprocess.resolve_listings(marker)
    assert "# TODO: source_code_base not configured" in out


# ── Doubled-prefix strips (lessons #011 + #016) ──────────────────────────────


def test_strip_doubled_noun_refs():
    text = "Theorem {prf:ref}`t-foo` says..."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{prf:ref}`t-foo` says..."


def test_strip_doubled_noun_refs_nbsp():
    """pandoc emits `~` as U+00A0 (NBSP), not a regular space."""
    text = "Algorithm\xa0{prf:ref}`algo-foo` does X."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{prf:ref}`algo-foo` does X."


def test_strip_doubled_noun_refs_guards_unrelated_prefixes():
    """Don't strip 'Theorem' before a ref to something that isn't a theorem."""
    text = "Theorem {prf:ref}`l-foo` should stay."
    out = postprocess.strip_doubled_noun_refs(text)
    # 't-' / 'thm-' guard would have removed it; 'l-' (lemma) is unrelated
    # to the 'Theorem' noun in _DOUBLED_NOUN_REFS, so keep prose intact.
    assert out == text


def test_strip_doubled_noun_refs_plural_chapters_and_separator():
    """Leading plural 'Chapters' before a multi-target prose
    (`{prf:ref}` X and Y) should be stripped — sphinx-proof renders
    each ref's own noun, so the leading plural is the only redundancy."""
    text = "In Chapters {prf:ref}`c-foo` and {prf:ref}`c-bar` we discuss X."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "In {prf:ref}`c-foo` and {prf:ref}`c-bar` we discuss X."


def test_strip_doubled_noun_refs_plural_with_range_separator():
    """Plural noun + `--`-separated range (Exercises X--Y)."""
    text = "In Exercises {prf:ref}`ex-a`--{prf:ref}`ex-b`, prove X."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "In {prf:ref}`ex-a`--{prf:ref}`ex-b`, prove X."


def test_strip_doubled_noun_refs_plural_with_nbsp():
    """pandoc emits LaTeX `~` as U+00A0 between plural noun and ref."""
    text = "Chapters\xa0{prf:ref}`c-introii`--{prf:ref}`c-mcs` cover X."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{prf:ref}`c-introii`--{prf:ref}`c-mcs` cover X."


def test_strip_doubled_noun_refs_irregular_plural_corollaries():
    """`Corollary` → `Corollaries` is an irregular plural (not just +s).
    Explicit listing in _DOUBLED_NOUN_REFS covers it."""
    text = "Corollaries {prf:ref}`c-aleph` and {prf:ref}`c-beth` follow."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{prf:ref}`c-aleph` and {prf:ref}`c-beth` follow."


def test_strip_doubled_noun_refs_singular_still_works():
    """Existing singular handling must continue to work after plural extension."""
    text = "Theorem {prf:ref}`t-foo` proves X."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{prf:ref}`t-foo` proves X."


def test_strip_doubled_noun_refs_listing_singular():
    """Code-block listings: prose "Listing {numref}`list-foo`" doubles
    with MyST's auto-rendered "Program N" — strip the manual prefix."""
    text = "Parameters appear in Listing {numref}`list-jobs`."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "Parameters appear in {numref}`list-jobs`."


def test_strip_doubled_noun_refs_listing_plural():
    text = "See Listings {numref}`list-a` and {numref}`list-b`."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "See {numref}`list-a` and {numref}`list-b`."


def test_strip_doubled_noun_refs_program_alternate_noun():
    """Some books use the noun MyST renders by default — 'Program' —
    instead of 'Listing'. Strip both."""
    text = "As shown in Program {numref}`list-foo`, the algorithm…"
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "As shown in {numref}`list-foo`, the algorithm…"


# ── Code-block listing cross-refs route to {numref} (issue #8 part 1) ──────


def test_cross_ref_algo_target_routes_to_prf_ref():
    """`algo:foo` labels target `prf:algorithm` directives. The full-word
    `algo:` prefix wasn't in the original routing tuple (only the
    abbreviated `alg:` was), so all 30 dp1 algorithm refs fell through
    to `{ref}` and would have rendered the caption text instead of
    "Algorithm N" — issue #9."""
    text = (
        '[\\[algo:fsvfi\\]](#algo:fsvfi)'
        '{reference-type="ref" reference="algo:fsvfi"}'
    )
    out = postprocess.convert_cross_references(text)
    assert '{prf:ref}`algo-fsvfi`' in out
    assert '{ref}`algo-' not in out


def test_cross_ref_eg_target_routes_to_prf_ref():
    """`eg:foo` labels target `prf:example` directives (the ENV_MAP
    routes `\\begin{example}` → `prf:example`). Same shape as the algo-
    bug — full-word prefix missed by the original tuple. Pre-existing
    bug shared by dp1's legacy pipeline; we fix it as a quality
    improvement at the same time."""
    text = (
        '[\\[eg:retail\\]](#eg:retail)'
        '{reference-type="ref" reference="eg:retail"}'
    )
    out = postprocess.convert_cross_references(text)
    assert '{prf:ref}`eg-retail`' in out
    assert '{ref}`eg-' not in out


def test_strip_doubled_noun_refs_example_singular_and_plural():
    """After issue #9: 'Example {prf:ref}`eg-foo`' should dedupe to
    just '{prf:ref}`eg-foo`' (sphinx-proof renders 'Example N')."""
    text = "Recall Example {prf:ref}`eg-retail` for the setup."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "Recall {prf:ref}`eg-retail` for the setup."

    text_plural = "Compare Examples {prf:ref}`eg-a` and {prf:ref}`eg-b`."
    out_plural = postprocess.strip_doubled_noun_refs(text_plural)
    assert out_plural == "Compare {prf:ref}`eg-a` and {prf:ref}`eg-b`."


def test_strip_doubled_noun_refs_algorithm_now_strips_for_kebab_labels():
    """Now that `algo-` routes to {prf:ref}, the Algorithm-stripper
    actually fires on real dp1 prose."""
    text = "shown in Algorithm {prf:ref}`algo-fsvfi`."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "shown in {prf:ref}`algo-fsvfi`."


def test_cross_ref_list_target_routes_to_numref():
    """`list:foo` / `list-foo` labels target enumerated `{code-block}`
    directives. The right MyST role is `{numref}` (lets the renderer
    show "Program N"), not `{ref}` (which dumps the caption inline)."""
    text = (
        '[\\[list:two\\_period\\_job\\_search\\]]'
        '(#list:two_period_job_search)'
        '{reference-type="ref" reference="list:two_period_job_search"}'
    )
    out = postprocess.convert_cross_references(text)
    assert '{numref}`list-two_period_job_search`' in out
    assert '{ref}`list-' not in out


def test_strip_doubled_noun_refs_plural_guards_unrelated_prefix():
    """The prefix guard applies to plurals the same as singulars —
    don't strip 'Chapters' before a ref whose target isn't a chapter."""
    text = "Chapters {prf:ref}`l-foo` should stay (l- is a lemma prefix)."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == text


def test_strip_doubled_section_symbol_basic():
    text = "in §{ref}`s-foo` and §{ref}`ss-bar`"
    out = postprocess.strip_doubled_section_symbol(text)
    assert out == "in {ref}`s-foo` and {ref}`ss-bar`"


def test_strip_doubled_section_symbol_with_nbsp_and_space():
    text = "§ {ref}`s-foo` and §\xa0{ref}`sec-bar`"
    out = postprocess.strip_doubled_section_symbol(text)
    assert out == "{ref}`s-foo` and {ref}`sec-bar`"


def test_strip_doubled_section_symbol_eg_prefix():
    """eg- was added after dp2 surfaced \\S\\ref{eg:foo} (followup to #016)."""
    text = "in §{ref}`eg-rsnotldp` we showed..."
    out = postprocess.strip_doubled_section_symbol(text)
    assert out == "in {ref}`eg-rsnotldp` we showed..."


def test_strip_doubled_section_symbol_preserves_external_refs():
    """`§10.2 of {cite}…` is a legitimate external section reference;
    must NOT be stripped (no {ref} follows the §)."""
    text = "see §10.2 of {cite}`sargent2025dynamic`"
    out = postprocess.strip_doubled_section_symbol(text)
    assert out == text


# ── Frontmatter style flag ───────────────────────────────────────────────────


def test_frontmatter_absorbed_default():
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "(c-foo)=\n# Foo\n\nBody text.\n"
    out = postprocess.add_frontmatter(body, "Foo")
    assert out.startswith("---\n")
    assert 'title: "Foo"' in out
    assert "label: c-foo" in out
    # Heading consumed
    assert "# Foo" not in out
    assert "Body text." in out


def test_frontmatter_standalone():
    postprocess._FRONTMATTER_STYLE = "standalone"
    body = "(c-foo)=\n# Foo\n\nBody text.\n"
    out = postprocess.add_frontmatter(body, "Foo")
    # No YAML; heading preserved
    assert not out.startswith("---\n")
    assert out.startswith("(c-foo)=\n# Foo")
    assert "Body text." in out


def test_frontmatter_idempotent_absorbed():
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "(c-foo)=\n# Foo\n\nBody.\n"
    once = postprocess.add_frontmatter(body, "Foo")
    twice = postprocess.add_frontmatter(once, "Foo")
    assert once == twice


# ── Duplicate-H1 stripping (issue #3) ────────────────────────────────────────


def test_frontmatter_strips_bare_h1_that_matches_title():
    """Source ``\\chapter{Preface}`` with no \\label yields pandoc
    ``# Preface`` (no attribute block). Combined with a config-supplied
    ``title: Preface``, the pipeline would otherwise emit both a YAML
    title and a body H1 — two identical headings in a row."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "# Preface\n\nThis book is the second of a two-volume sequence.\n"
    out = postprocess.add_frontmatter(body, "Preface")
    assert 'title: "Preface"' in out
    assert "# Preface" not in out
    assert "This book is the second" in out


def test_frontmatter_keeps_bare_h1_when_title_differs():
    """If the body H1 doesn't match the configured title, the author
    wrote two distinct things — leave both alone."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "# Common Symbols\n\nGlossary follows.\n"
    out = postprocess.add_frontmatter(body, "Notation")
    assert 'title: "Notation"' in out
    assert "# Common Symbols" in out


def test_frontmatter_no_body_h1_is_noop_for_duplicate_strip():
    """When the body starts with prose (no H1 at all), the strip
    regex shouldn't match and the body must pass through unchanged."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "First paragraph of content.\n"
    out = postprocess.add_frontmatter(body, "Preface")
    assert 'title: "Preface"' in out
    assert "First paragraph of content." in out


def test_frontmatter_does_not_strip_h1_later_in_body():
    """A heading buried inside the body that happens to share the title
    must NOT be stripped — only a duplicate at the very start of the
    body counts."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "Introductory prose.\n\n# Preface\n\nMore content.\n"
    out = postprocess.add_frontmatter(body, "Preface")
    assert 'title: "Preface"' in out
    # The buried heading survives.
    assert "# Preface" in out


def test_frontmatter_per_call_style_override_to_standalone():
    """add_frontmatter's `style` arg lets a single call use standalone
    even when the module default is absorbed — needed for books with
    mixed conventions (numbered chapters absorbed, front-matter
    standalone, or vice versa)."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "(c-foo)=\n# Foo\n\nBody.\n"
    out = postprocess.add_frontmatter(body, "Foo", style="standalone")
    assert not out.startswith("---\n")
    assert out.startswith("(c-foo)=\n# Foo")


def test_frontmatter_per_call_style_override_to_absorbed():
    postprocess._FRONTMATTER_STYLE = "standalone"
    body = "(c-foo)=\n# Foo\n\nBody.\n"
    out = postprocess.add_frontmatter(body, "Foo", style="absorbed")
    assert out.startswith("---\n")
    assert "label: c-foo" in out


def test_chapter_styles_populated_from_config():
    """apply_config should pick up per-stem `frontmatter_style` from
    chapters[] and extra_files[] entries, and leave unspecified stems
    out of the override map (so they inherit the global default)."""
    cfg = {
        "source_dir": ".",
        "frontmatter_style": "standalone",
        "chapters": [
            {"stem": "ch_intro", "title": "Intro"},
            {"stem": "ch_other", "title": "Other", "frontmatter_style": "absorbed"},
        ],
        "extra_files": [
            {"stem": "preface", "title": "Preface", "frontmatter_style": "absorbed"},
        ],
    }
    postprocess.apply_config(cfg)
    assert postprocess.CHAPTER_STYLES == {
        "ch_other": "absorbed",
        "preface": "absorbed",
    }
    # Restore default for other tests.
    postprocess._FRONTMATTER_STYLE = "absorbed"


# ── Broken inline math detector (validate.find_broken_inline_math) ──────────


def test_broken_math_detects_blockquote_after_open_dollar():
    """The classic MyST trap: a line opens inline math with `$`, the
    closing `$` is on the next line, and that line starts with `>` —
    MyST then renders the `>` as a blockquote marker instead of math."""
    text = "Consider the value $f(x)\n> 0$ when applicable.\n"
    diags = validate.find_broken_inline_math(text, "ch_x.md")
    assert len(diags) == 1
    assert "ch_x.md" in diags[0]


def test_broken_math_ignores_multiline_math_without_blockquote_marker():
    """Inline math wrapped across lines where the continuation line is
    ordinary content (not `>`) renders correctly in MyST and must NOT
    be flagged — that pattern is common in --wrap=none output and is
    not a bug. Only the `>`-leading-the-next-line case is broken."""
    text = "Let $a = b\nc = d$ be defined.\n"
    assert validate.find_broken_inline_math(text, "f.md") == []


def test_broken_math_ignores_fenced_code_block():
    text = (
        "```python\n"
        "x = '$foo\n"
        "> bar$'\n"
        "```\n"
    )
    assert validate.find_broken_inline_math(text, "f.md") == []


def test_broken_math_ignores_display_math_block():
    text = (
        "$$\n"
        "a = b\n"
        "> 0\n"
        "$$\n"
    )
    assert validate.find_broken_inline_math(text, "f.md") == []


def test_broken_math_clean_paragraph_returns_empty():
    text = "Inline math $a = b$ on one line is fine.\n\nNext paragraph.\n"
    assert validate.find_broken_inline_math(text, "f.md") == []


# ── postprocess.rewrites (book-specific Markdown rewrites) ──────────────────


def _set_postprocess_rewrites(rules):
    """Helper: apply just the postprocess.rewrites portion of a config so
    individual tests don't need to feed the full apply_config."""
    cfg = {"source_dir": ".", "postprocess": {"rewrites": rules}}
    postprocess.apply_config(cfg)


def test_postprocess_rewrites_global_applies_to_every_stem():
    _set_postprocess_rewrites([
        {"from": r"\bSI\b", "to": "System I"},
    ])
    a = postprocess.apply_postprocess_rewrites("Discuss SI here.", "ch_intro")
    b = postprocess.apply_postprocess_rewrites("Other SI ref.",    "ch_other")
    assert "System I" in a
    assert "System I" in b


def test_postprocess_rewrites_stem_scoped_skips_other_chapters():
    _set_postprocess_rewrites([
        {"from": r"^\*\*Mathematical Notation\*\*$",
         "to":   "## Mathematical Notation",
         "stems": ["common_symbols"]},
    ])
    target  = "**Mathematical Notation**"
    in_scope = postprocess.apply_postprocess_rewrites(target, "common_symbols")
    out_of_scope = postprocess.apply_postprocess_rewrites(target, "ch_intro")
    assert in_scope == "## Mathematical Notation"
    assert out_of_scope == target


def test_postprocess_rewrites_multiline_anchors_work():
    """Rewrites are compiled with re.MULTILINE — `^...$` should match a
    line within a larger body, not just the whole string."""
    _set_postprocess_rewrites([
        {"from": r"^\*\*Heading\*\*$", "to": "## Heading"},
    ])
    text = "Prelude.\n\n**Heading**\n\nFollow.\n"
    out = postprocess.apply_postprocess_rewrites(text, "ch_x")
    assert "## Heading" in out
    assert "**Heading**" not in out
    # Surrounding content preserved
    assert "Prelude." in out
    assert "Follow." in out


def test_postprocess_rewrites_order_matters():
    """List order = application order. A later rewrite sees the output
    of earlier ones."""
    _set_postprocess_rewrites([
        {"from": r"A", "to": "B"},
        {"from": r"B", "to": "C"},
    ])
    assert postprocess.apply_postprocess_rewrites("A", "ch_x") == "C"


def test_postprocess_rewrites_validation_rejects_missing_keys():
    with pytest.raises(SystemExit) as exc:
        _set_postprocess_rewrites([{"from": "x"}])
    assert "'from' and 'to'" in str(exc.value)


def test_postprocess_rewrites_validation_rejects_bad_regex():
    with pytest.raises(SystemExit) as exc:
        _set_postprocess_rewrites([{"from": "(unclosed", "to": "x"}])
    assert "bad regex" in str(exc.value)


def test_postprocess_rewrites_validation_rejects_bad_stems_type():
    with pytest.raises(SystemExit) as exc:
        _set_postprocess_rewrites([
            {"from": "x", "to": "y", "stems": "not-a-list"},
        ])
    assert "stems" in str(exc.value)


def test_postprocess_rewrites_empty_config_is_noop():
    # No postprocess.rewrites declared → POSTPROCESS_REWRITES stays empty.
    postprocess.apply_config({"source_dir": "."})
    assert postprocess.POSTPROCESS_REWRITES == []
    assert postprocess.apply_postprocess_rewrites("Hello.", "ch_x") == "Hello."


def test_chapter_styles_rejects_invalid_value():
    cfg = {
        "source_dir": ".",
        "chapters": [
            {"stem": "ch_x", "title": "X", "frontmatter_style": "weird"},
        ],
    }
    with pytest.raises(SystemExit) as exc:
        postprocess.apply_config(cfg)
    assert "frontmatter_style" in str(exc.value)


def test_frontmatter_standalone_synthesises_when_missing():
    """If a body has been processed once in absorbed mode and then re-run
    in standalone mode, the (label)= heading should be reconstructed
    from the existing YAML label."""
    postprocess._FRONTMATTER_STYLE = "standalone"
    body = '---\ntitle: "Foo"\nlabel: c-foo\n---\n\nBody.\n'
    out = postprocess.add_frontmatter(body, "Foo")
    assert out.startswith("(c-foo)=\n# Foo\n")


# ── Heading auto-id class strip + explicit-label preference (FIX Issue 2) ────


def test_section_label_strips_unnumbered_class():
    """Pandoc emits ``# Title {#slug .unnumbered}`` for \\chapter*{}; the
    ``.unnumbered`` class must not leak into the MyST label."""
    body = "# Common Symbols {#common-symbols .unnumbered}\n\nBody.\n"
    out = postprocess.convert_section_labels(body)
    assert "(common-symbols)=" in out
    assert ".unnumbered" not in out


def test_section_label_strips_multiple_classes():
    body = "# Title {#slug .unnumbered .unlisted}\n"
    out = postprocess.convert_section_labels(body)
    assert "(slug)=" in out
    assert "# Title" in out
    assert ".unnumbered" not in out
    assert ".unlisted" not in out


def test_frontmatter_prefers_explicit_label_over_heading_autoid():
    """When ``\\chapter*{Title}`` + separate ``\\label{c:cs}`` produces
    a heading auto-id slug AND a body anchor, the explicit body anchor
    must win in the YAML label, and the body anchor must be removed."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = (
        "(common-symbols-and-terminology)=\n"
        "# Common Symbols and Terminology\n"
        "\n"
        "(c-cs)=\n"
        "Body text.\n"
    )
    out = postprocess.add_frontmatter(body, "Notation")
    assert "label: c-cs" in out
    assert "common-symbols-and-terminology" not in out
    assert "(c-cs)=" not in out
    assert "Body text." in out


def test_frontmatter_uses_autoid_when_no_explicit_label():
    """Plain ``\\chapter*{Foo}`` (no explicit \\label) still gets the
    auto-id slug as its label — there's no better candidate."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "(some-chapter)=\n# Some Chapter\n\nBody.\n"
    out = postprocess.add_frontmatter(body, "Some Chapter")
    assert "label: some-chapter" in out


def test_frontmatter_no_label_when_heading_unanchored():
    """``\\chapter{Preface}`` (no \\label, numbered or otherwise) emits
    no anchor; frontmatter should likewise carry no label."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = "Body text without heading.\n"
    out = postprocess.add_frontmatter(body, "Preface")
    assert 'title: "Preface"' in out
    assert "label:" not in out


def test_frontmatter_explicit_label_idempotent_absorbed():
    """Re-running the pipeline on its own output must be a no-op once the
    explicit label has been absorbed into YAML."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = (
        "(common-symbols-and-terminology)=\n"
        "# Common Symbols and Terminology\n"
        "\n"
        "(c-cs)=\n"
        "Body.\n"
    )
    once = postprocess.add_frontmatter(body, "Notation")
    twice = postprocess.add_frontmatter(once, "Notation")
    assert once == twice


# ── natbib citation variant decoding (FIX Issue 3) ───────────────────────────


def test_citation_natbib_marker_citep():
    """Marker emitted by preprocess for \\citep — single key."""
    body = "See \\[\\[CITEP:smith2020\\]\\] for details."
    out = postprocess.decode_natbib_markers(body)
    assert out == "See {cite:p}`smith2020` for details."


def test_citation_natbib_marker_citep_multi():
    """Marker for \\citep with multiple keys — strip spaces around commas."""
    body = "See \\[\\[CITEP:a, b, c\\]\\] end."
    out = postprocess.decode_natbib_markers(body)
    assert out == "See {cite:p}`a,b,c` end."


def test_citation_natbib_marker_citealp():
    """\\citealp renders as 'Author Year' (no parens) → cite:t."""
    body = "Following \\[\\[CITEALP:stokey1989recursive\\]\\] we have"
    out = postprocess.decode_natbib_markers(body)
    assert "{cite:t}`stokey1989recursive`" in out


def test_citation_natbib_marker_citealp_multi():
    body = "e.g. \\[\\[CITEALP:stokey1989recursive,puterman2005markov\\]\\]."
    out = postprocess.decode_natbib_markers(body)
    assert "{cite:t}`stokey1989recursive,puterman2005markov`" in out


def test_citation_natbib_marker_citeauthor_and_citeyear():
    body = "\\[\\[CITEAUTHOR:bellman1957\\]\\] in \\[\\[CITEYEAR:bellman1957\\]\\]."
    out = postprocess.decode_natbib_markers(body)
    assert "{cite:author}`bellman1957`" in out
    assert "{cite:year}`bellman1957`" in out


def test_citation_natbib_marker_citeyearpar_adds_parens():
    """\\citeyearpar renders 'year' with parens; output should wrap the
    cite role with literal parens so the rendered form is e.g. '(1957)'."""
    body = "Bellman's \\[\\[CITEYEARPAR:bellman1957\\]\\] monograph"
    out = postprocess.decode_natbib_markers(body)
    assert "({cite:year}`bellman1957`)" in out


def test_citation_marker_decode_protects_against_cross_ref_greed():
    """Regression for lesson 020 / lesson 002: when a natbib marker
    appears in the same paragraph as a pandoc cross-ref, decoding must
    run BEFORE convert_cross_references — otherwise the cross-ref regex
    matches greedily from the marker's [ to the ref's ](#x){...},
    swallowing the marker entirely."""
    pandoc_out = (
        r"preferences \[\[CITEP:epstein1989risk, weil1990nonexpected\]\] "
        r'play. Bellman equation [\[eq:osbell\]](#eq:osbell)'
        r'{reference-type="eqref" reference="eq:osbell"} becomes'
    )
    # Correct order: decode first, then cross-refs.
    fixed = postprocess.decode_natbib_markers(pandoc_out)
    fixed = postprocess.convert_cross_references(fixed)
    assert "{cite:p}`epstein1989risk,weil1990nonexpected`" in fixed
    assert "{eq}`eq-osbell`" in fixed
    # Demonstrate the failure mode: reversed order eats the marker.
    bad = postprocess.convert_cross_references(pandoc_out)
    assert "epstein1989risk" not in bad


def test_citation_pandoc_suppress_author_decoded():
    """Pandoc emits [-@key] for \\citeyear when the preprocess rewrite
    is bypassed (or for natbib variants we haven't yet mapped). The
    bracketed form must decode to {cite:year} cleanly, not leave junk."""
    body = "Bellman's [-@bellman1957dynamic] monograph"
    out = postprocess.convert_citations(body)
    assert "{cite:year}`bellman1957dynamic`" in out
    # Stray brackets / dash must not survive
    assert "[-" not in out
    assert "[-@" not in out


def test_citation_pandoc_native_unchanged():
    """Pandoc's native [@key] and @key forms still map to {cite} and
    {cite:t} respectively — marker decoding doesn't disturb them."""
    body = "[@smith2020] and @jones2019 in a paragraph."
    out = postprocess.convert_citations(body)
    assert "{cite}`smith2020`" in out
    assert "{cite:t}`jones2019`" in out


def test_citation_idempotent():
    """Re-running on already-converted output is a no-op."""
    body = "See \\[\\[CITEP:smith2020\\]\\] and [@jones2019]."
    once = postprocess.convert_citations(body)
    twice = postprocess.convert_citations(once)
    assert once == twice


# ── simple_table → list-table (FIX Issue 1) ──────────────────────────────────


def _table(*rows: str, leading: str = "  ", col1_width: int = 10,
           gap: int = 2, col2_width: int = 20) -> str:
    """Build a pandoc-shaped 2-col simple_table. ``col1_width`` dashes,
    ``gap`` spaces, ``col2_width`` dashes — col-2 content must start at
    position ``len(leading) + col1_width + gap``."""
    rule = leading + ("-" * col1_width) + (" " * gap) + ("-" * col2_width)
    col2_start = len(leading) + col1_width + gap
    out_lines = [rule]
    for a, b in (r.split("|", 1) for r in rows):
        a = a.strip()
        b = b.strip()
        line = leading + a + (" " * (col1_width + gap - len(a))) + b
        # Pad/trim so col2 content lands at col2_start
        assert line[col2_start] == b[0], (line, col2_start, b)
        out_lines.append(line)
    out_lines.append(rule)
    return "\n".join(out_lines) + "\n"


def test_simple_table_two_column_basic():
    body = (
        "Intro.\n\n"
        + _table(r"$\alpha$ | the first letter",
                 r"$\beta$  | the second letter")
        + "\nAfter.\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 0" in out
    assert "* - $\\alpha$" in out
    assert "  - the first letter" in out
    assert "* - $\\beta$" in out
    assert "  - the second letter" in out
    # The dash rules should be gone.
    assert "----------" not in out
    # Surrounding prose preserved.
    assert "Intro." in out
    assert "After." in out


def test_simple_table_preserves_math_and_refs_in_cells():
    body = _table(r"$x$ | see {ref}`eg-foo`")
    out = postprocess.convert_simple_tables(body)
    assert "* - $x$" in out
    assert "  - see {ref}`eg-foo`" in out


def test_simple_table_with_caption():
    body = _table("A | B") + "\n  : My caption\n"
    out = postprocess.convert_simple_tables(body)
    assert ":caption: My caption" in out
    # Caption line should be consumed, not left behind.
    assert "  : My caption" not in out


def test_simple_table_three_column_left_alone():
    """3+ column tables stay as raw simple_tables. Out of scope per FIX
    Issue 1's "first cut" — wider tables have more layout nuance."""
    body = (
        "  ----  ----  ----\n"
        "  A     B     C\n"
        "  D     E     F\n"
        "  ----  ----  ----\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Untouched.
    assert "```{list-table}" not in out
    assert "----  ----  ----" in out


def test_simple_table_skipped_inside_code_fence():
    body = "```\n" + _table("A | B") + "```\n"
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" not in out
    # The original content is preserved verbatim.
    assert "----------" in out


def test_simple_table_unclosed_rule_passes_through():
    """Defensive: a lone dash-rule with no closing match shouldn't
    silently swallow the rest of the file."""
    body = (
        "  ----------  --------------------\n"
        "  A           B\n"
        "(no closing rule)\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" not in out
    assert "(no closing rule)" in out


def test_simple_table_idempotent():
    body = _table("A | B")
    once = postprocess.convert_simple_tables(body)
    twice = postprocess.convert_simple_tables(once)
    assert once == twice


def test_multiline_table_blank_lines_separate_rows():
    """When pandoc emits multiline_tables (blank lines between rows),
    each blank line is a row separator. Non-blank lines within the
    same row join into a single cell."""
    body = (
        "  ----------  --------------------\n"
        "  A           short one\n"
        "\n"
        "  B           a longer\n"
        "              wrapped value\n"
        "\n"
        "  ----------  --------------------\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "* - A" in out
    assert "  - short one" in out
    assert "* - B" in out
    assert "  - a longer wrapped value" in out


def test_multiline_table_bounded_by_fenced_div_closer():
    """GH #24 — pandoc renders ``\\begin{center}\\begin{tabular}...`` as
    a multiline_table inside a ``::: center`` fenced div, with an
    *opening* dash-rule but no closing one. Before the fix, the forward
    scan for a matching closing rule ran on past the table body, past
    the ``:::`` close, past any intervening paragraphs, and only stopped
    at the *next* table's opening rule — fusing two tables and the
    prose between them into one mangled list-table."""
    body = (
        "::: center\n"
        "  ----------  --------------------\n"
        "  $\\alpha$    first letter\n"
        "  $\\beta$     second letter\n"
        ":::\n"
        "\n"
        "Paragraph that should NOT be consumed as a table row.\n"
        "\n"
        "::: center\n"
        "  ----  ----------------------------------------\n"
        "  Code  Description\n"
        "  A     first\n"
        "  B     second\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert out.count("```{list-table}") == 2, \
        "both tables should convert independently, not fuse"
    assert "* - $\\alpha$" in out
    assert "* - $\\beta$" in out
    assert "Paragraph that should NOT be consumed" in out
    # The first table's rows must NOT include the paragraph or the
    # second table's header line.
    first_table = out.split("```{list-table}", 2)[1].split("```", 1)[0]
    assert "Paragraph" not in first_table
    assert "Description" not in first_table


def test_frontmatter_does_not_steal_first_section_label():
    """Regression: when the chapter has its own explicit label folded into
    the heading auto-id (``\\chapter{Foo}\\label{c:foo}`` →
    ``(c-foo)=\\n# Foo``) and is immediately followed by a *section*
    anchor (``(s-bar)=\\n## Bar``), the section's anchor must NOT be
    promoted to the chapter's frontmatter label."""
    postprocess._FRONTMATTER_STYLE = "absorbed"
    body = (
        "(c-apps)=\n"
        "# Additional Applications\n"
        "\n"
        "(s-optstop)=\n"
        "## Job Search\n"
        "\n"
        "Body.\n"
    )
    out = postprocess.add_frontmatter(body, "Additional Applications")
    assert "label: c-apps" in out
    assert "s-optstop" not in out.split("---\n\n", 1)[0]  # not in frontmatter
    assert "(s-optstop)=" in out  # section anchor preserved in body
    assert "## Job Search" in out


def test_frontmatter_explicit_label_standalone():
    """Standalone style: explicit body anchor wins, heading uses it as
    the (label)= prefix, duplicate body anchor is dropped."""
    postprocess._FRONTMATTER_STYLE = "standalone"
    body = (
        "(common-symbols-and-terminology)=\n"
        "# Common Symbols and Terminology\n"
        "\n"
        "(c-cs)=\n"
        "Body.\n"
    )
    out = postprocess.add_frontmatter(body, "Notation")
    assert out.startswith("(c-cs)=\n# Common Symbols and Terminology\n")
    assert "common-symbols-and-terminology" not in out
    # Only one (c-cs)= anchor survives
    assert out.count("(c-cs)=") == 1


# ── Config-driven ENV_MAP extension ──────────────────────────────────────────


# ── Strip blank lines inside display math (issue #11) ──────────────────────


def test_strip_blank_lines_in_math_collapses_whitespace_line():
    """``\\qedhere`` is stripped late in the pipeline; its preceding
    whitespace survives as a blank line inside ``$$ … $$``, which MyST
    rejects as 'No input for math node'."""
    body = (
        "$$\n"
        "\\tau s(A)\n"
        "        = s(\\tau A).\n"
        "        \n"   # whitespace-only line from \qedhere strip
        "$$ (eq-foo)\n"
    )
    out = postprocess.strip_blank_lines_in_math(body)
    # No blank/whitespace-only lines inside the block
    assert "= s(\\tau A).\n$$" in out
    # Closing-with-label form preserved
    assert "$$ (eq-foo)" in out


def test_strip_blank_lines_in_math_collapses_multiple_blanks():
    body = "$$\nx = 1\n\n\n\ny = 2\n$$\n"
    out = postprocess.strip_blank_lines_in_math(body)
    assert out == "$$\nx = 1\ny = 2\n$$\n"


def test_strip_blank_lines_in_math_noop_when_clean():
    body = "$$\nx = 1\ny = 2\n$$\n"
    assert postprocess.strip_blank_lines_in_math(body) == body


def test_strip_blank_lines_in_math_does_not_touch_inline_math():
    """The regex requires ``$$\\n`` — inline ``$x$`` paragraphs are
    left alone."""
    body = "Some $inline$ math here and a paragraph.\n\nAnother $x$ ref.\n"
    assert postprocess.strip_blank_lines_in_math(body) == body


def test_strip_blank_lines_in_math_does_not_match_inline_closing_dollar():
    """Regression for issue #12: inline ``$$ … $$`` at end of a bullet
    must NOT trigger the block-math regex. Without anchoring the
    opening ``$$`` to a line start, the non-greedy ``(.*?)`` extends
    across the next bullets / paragraph until it finds the next
    ``\\n$$`` (a real block opener), collapsing every blank line in
    between."""
    body = (
        "- $\\Gamma$ defines $$\\Gsf \\coloneq \\{(x,a) : a \\in \\Gamma(x)\\},$$\n"
        "\n"
        "- a reward function $r$,\n"
        "\n"
        "- a stochastic kernel $P$.\n"
        "\n"
        "Some prose follows here.\n"
        "\n"
        "$$\n"
        "\\EE \\sum_{t \\geq 0} \\beta^t r(X_t, A_t)\n"
        "$$\n"
    )
    out = postprocess.strip_blank_lines_in_math(body)
    # Bullets stay separated by blank lines
    assert ",$$\n\n- a reward" in out
    assert "- a reward function $r$,\n\n- a stochastic" in out
    # Prose paragraph stays separated from the bullets
    assert "kernel $P$.\n\nSome prose" in out
    # And from the real display math block
    assert "Some prose follows here.\n\n$$" in out
    # The real block at the bottom is still well-formed
    assert "$$\n\\EE \\sum_{t \\geq 0} \\beta^t r(X_t, A_t)\n$$" in out


def test_strip_blank_lines_in_math_preserves_aligned_body():
    """Multi-line aligned bodies are common; only blanks collapse."""
    body = (
        "$$\n"
        "\\begin{aligned}\n"
        "a &= b \\\\\n"
        "c &= d\n"
        "\\end{aligned}\n"
        "$$\n"
    )
    out = postprocess.strip_blank_lines_in_math(body)
    assert "\\begin{aligned}" in out
    assert "a &= b" in out
    assert "c &= d" in out
    assert "\\end{aligned}" in out


# ── TIKZCD_INLINE_MAP replacement literals (issue #7) ───────────────────────


def test_tikzcd_replacement_with_latex_backslash_escapes():
    """Authors write LaTeX-flavoured Markdown in tikz_overrides.py
    replacements (e.g. ``$\\hat U$``, ``\\Phi``). Under Python 3.13 the
    regex parser rejects ``\\h``, ``\\P``, etc. when those are treated
    as a regex replacement string. The lambda wrap bypasses escape
    parsing so authors can write LaTeX freely in their override files."""
    postprocess.TIKZCD_INLINE_MAP = {
        'ch_x': [{
            'pattern':     r'\$\$tikzcd-placeholder\$\$',
            'replacement': (
                '```{figure} figures/conjugacy.svg\n'
                ':label: f-conjugacy\n'
                '\n'
                r'$(\hat U, \hat T)$ under $\Phi$ and $\beta$.'
                '\n```'
            ),
        }],
    }
    body = 'Before.\n\n$$tikzcd-placeholder$$\n\nAfter.\n'
    # Must not raise re.PatternError under Python 3.13+
    out = postprocess.resolve_tikz_figures(body, 'ch_x')
    assert r'$(\hat U, \hat T)$ under $\Phi$ and $\beta$.' in out
    assert '```{figure} figures/conjugacy.svg' in out
    # Surrounding prose preserved
    assert 'Before.' in out and 'After.' in out
    # Restore for other tests
    postprocess.TIKZCD_INLINE_MAP = {}


def test_tikzcd_replacement_left_alone_when_stem_not_in_map():
    """No-op when there's no entry for this stem."""
    postprocess.TIKZCD_INLINE_MAP = {
        'ch_other': [{'pattern': 'X', 'replacement': 'Y'}],
    }
    body = 'X marks the spot.\n'
    out = postprocess.resolve_tikz_figures(body, 'ch_x')
    assert out == body
    postprocess.TIKZCD_INLINE_MAP = {}


# ── Mid-line hypertarget marker inside proof bodies (issue #4) ──────────────


def test_proof_midline_hypertarget_promoted_to_label():
    """`\\begin{proof}[Proof of Lemma~\\ref{l:eqfst}]\\label{p:l:eqfst}`
    renders as a pandoc ``::: proof`` block whose first body line is::

        *Proof of {prf:ref}`l-eqfst`.* []{#p:l:eqfst label="p:l:eqfst"} body…

    The mid-line ``[]{#…}`` marker must be stripped and the label
    promoted to ``:label:`` on the directive (issue #4)."""
    body = (
        '::: proof\n'
        '*Proof of {prf:ref}`l-eqfst`.* []{#p:l:eqfst label="p:l:eqfst"} '
        'Regarding (i), fix $\\phi$.\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    assert '```{prf:proof}' in out
    assert ':label: p-l-eqfst' in out
    # Marker token gone from the body
    assert '[]{#p:l:eqfst' not in out
    # Surrounding text preserved (proof opener + body prose)
    assert '*Proof of {prf:ref}`l-eqfst`.*' in out
    assert 'Regarding (i), fix' in out


def test_proof_midline_hypertarget_strips_bare_proof_opener():
    """For a `\\begin{proof}\\label{p:foo}` (no `[Proof of X]` arg),
    pandoc emits `*Proof.* []{#p:foo label="p:foo"} body`. The mid-line
    marker is stripped, the label promoted, AND the residual `*Proof.*`
    opener is also removed — sphinx-proof adds its own."""
    body = (
        '::: proof\n'
        '*Proof.* []{#p:foo label="p:foo"} body text here.\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    assert ':label: p-foo' in out
    assert 'body text here.' in out
    # *Proof.* opener stripped (sphinx-proof renders its own)
    assert '*Proof.*' not in out


# ── Multi-label environments (issue #10) ────────────────────────────────────


def test_multi_label_exercise_promotes_first_emits_div_for_rest():
    """`\\begin{Exercise}\\label{a}\\label{b}` becomes a directive with
    `:label: a` plus a sibling `{div}` anchor for `b` (so `{ref}` resolves
    both labels)."""
    body = (
        '::: Exercise\n'
        '[]{#ex:boeq label="ex:boeq"}[]{#ex:egmdps label="ex:egmdps"}'
        ' Given $v$, prove that...\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    # Sibling {div} for the secondary label, ABOVE the directive
    assert '```{div}' in out
    assert ':name: ex-egmdps' in out
    # First label promoted to :label:
    assert ':label: ex-boeq' in out
    # No leftover inline anchor artifacts
    assert '[]{#ex:' not in out
    # Body content preserved
    assert 'Given $v$, prove that...' in out
    # {div} block comes before the directive header
    div_idx = out.index('```{div}')
    exercise_idx = out.index('```{exercise}')
    assert div_idx < exercise_idx


def test_multi_label_proposition_two_separate_anchors_on_one_line():
    body = (
        '::: proposition\n'
        '[]{#p:convmx label="p:convmx"}[]{#p:convmx2 label="p:convmx2"}'
        ' If $\\rR$ is convex, then $\\rR$ is globally stable.\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    assert ':name: p-convmx2' in out
    assert ':label: p-convmx' in out
    assert '[]{#p:' not in out


def test_multi_label_three_anchors_emits_two_divs():
    """Three labels → first promoted, two sibling {div}s."""
    body = (
        '::: lemma\n'
        '[]{#l:a label="l:a"}[]{#l:b label="l:b"}[]{#l:c label="l:c"}'
        ' Body text.\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    assert ':label: l-a' in out
    assert ':name: l-b' in out
    assert ':name: l-c' in out
    assert out.count('```{div}') == 2


def test_standalone_labels_strips_midline_footnote_orphan():
    """`\\footnote{\\label{fn:hcon}...}` produces a markdown footnote body
    `[^1]: []{#fn:hcon label="fn:hcon"}body…`. The mid-line anchor has
    no MyST destination (footnotes use `[^N]` syntax for refs), so it
    must be stripped (issue #10)."""
    body = '[^1]: []{#fn:hcon label="fn:hcon"}For X to be well-defined, …\n'
    out = postprocess.convert_standalone_labels(body)
    assert '[^1]: For X to be well-defined, …' in out
    assert '[]{#fn:hcon' not in out


def test_standalone_labels_keeps_own_line_anchor_as_myst_target():
    """Own-line anchors still convert to `(X)=` — regression guard
    against the second strip eating the first sub's output."""
    body = '[]{#sec:foo label="sec:foo"}\n\nSection content.\n'
    out = postprocess.convert_standalone_labels(body)
    assert '(sec-foo)=' in out
    assert 'Section content.' in out


def test_single_label_still_works_after_refactor():
    """Regression guard: the single-label case (the common shape) must
    still produce `:label: X` with no extra {div} blocks."""
    body = (
        '::: theorem\n'
        '[]{#t:foo label="t:foo"} The theorem statement.\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    assert ':label: t-foo' in out
    assert 'The theorem statement.' in out
    assert '```{div}' not in out


def test_proof_midline_hypertarget_works_with_real_dp1_shape():
    """End-to-end shape from book-dp1 appB.md."""
    body = (
        '::: proof\n'
        '*Proof of {prf:ref}`l-eqfst`.* []{#p:l:eqfst label="p:l:eqfst"} '
        'Regarding (i), fix x.\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    expected_substrings = [
        '```{prf:proof}',
        ':label: p-l-eqfst',
        '*Proof of {prf:ref}`l-eqfst`.*',
        'Regarding (i), fix x.',
        '```',
    ]
    for s in expected_substrings:
        assert s in out, f"missing: {s!r} in:\n{out}"


def test_extra_environments_extends_env_map():
    # Reset the dicts to defaults before testing.
    import importlib
    importlib.reload(postprocess)
    assert "Conjecture" not in postprocess.ENV_MAP
    postprocess.apply_config({
        "source_dir": "..",
        "chapters": [{"stem": "c", "title": "X"}],
        "extra_environments": {"Conjecture": "prf:conjecture"},
    })
    assert postprocess.ENV_MAP["Conjecture"] == "prf:conjecture"
    # Defaults still present
    assert postprocess.ENV_MAP["theorem"] == "prf:theorem"


def test_skip_environments_unions_with_defaults():
    import importlib
    importlib.reload(postprocess)
    postprocess.apply_config({
        "source_dir": "..",
        "chapters": [{"stem": "c", "title": "X"}],
        "skip_environments": ["framed"],
    })
    assert "framed" in postprocess.ENV_SKIP
    # Defaults preserved
    assert "center" in postprocess.ENV_SKIP


def test_extra_environments_rejects_bad_type():
    """Schema validator catches this before the inner type-check fires."""
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="extra_environments must be"):
        postprocess.apply_config({
            "source_dir": "..",
            "extra_environments": "not a dict",
        })


def test_skip_environments_rejects_bad_type():
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="skip_environments must be"):
        postprocess.apply_config({
            "source_dir": "..",
            "skip_environments": "not a list",
        })


def test_frontmatter_style_rejects_bad_value():
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="frontmatter_style"):
        postprocess.apply_config({
            "source_dir": "..",
            "frontmatter_style": "weird",
        })


def test_whitespace_compression_rejects_bad_value():
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="whitespace_compression"):
        postprocess.apply_config({
            "source_dir": "..",
            "whitespace_compression": "tight",
        })


# ── Config schema validation ────────────────────────────────────────────────


def test_validate_config_rejects_unknown_key_with_typo_hint():
    """Catching typos is the whole point of the validator."""
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match=r"whitespace_comression.*whitespace_compression"):
        postprocess.validate_config({
            "source_dir": "..",
            "whitespace_comression": "compact",  # typo
        })


def test_validate_config_requires_source_dir():
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="source_dir"):
        postprocess.validate_config({})


def test_validate_config_rejects_wrong_type():
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="bibliography must be"):
        postprocess.validate_config({
            "source_dir": "..",
            "bibliography": ["not", "a", "string"],
        })


def test_validate_config_chapters_need_stem():
    import importlib
    importlib.reload(postprocess)
    with pytest.raises(SystemExit, match="chapters\\[1\\]"):
        postprocess.validate_config({
            "source_dir": "..",
            "chapters": [{"stem": "ok"}, {"title": "no stem"}],
        })


def test_validate_config_nullable_bibliography():
    """``bibliography: null`` is valid (means "no bib to copy")."""
    import importlib
    importlib.reload(postprocess)
    # Should not raise
    postprocess.validate_config({
        "source_dir": "..",
        "bibliography": None,
        "figures_dir": None,
        "tikz_overrides": None,
    })


def test_validate_config_accepts_full_example():
    """The dp1 and dp2 example configs must validate cleanly."""
    import importlib
    importlib.reload(postprocess)
    import yaml
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    for example in ('book-dp1', 'book-dp2'):
        path = project_root / 'examples' / example / 'config.yaml'
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        postprocess.validate_config(config)


# ── Equation regex safety (lesson #002 + the dp1 `$\Xsf$ $$` regression) ─────


def test_convert_equations_separates_inline_close_from_display_open():
    """The infamous `$\\Xsf$ $$` case: pandoc emits an inline-math close
    immediately followed by a display-math open on the same line.
    Without the [^\\n] fix to `convert_equations`, MyST swallows everything
    as inline math and the rest of the file gets blank-line-stripped."""
    text = (
        "Let $\\sigma$ be $g_k$-greedy. Then $$\\begin{equation*}\n"
        "    \\sigma(x) = 1\n"
        "\\end{equation*}$$ where things happen.\n"
    )
    out = postprocess.convert_equations(text)
    lines = out.split("\n")
    # The opening $$ should sit on its own line, separated from prose
    open_idx = next(i for i, l in enumerate(lines) if l.strip() == "$$" and i > 0)
    # The line above the opener should be blank (separator)
    assert lines[open_idx - 1] == ""


def test_convert_equations_label_after_body_in_equation_env():
    """GH #26 — the standard ``\\begin{equation} body \\label{eq:foo}
    \\end{equation}`` convention. The label must be extracted in the
    equation-env pass; if it leaks into the document body, the
    standalone-label cleanup regex can match it against a far-away
    ``$$math$$`` and swallow everything in between."""
    text = (
        "We use the mean squared error: $$\\begin{equation}\n"
        "    J(\\theta) = \\frac{1}{m}\\sum_i (h(x_i) - y_i)^2.\n"
        "    \\label{eq:mse}\n"
        "\\end{equation}$$ This loss is not arbitrary.\n"
    )
    out = postprocess.convert_equations(text)
    assert "$$ (eq-mse)" in out
    # \label must be consumed, not stranded in the body
    assert "\\label{eq:mse}" not in out


def test_convert_equations_standalone_label_does_not_cross_paragraphs():
    """GH #26 — an orphan ``\\label{}`` in a multi-line ``$$ … $$`` block
    must not pair with the nearest *prior* inline ``$$math$$`` from a
    paragraph far above. Before the fix, the catch-all regex used
    ``DOTALL`` with ``(.*?)`` and would happily span paragraphs, fusing
    figures and prose into the body of a single math block."""
    text = (
        "The regression formula is $$h(x) = \\theta_0 + \\theta_1 x.$$ "
        "It illustrates the simple linear case.\n"
        "\n"
        "```{figure} figures/regression.png\n"
        ":name: fig-regression\n"
        "\n"
        "Caption.\n"
        "```\n"
        "\n"
        "Unrelated prose between equations.\n"
        "\n"
        "Now the MSE:\n"
        "$$\n"
        "J(\\theta) = \\sum_i \\ell_i.\n"
        "\\label{eq:mse}\n"
        "$$\n"
        "Done.\n"
    )
    out = postprocess.convert_equations(text)
    # The inline display formula must remain inline (untouched).
    assert "$$h(x) = \\theta_0 + \\theta_1 x.$$" in out
    # The figure between the two equations must survive.
    assert "```{figure} figures/regression.png" in out
    assert "Unrelated prose between equations." in out


# ── Labels: colons → hyphens (universal rule) ────────────────────────────────


def test_convert_label_colons():
    assert postprocess.convert_label_colons("thm:main") == "thm-main"
    assert postprocess.convert_label_colons("eq:foo:bar") == "eq-foo-bar"
    assert postprocess.convert_label_colons("no-colon") == "no-colon"


# ── Nested subfigures (issue #17) ────────────────────────────────────────────


def test_nested_subfigures_with_embed_emits_both_images_outer_referenced():
    """GH #17 — dp2's ``ch_approx_learning`` shape: outer figure has a
    label that is cross-referenced via ``{numref}`` elsewhere in the
    chapter, so the outer label is donated to the first unlabeled
    inner subfigure (to keep the existing cross-ref working). The
    second subfigure auto-generates ``{outer}-b`` so it survives
    instead of being silently dropped by the old admonition path.
    """
    pandoc_out = (
        'See {numref}`f-foo` below.\n'
        '<figure id="f:foo">\n'
        '<figure>\n'
        '<embed src="figures/a.pdf" />\n'
        '<figcaption>First</figcaption>\n'
        '</figure>\n'
        '<figure>\n'
        '<embed src="figures/b.pdf" />\n'
        '<figcaption>Second</figcaption>\n'
        '</figure>\n'
        '<figcaption>Outer caption</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert 'figures/a.pdf' in out
    assert 'figures/b.pdf' in out, "second subfigure image was dropped"
    assert ':name: f-foo\n' in out, "outer label should transfer to first inner"
    assert ':name: f-foo-b\n' in out, "second inner should get auto-suffix"
    assert 'First' in out and 'Second' in out


def test_nested_subfigures_with_embed_unreferenced_outer_uses_suffixes():
    """When the outer label isn't cross-referenced anywhere, no
    consumer cares about preserving it, so both unlabeled inners get
    clean ``{outer}-a`` / ``{outer}-b`` auto-suffixes."""
    pandoc_out = (
        '<figure id="f:foo">\n'
        '<figure>\n'
        '<embed src="figures/a.pdf" />\n'
        '<figcaption>First</figcaption>\n'
        '</figure>\n'
        '<figure>\n'
        '<embed src="figures/b.pdf" />\n'
        '<figcaption>Second</figcaption>\n'
        '</figure>\n'
        '<figcaption>Outer caption</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert ':name: f-foo-a\n' in out
    assert ':name: f-foo-b\n' in out
    assert 'figures/a.pdf' in out and 'figures/b.pdf' in out


# ── Description lists (issue #19) ────────────────────────────────────────────


def _desc_markers(items: list[tuple[str, str]]) -> str:
    """Build the pandoc-escaped marker shape that ``convert_description_lists``
    receives — same form pandoc emits when the preprocess marker file is
    converted (``<`` → ``\\<``)."""
    parts = [r"\<!--DESCRIPTION-START--\>", ""]
    for term, body in items:
        b64 = base64.b64encode(term.encode("utf-8")).decode("ascii")
        parts.append(rf"\<!--DESCITEM term={b64}--\>")
        parts.append("")
        parts.append(body)
        parts.append("")
    parts.append(r"\<!--DESCRIPTION-END--\>")
    return "\n".join(parts) + "\n"


def test_convert_description_lists_basic_pair():
    src = _desc_markers([
        ("Hard constraints, encoded in the architecture.",
         "Some equations can be satisfied exactly."),
        ("Soft constraint, minimized in the loss.",
         "The only equilibrium condition."),
    ])
    out = postprocess.convert_description_lists(src)
    assert "Hard constraints, encoded in the architecture.\n: Some equations can be satisfied exactly." in out
    assert "Soft constraint, minimized in the loss.\n: The only equilibrium condition." in out
    # No marker residue left.
    assert "DESCITEM" not in out
    assert "DESCRIPTION-START" not in out
    assert "DESCRIPTION-END" not in out


def test_convert_description_lists_term_with_punctuation_round_trips():
    """Base64 encoding lets the term carry arbitrary characters
    (parentheses, math, em-dashes)."""
    src = _desc_markers([
        (r"Term with (parens), $x \in [0,1]$, and — punctuation.",
         "Body."),
    ])
    out = postprocess.convert_description_lists(src)
    assert r"Term with (parens), $x \in [0,1]$, and — punctuation." in out
    assert ": Body." in out


def test_convert_description_lists_no_term_emits_plain_paragraph():
    """``\\item`` without ``[…]`` produces an empty term — render as a
    plain paragraph (the LaTeX behaviour) rather than ``\\n: body``."""
    src = _desc_markers([("", "Bare item body.")])
    out = postprocess.convert_description_lists(src)
    assert "Bare item body." in out
    assert "\n: " not in out


def test_convert_description_lists_preserves_surrounding_prose():
    src = (
        "Before the list.\n\n"
        + _desc_markers([("T", "B")])
        + "\nAfter the list.\n"
    )
    out = postprocess.convert_description_lists(src)
    assert out.startswith("Before the list.")
    assert "After the list." in out
    assert "T\n: B" in out


# ── algpseudocode body parser (issue #20) ────────────────────────────────────


def _bullets(out: str) -> list[str]:
    return [ln.rstrip() for ln in out.split("\n") if ln.strip()]


def test_algpseudo_state_only_flat_bullets():
    body = r"\STATE Init $v$" "\n" r"\STATE Iterate"
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == ["- Init $v$", "- Iterate"]


def test_algpseudo_for_endfor_nests():
    body = (
        r"\FOR{$i = 1$ to $n$}" "\n"
        r"  \STATE work($i$)" "\n"
        r"\ENDFOR"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- for $i = 1$ to $n$:",
        "  - work($i$)",
    ]


def test_algpseudo_nested_for():
    body = (
        r"\FOR{$i$}" "\n"
        r"  \FOR{$j$}" "\n"
        r"    \STATE cell($i$, $j$)" "\n"
        r"  \ENDFOR" "\n"
        r"\ENDFOR"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- for $i$:",
        "  - for $j$:",
        "    - cell($i$, $j$)",
    ]


def test_algpseudo_while_endwhile():
    body = (
        r"\WHILE{$v > \epsilon$}" "\n"
        r"  \STATE step" "\n"
        r"\ENDWHILE"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        r"- while $v > \epsilon$:",
        "  - step",
    ]


def test_algpseudo_repeat_until_preserves_condition():
    """algorithm2e's \\Repeat is one-arg and drops the condition; the
    algpseudocode parser keeps it as a trailing ``until C`` bullet."""
    body = (
        r"\REPEAT" "\n"
        r"  \STATE noop" "\n"
        r"\UNTIL{converged}"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- repeat:",
        "  - noop",
        "- until converged",
    ]


def test_algpseudo_if_else_endif():
    body = (
        r"\IF{$x < 0$}" "\n"
        r"  \STATE neg" "\n"
        r"\ELSE" "\n"
        r"  \STATE pos" "\n"
        r"\ENDIF"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- if $x < 0$:",
        "  - neg",
        "- else:",
        "  - pos",
    ]


def test_algpseudo_if_elsif_else_chain():
    body = (
        r"\IF{$x < 0$}" "\n"
        r"  \STATE neg" "\n"
        r"\ELSIF{$x = 0$}" "\n"
        r"  \STATE zero" "\n"
        r"\ELSE" "\n"
        r"  \STATE pos" "\n"
        r"\ENDIF"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- if $x < 0$:",
        "  - neg",
        "- else if $x = 0$:",
        "  - zero",
        "- else:",
        "  - pos",
    ]


def test_algpseudo_require_ensure_return_kw_words():
    body = (
        r"\REQUIRE Initial $x_0$" "\n"
        r"\STATE Iterate" "\n"
        r"\ENSURE Converged $\bar x$" "\n"
        r"\RETURN $\bar x$"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- **Input:** Initial $x_0$",
        "- Iterate",
        r"- **Output:** Converged $\bar x$",
        r"- return $\bar x$",
    ]


def test_algpseudo_loop_endloop():
    """``\\LOOP``/``\\ENDLOOP`` has no algorithm2e equivalent — the
    native parser supports it directly."""
    body = (
        r"\LOOP" "\n"
        r"  \STATE forever" "\n"
        r"\ENDLOOP"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        "- loop:",
        "  - forever",
    ]


def test_algpseudo_strips_algorithmic_wrapper_if_present():
    """When dispatched from the algorithm2e path, the body still has
    ``\\begin{algorithmic}…\\end{algorithmic}`` around it — strip and
    proceed."""
    body = (
        r"\begin{algorithmic}" "\n"
        r"\STATE work" "\n"
        r"\end{algorithmic}"
    )
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == ["- work"]


def test_algpseudo_textbf_becomes_markdown_bold():
    body = r"\STATE \textbf{Input:} value"
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == ["- **Input:** value"]


def test_algpseudo_textbf_with_nested_braces_preserves_inner_math():
    """GH #21: \\textbf{} containing inline math with \\mathcal{Q} used
    to mangle into ``**[…$\\mathcal{Q**$ …]}`` because the naive
    ``[^}]*`` regex stopped at the first ``}``. Balanced-brace unwrap
    keeps the inner math intact."""
    body = r"\STATE Loss: \textbf{[NEW: $\mathcal{Q}$ is chosen]}"
    out = postprocess._algpseudo_convert_body(body)
    assert _bullets(out) == [
        r"- Loss: **[NEW: $\mathcal{Q}$ is chosen]**",
    ]


def test_algpseudo_textbf_with_multiple_nested_braced_macros():
    """Reporter's second case: ``\\texttt{}`` groups inside ``\\textbf{}``."""
    body = (
        r"\STATE Update: $x \leftarrow y$ "
        r"\textbf{[NEW: wrap in \texttt{@tf.function} or "
        r"\texttt{@jax.jit} for $5$ speed-up]}"
    )
    out = postprocess._algpseudo_convert_body(body)
    line = _bullets(out)[0]
    # Bold opens and closes exactly once around the bracketed note.
    assert line.count("**") == 2
    # Inner macros / math survive unbroken.
    assert r"\texttt{@tf.function}" in line
    assert r"\texttt{@jax.jit}" in line
    assert "$5$" in line


def test_algo2e_textbf_with_nested_braces_also_balanced():
    """Same fix applies to the algorithm2e body converter — it shared
    the same regex bug. The body lacks algpseudocode keywords, so
    ``_algo_convert_body`` stays on its native algorithm2e path."""
    body = r"\textbf{Step $\mathcal{A}$ matrix} \;"
    out = postprocess._algo_convert_body(body)
    assert r"**Step $\mathcal{A}$ matrix**" in out
    # No mid-math `**` insertion.
    assert r"$\mathcal{A**$" not in out


def test_algpseudo_comment_annotation_becomes_inline_note():
    body = r"\STATE work \Comment{annotation here}"
    out = postprocess._algpseudo_convert_body(body)
    assert "annotation here" in out
    assert "\\Comment" not in out


def test_algo_convert_body_dispatches_to_algpseudo_on_algorithmic_wrapper():
    """The algorithm-body converter must route algpseudocode bodies to
    ``_algpseudo_convert_body``. Without dispatch, the algorithm2e
    parser would leak ``\\STATE`` / ``\\FOR`` as literal text."""
    body = (
        r"\begin{algorithmic}" "\n"
        r"\STATE Step one" "\n"
        r"\FOR{$i$}" "\n"
        r"  \STATE inner" "\n"
        r"\ENDFOR" "\n"
        r"\end{algorithmic}"
    )
    out = postprocess._algo_convert_body(body)
    assert "\\STATE" not in out
    assert "\\FOR" not in out
    assert "- Step one" in out
    assert "- for $i$:" in out
    assert "  - inner" in out


# ── resolve_algorithmics end-to-end (issue #20) ──────────────────────────────


def _algic_marker(body: str) -> str:
    """Build the pandoc-escaped ALGORITHMIC marker shape that
    ``resolve_algorithmics`` receives."""
    b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
    return rf"\<!--ALGORITHMIC body={b64}--\>"


def test_resolve_algorithmics_basic():
    body = r"\STATE first" "\n" r"\STATE second"
    out = postprocess.resolve_algorithmics(f"Before.\n\n{_algic_marker(body)}\n\nAfter.\n")
    assert "ALGORITHMIC" not in out
    assert "- first" in out
    assert "- second" in out
    assert "Before." in out and "After." in out


def test_resolve_algorithmics_full_reporter_example():
    """End-to-end shape matching the GH #20 reporter's example
    (DL for DSGE ch02_deqns)."""
    body = (
        r"\small" "\n"
        r"\STATE \textbf{Input:} Initial state $x_0$" "\n"
        r"\FOR{episode $e = 1, \ldots, E$}" "\n"
        r"    \STATE \textbf{Simulate path:} ..." "\n"
        r"    \FOR{gradient step $t = 1, \ldots, T$}" "\n"
        r"        \STATE Compute loss" "\n"
        r"    \ENDFOR" "\n"
        r"\ENDFOR" "\n"
        r"\STATE \textbf{Output:} Trained network"
    )
    out = postprocess.resolve_algorithmics(_algic_marker(body))
    bullets = _bullets(out)
    assert bullets == [
        "- **Input:** Initial state $x_0$",
        r"- for episode $e = 1, \ldots, E$:",
        "  - **Simulate path:** ...",
        r"  - for gradient step $t = 1, \ldots, T$:",
        "    - Compute loss",
        "- **Output:** Trained network",
    ]


def test_nested_subfigures_without_embed_keeps_admonition_path():
    """When inner subfigures have no ``<embed>`` (e.g. ``\\input{tikz/…}``
    that pandoc couldn't include), keep the admonition placeholder so
    ``TIKZ_FIGURE_MAP`` can resolve labels later. The fix to #17 must
    not break this dp2 pattern."""
    pandoc_out = (
        '<figure id="f:bar">\n'
        '<figure id="f:bar_a">\n'
        '<figcaption>A</figcaption>\n'
        '</figure>\n'
        '<figure id="f:bar_b">\n'
        '<figcaption>B</figcaption>\n'
        '</figure>\n'
        '<figcaption>Outer</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert '{admonition} Figure (TikZ' in out
    assert 'f-bar_a' in out and 'f-bar_b' in out
