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


# ── Labels: colons → hyphens (universal rule) ────────────────────────────────


def test_convert_label_colons():
    assert postprocess.convert_label_colons("thm:main") == "thm-main"
    assert postprocess.convert_label_colons("eq:foo:bar") == "eq-foo-bar"
    assert postprocess.convert_label_colons("no-colon") == "no-colon"
