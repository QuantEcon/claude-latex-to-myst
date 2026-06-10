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


# ── Exercise markers (#69) ───────────────────────────────────────────────────


def test_resolve_exercise_markers_emits_exercise_directive():
    """GH #69 — ``<!--EXERCISE-START label=X-->`` / ``<!--EXERCISE-END-->``
    marker pair decodes to a MyST ``{exercise}`` directive carrying
    the original label, with the markdown content as the body."""
    src = (
        "Before.\n\n"
        "<!--EXERCISE-START label=ex-ch1-1-->\n"
        "**[Core] Backprop.** Derive the gradient.\n"
        "<!--EXERCISE-END-->\n\n"
        "After.\n"
    )
    out = postprocess.resolve_exercise_markers(src)
    assert "```{exercise}" in out
    assert ":label: ex-ch1-1" in out
    assert "**[Core] Backprop.** Derive the gradient." in out
    # Markers are gone — no leakage into the body.
    assert "EXERCISE-START" not in out
    assert "EXERCISE-END" not in out


def test_resolve_exercise_markers_tolerates_pandoc_escaped_brackets():
    """Pandoc may escape ``<`` and ``>`` in HTML comments as ``\\<``
    and ``\\>`` when round-tripping through markdown. The resolver
    regex must accept both forms (mirrors the ``resolve_listings``
    pattern)."""
    src = (
        r"\<!--EXERCISE-START label=ex-a--\> "
        "body content "
        r"\<!--EXERCISE-END--\>"
    )
    out = postprocess.resolve_exercise_markers(src)
    assert "```{exercise}" in out
    assert ":label: ex-a" in out
    assert "body content" in out


def test_resolve_exercise_markers_handles_multiple_pairs():
    """A series of marker pairs (the common case — every exercise
    in a chapter) each decodes independently into its own directive."""
    src = (
        "<!--EXERCISE-START label=ex-1-->\n"
        "first body\n"
        "<!--EXERCISE-END-->\n\n"
        "<!--EXERCISE-START label=ex-2-->\n"
        "second body\n"
        "<!--EXERCISE-END-->\n"
    )
    out = postprocess.resolve_exercise_markers(src)
    assert out.count("```{exercise}") == 2
    assert ":label: ex-1" in out
    assert ":label: ex-2" in out


def test_resolve_exercise_markers_widens_fence_around_nested_code_block():
    """An exercise whose body contains a ```` ```python ```` code fence
    must be wrapped in a *four*-backtick directive fence — the lecture
    source convention — so the inner ``` doesn't close the directive
    early (CommonMark fence-nesting rule)."""
    src = (
        "<!--EXERCISE-START label=ex-code-->\n"
        "Implement the loss:\n"
        "\n"
        "```python\n"
        "def loss(y, yhat):\n"
        "    return ((y - yhat) ** 2).mean()\n"
        "```\n"
        "<!--EXERCISE-END-->\n"
    )
    out = postprocess.resolve_exercise_markers(src)
    # Outer directive opens and closes with four backticks.
    assert "````{exercise}" in out
    assert out.rstrip().endswith("````")
    # The inner three-backtick block survives intact inside the body.
    assert "```python" in out
    assert ":label: ex-code" in out
    # No marker leakage.
    assert "EXERCISE-START" not in out and "EXERCISE-END" not in out


def test_resolve_exercise_markers_idempotent_no_markers():
    """No markers in the input → no-op."""
    src = "Just some markdown with no markers.\n"
    assert postprocess.resolve_exercise_markers(src) == src


def test_outer_fence_helper_sizes_to_deepest_inner_fence():
    """Shared helper (issue #79): pick a fence one tick longer than the
    deepest backtick fence in the content, minimum three. Tildes and
    inline single backticks don't count — they can't close a backtick
    fence (lesson 040)."""
    from transforms._helpers import outer_fence
    assert outer_fence("plain prose, no fence") == "```"
    assert outer_fence("use `inline` code") == "```"
    assert outer_fence("a\n```python\nx\n```\nb") == "````"
    assert outer_fence("a\n````\n```py\nx\n```\n````") == "`````"
    # A tilde fence inside is irrelevant to a backtick wrapper.
    assert outer_fence("a\n~~~\nx\n~~~\nb") == "```"


def test_complete_image_path_extensionless_include():
    """#104: an extensionless include resolves via the figure_ext_map; paths
    with an extension or no map hit keep the prior behaviour."""
    from transforms._helpers import complete_image_path
    m = {"restud_fig11a": "restud_fig11a.png", "du": "du.svg"}
    # Extensionless + dir prefix → remap to figures/ + resolved file.
    assert complete_image_path("fig/restud_fig11a", m) == "figures/restud_fig11a.png"
    assert complete_image_path("restud_fig11a", m) == "figures/restud_fig11a.png"
    assert complete_image_path("fig/du", m) == "figures/du.svg"
    # No map hit → unchanged (genuinely missing file; no regression).
    assert complete_image_path("fig/unknown", m) == "fig/unknown"
    # Already has an extension → prior behaviour (dir-prefixed stays, bare
    # gets figures/).
    assert complete_image_path("fig/foo.png", m) == "fig/foo.png"
    assert complete_image_path("foo.png", m) == "figures/foo.png"
    # No map at all → prior behaviour only.
    assert complete_image_path("bar", None) == "figures/bar"


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


# ── lstlisting → {code-block} via pandoc attribute fences (closes #31) ───────


def test_pandoc_attr_code_block_label_becomes_name():
    """Pandoc emits ``\\begin{lstlisting}[label=lst:X]`` as a fenced
    code block whose info string is a pandoc attribute block
    ``{#lst:X .python ...}``. MyST silently drops the attributes
    (renders as anchorless plain code), so ``\\ref{lst:X}`` elsewhere
    fails to resolve. Convert to a ``{code-block}`` directive."""
    src = (
        '``` {#lst:demo .python caption="Demo caption" '
        'label="lst:demo" language="Python"}\n'
        'x = 1\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert '```{code-block} python' in out
    assert ':name: lst-demo' in out
    assert ':caption: Demo caption' in out
    assert 'x = 1' in out
    # The pandoc-attr block must not survive.
    assert '#lst:demo' not in out
    assert 'language="Python"' not in out


def test_pandoc_attr_code_block_label_only_no_caption():
    """Label without caption is the bare cross-ref case — emit name,
    no :caption: line."""
    src = (
        '``` {#lst:demo .python}\n'
        'x = 1\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert '```{code-block} python' in out
    assert ':name: lst-demo' in out
    assert ':caption:' not in out


def test_pandoc_attr_code_block_lang_only_strips_attrs():
    """No ``#id`` and no ``caption=`` → no semantic attrs to preserve.
    Strip the pandoc-attr block; emit a plain fenced code block. The
    info string would otherwise render as broken in MyST."""
    src = (
        '``` {.python language="Python"}\n'
        'x = 1\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert '```python\n' in out
    assert '{code-block}' not in out
    assert 'language=' not in out


def test_pandoc_attr_code_block_label_with_colon_chain():
    """``label=lst:foo:bar`` should map to ``lst-foo-bar`` via the
    standard colon→hyphen rule."""
    src = (
        '``` {#lst:foo:bar .julia caption="Multi colon" language="Julia"}\n'
        'println("hi")\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert ':name: lst-foo-bar' in out


def test_pandoc_attr_code_block_does_not_touch_myst_directive_fence():
    """A genuine MyST directive fence (``\\`\\`\\`{code-block} python``)
    must not be re-processed by this pass — MyST directives have no
    space between the backticks and the brace, and the brace content
    is a directive name, not pandoc attributes."""
    src = (
        '```{code-block} python\n'
        ':name: list-demo\n'
        '\n'
        'x = 1\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    # Idempotent: unchanged.
    assert out == src


def test_pandoc_attr_code_block_idempotent():
    """Re-running on already-converted output must be a no-op."""
    src = (
        '``` {#lst:demo .python caption="Demo" label="lst:demo"}\n'
        'x = 1\n'
        '```\n'
    )
    once = postprocess.convert_pandoc_attr_code_blocks(src)
    twice = postprocess.convert_pandoc_attr_code_blocks(once)
    assert once == twice


def test_pandoc_attr_code_block_caption_with_braces_in_value():
    """GH #35 — LaTeX captions with ``\\texttt{X}``, ``\\textbf{X}``,
    math fragments etc. embed literal ``}`` inside the quoted
    ``caption="..."`` value. The original attribute group
    ``[^}\\n]+`` terminated at the first ``}``, so the block was
    skipped and the pandoc-attr fence survived into MyST unconverted
    (anchorless code, ``\\ref{lst:X}`` broken).

    Note: pandoc serialises ``\\`` inside a quoted attribute value as
    ``\\\\`` — the source fixture mirrors what pandoc actually emits,
    and the assertions check that the caption decodes back to the
    original single-backslash LaTeX shape (#71)."""
    src = (
        '``` {#lst:demo caption="Autodiff Euler for \\\\texttt{Pi}; see '
        '\\\\texttt{02_Brock.ipynb}." label="lst:demo" language="Python"}\n'
        'def loss(): pass\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert '```{code-block} python' in out
    assert ':name: lst-demo' in out
    # Caption decodes from pandoc's ``\\\\`` escape back to ``\\`` —
    # the form MyST + KaTeX expect.
    assert 'Autodiff Euler for \\texttt{Pi}' in out
    assert '\\texttt{02_Brock.ipynb}' in out
    # The pre-decoded doubled-backslash form must NOT survive.
    assert '\\\\texttt' not in out


def test_pandoc_attr_code_block_multiple_braced_macros_in_caption():
    """Regression guard: more than one brace-bearing macro in the
    same caption still parses correctly. Mirrors the doubled-backslash
    shape pandoc emits for ``\\`` inside the quoted attribute value (#71)."""
    src = (
        '``` {#lst:demo caption="Use \\\\texttt{a}, \\\\textbf{b}, '
        'and $\\\\mathbb{R}$." label="lst:demo"}\n'
        'x = 1\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert ':name: lst-demo' in out
    assert '\\texttt{a}' in out
    assert '\\textbf{b}' in out
    assert '$\\mathbb{R}$' in out
    assert '\\\\texttt' not in out


def test_pandoc_attr_code_block_caption_with_inline_math_decodes_escapes():
    """GH #71 — pandoc serialises ``\\`` inside a quoted attribute
    value as ``\\\\``. Pre-fix the resolver stripped the outer quotes
    but didn't decode the doubled backslash, so inline math in
    lstlisting captions arrived in MyST as ``$s \\\\in (0,1)$``, which
    KaTeX rendered as "function with no arguments" errors. The fix
    decodes pandoc's ``\\X`` → ``X`` escape so math commands survive
    with single backslashes — the form KaTeX expects.

    Surfaced converting book-dp-deep-learning's ch02_deqns lstlisting
    captioned ``Representative DEQN loss … savings share $s \\in (0,1)$
    via a sigmoid …``."""
    src = (
        '``` {.python caption="Loss for $s \\\\in (0,1)$ via '
        '\\\\emph{sigmoid}; \\\\(C > z K^\\\\alpha\\\\)."}\n'
        'def loss(): pass\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    # Single-backslash math commands — the KaTeX-friendly form.
    assert '$s \\in (0,1)$' in out
    assert '\\emph{sigmoid}' in out
    assert '\\(C > z K^\\alpha\\)' in out
    # Doubled-backslash form must NOT survive into the caption.
    assert '\\\\in' not in out
    assert '\\\\emph' not in out
    assert '\\\\alpha' not in out


def test_pandoc_attr_code_block_caption_decodes_quoted_quote_escape():
    """Pandoc serialises ``"`` inside a quoted attribute value as ``\\"``.
    The decoder must round-trip that too — defensive guard against the
    same class of double-escape bug surfacing for embedded quotes (#71)."""
    src = (
        '``` {.python caption="Run \\"foo\\" then \\"bar\\"."}\n'
        'x = 1\n'
        '```\n'
    )
    out = postprocess.convert_pandoc_attr_code_blocks(src)
    assert ':caption: Run "foo" then "bar".' in out


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


def test_strip_doubled_noun_refs_figure_numref():
    """`Figure~\\ref{f:x}` → `Figure {numref}`f-x`` renders 'Figure Figure
    N' because numref auto-renders 'Figure N'; strip the prose noun (#110)."""
    text = "See Figure {numref}`f-state_action_reward` for details."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "See {numref}`f-state_action_reward` for details."


def test_strip_doubled_noun_refs_figures_plural_fig_prefix():
    text = "Figures {numref}`fig-a` and {numref}`fig-b` show this."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{numref}`fig-a` and {numref}`fig-b` show this."


def test_strip_doubled_noun_refs_appendix_section_symbol():
    """`Appendix~\\S\\ref{c:areal}` → `Appendix §{prf:ref}`c-areal``; both the
    prose 'Appendix' and the stray § are redundant once the role auto-renders
    'Appendix A' (#110)."""
    text = "As shown in Appendix §{prf:ref}`c-areal` we have results."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "As shown in {prf:ref}`c-areal` we have results."


def test_strip_doubled_noun_refs_figure_with_nbsp_and_section_symbol():
    text = "Figure\xa0§{numref}`f-x` is key."
    out = postprocess.strip_doubled_noun_refs(text)
    assert out == "{numref}`f-x` is key."


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


def test_cross_ref_routing_default_unchanged_when_no_config():
    """Regression guard: an empty/no config preserves the default
    routing table (every existing book continues to work)."""
    postprocess.apply_config({"source_dir": "."})
    # Defaults: eq → {eq}, fig → {numref}, sec → {ref}, thm → {prf:ref}.
    out = postprocess.convert_cross_references(
        '[X](#eq:foo){reference-type="ref" reference="eq:foo"} '
        '[Y](#fig:bar){reference-type="ref" reference="fig:bar"} '
        '[Z](#sec:baz){reference-type="ref" reference="sec:baz"} '
        '[W](#thm:qux){reference-type="ref" reference="thm:qux"}'
    )
    assert '{eq}`eq-foo`' in out
    assert '{numref}`fig-bar`' in out
    assert '{ref}`sec-baz`' in out
    assert '{prf:ref}`thm-qux`' in out
    postprocess._EXTRA_CROSS_REF_ROUTING = []


def test_cross_ref_routing_string_prefix_expands_to_both_forms():
    """``prefix: "lst"`` should match both ``lst:foo`` (raw label) and
    ``lst-foo`` (post-colon-to-hyphen). The string form is the
    book-friendly shorthand for the common case."""
    postprocess.apply_config({
        "source_dir": ".",
        "cross_ref_routing": [
            {"prefix": "lst", "role": "numref"},
        ],
    })
    out = postprocess.convert_cross_references(
        '[X](#lst:demo){reference-type="ref" reference="lst:demo"}'
    )
    assert '{numref}`lst-demo`' in out
    postprocess._EXTRA_CROSS_REF_ROUTING = []


def test_cross_ref_routing_explicit_prefix_list():
    """A list of prefixes lets a book route multiple distinct prefixes
    to the same role without repeating themselves."""
    postprocess.apply_config({
        "source_dir": ".",
        "cross_ref_routing": [
            {"prefix": ["prog-", "snippet-"], "role": "numref"},
        ],
    })
    out = postprocess.convert_cross_references(
        '[X](#prog-foo){reference-type="ref" reference="prog-foo"} '
        '[Y](#snippet-bar){reference-type="ref" reference="snippet-bar"}'
    )
    assert '{numref}`prog-foo`' in out
    assert '{numref}`snippet-bar`' in out
    postprocess._EXTRA_CROSS_REF_ROUTING = []


def test_cross_ref_routing_extras_take_precedence_over_defaults():
    """Per-book entry can override a default. ``eq:`` defaults to
    ``{eq}``; a book that wants ``{numref}`` for equations gets it."""
    postprocess.apply_config({
        "source_dir": ".",
        "cross_ref_routing": [
            {"prefix": "eq", "role": "numref"},
        ],
    })
    out = postprocess.convert_cross_references(
        '[X](#eq:foo){reference-type="ref" reference="eq:foo"}'
    )
    assert '{numref}`eq-foo`' in out
    postprocess._EXTRA_CROSS_REF_ROUTING = []


def test_cross_ref_routing_validation_rejects_missing_role():
    """Bad config: entry without role key."""
    with pytest.raises(SystemExit, match="requires 'prefix' and 'role'"):
        postprocess.apply_config({
            "source_dir": ".",
            "cross_ref_routing": [{"prefix": "lst"}],
        })


def test_doubled_noun_refs_default_unchanged_when_no_config():
    """Regression guard: empty config preserves default doubled-noun
    strips (Theorem, Lemma, Listing, …)."""
    postprocess.apply_config({"source_dir": "."})
    out = postprocess.strip_doubled_noun_refs(
        "Theorem {prf:ref}`t-main` proves it."
    )
    assert out == "{prf:ref}`t-main` proves it."
    postprocess._EXTRA_DOUBLED_NOUN_REFS = []


def test_doubled_noun_refs_config_extension():
    """Books with custom theorem-class nouns ("Claim", "Conjecture")
    extend the strip list via config."""
    postprocess.apply_config({
        "source_dir": ".",
        "doubled_noun_refs": [
            {"noun": "Claim",      "prefix": "claim-"},
            {"noun": "Conjecture", "prefix": "conj-"},
        ],
    })
    out = postprocess.strip_doubled_noun_refs(
        "Claim {prf:ref}`claim-foo` and Conjecture {prf:ref}`conj-bar`."
    )
    assert out == "{prf:ref}`claim-foo` and {prf:ref}`conj-bar`."
    # Defaults still apply.
    out2 = postprocess.strip_doubled_noun_refs(
        "Theorem {prf:ref}`t-main`."
    )
    assert out2 == "{prf:ref}`t-main`."
    postprocess._EXTRA_DOUBLED_NOUN_REFS = []


def test_doubled_noun_refs_validation_rejects_missing_prefix():
    """Bad config: entry without prefix key."""
    with pytest.raises(SystemExit, match="string 'noun' and 'prefix'"):
        postprocess.apply_config({
            "source_dir": ".",
            "doubled_noun_refs": [{"noun": "Claim"}],
        })


def test_regen_flag_validated_as_bool():
    """``regen`` must be a boolean when present — anything else is a typo
    waiting to silently bypass the gate (#63)."""
    with pytest.raises(SystemExit, match=r"regen must be a boolean"):
        postprocess.apply_config({
            "source_dir": ".",
            "extra_files": [
                {"stem": "preface", "regen": "false"},  # str, not bool
            ],
        })


def test_regen_flag_accepts_bool():
    """``regen: false`` (bool) is the only accepted form; missing field
    is also fine (defaults to regen-enabled)."""
    postprocess.apply_config({
        "source_dir": ".",
        "extra_files": [
            {"stem": "preface"},  # missing → default regen
            {"stem": "common_symbols", "regen": False},
            {"stem": "glossary", "regen": True},
        ],
    })


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


# ── colon-bearing bib keys in textual @key form (closes #32) ─────────────────


@pytest.mark.parametrize("key", [
    "Bertsekas:2000:DPO:517430",
    "Rasmussen:2005:GPM:1162254",
    "Bilionis:2016wc",
    "ECTA:ECTA1716",
    "marcet_marshall:94",
])
def test_citation_textual_colon_bearing_keys(key):
    """JabRef/Mendeley/ACM-style bib keys contain ``:`` — the textual
    ``@key`` form must capture the whole key, not truncate at the first
    colon."""
    src = f"See @{key} for details."
    out = postprocess.convert_citations(src)
    assert f"{{cite:t}}`{key}`" in out
    # The suffix must not leak as literal text.
    assert ":" not in out.split(f"`{key}`", 1)[1].split(" ", 1)[0]


def test_citation_textual_colon_key_at_end_of_sentence():
    """Trailing period after a colon-bearing key is sentence punctuation,
    not part of the key."""
    src = "Per @Bertsekas:2000:DPO:517430."
    out = postprocess.convert_citations(src)
    assert "{cite:t}`Bertsekas:2000:DPO:517430`." in out


def test_citation_textual_plain_key_trailing_period_unchanged():
    """Regression guard: plain key followed by a period still captures
    just the key — the period stays as sentence punctuation."""
    src = "See @Smith2020. Next sentence."
    out = postprocess.convert_citations(src)
    assert "{cite:t}`Smith2020`. Next sentence." in out


@pytest.mark.parametrize("prose,key,after", [
    # Plain key + comma (regression baseline).
    ("In the spirit of @key2019, ...", "key2019", ", ..."),
    # Plain key + trailing colon in prose — the #36 regression case.
    ("See @key2019: it explains.", "key2019", ": it explains."),
    # Plain key + sentence-ending period.
    ("See @key2019. Next.", "key2019", ". Next."),
    # Colon-bearing key + trailing colon in prose (the ECTA case from #36).
    ("Per @ECTA:ECTA1716: see.", "ECTA:ECTA1716", ": see."),
    # Colon-bearing key + space (no trailing punctuation issue).
    ("Per @author:2020:tag and.", "author:2020:tag", " and."),
    # Colon-bearing key + sentence end (#32 baseline).
    ("Per @Bertsekas:2000:DPO:517430.", "Bertsekas:2000:DPO:517430", "."),
])
def test_citation_textual_key_boundary(prose, key, after):
    """GH #36 — a trailing ``:`` immediately after the key belongs to
    prose, not to the key. The #32 widening accidentally pulled it
    into the capture (9 broken sites in the Deep-Learning book).
    Parametrized over both colon-bearing and plain keys to lock the
    boundary behaviour."""
    out = postprocess.convert_citations(prose)
    assert f"{{cite:t}}`{key}`{after}" in out


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


def test_simple_table_no_caption_emits_bare_list_table():
    """Un-captioned tables continue to emit a bare ``{list-table}`` —
    no ``{table}`` wrapper. Keeps the 2-col and N-col tests that
    pre-date the wrapper fix stable on shape."""
    body = (
        "  ----  ----\n"
        "  a     b\n"
        "  ----  ----\n"
        "  1     2\n"
        "  ----  ----\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert "{table}" not in out
    assert "````" not in out


def test_simple_table_captioned_zero_header_suppresses_inner_enumeration():
    """Issue #52: a captioned 0-header simple table keeps the ``{table}``
    wrapper (role-safe caption-as-paragraph) but the nested
    ``{list-table}`` carries ``:enumerated: false`` so it doesn't claim a
    phantom table number that drifts every later ``{numref}``."""
    body = (
        "::: {#tab:zero}\n"
        + _table(r"$\alpha$ | the first letter",
                 r"$\beta$  | the second letter")
        + "\n  : Greek letters.\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "````{table}" in out
    assert ":name: tab-zero" in out
    assert "Greek letters." in out               # caption-as-paragraph
    assert "```{list-table}" in out
    assert ":header-rows: 0" in out
    assert ":enumerated: false" in out


def test_simple_table_caption_with_inline_role_backticks():
    """Regression for PR #41 v6: captions containing inline-role
    backticks (``{ref}`foo``, ``{cite:t}`bar``) silently broke when
    placed on the directive argument — MyST's argument parser
    mistakes the role's backticks for inline-code-span delimiters,
    the directive fails to parse, and the ``{table}`` collapses to a
    plain paragraph in the AST.

    All 8 silently-failing captioned tables in the Deep-Learning
    book had ≥2 backticks in their captions. The v7 fix moves the
    caption into the directive body as a regular markdown paragraph,
    where inline roles parse normally.
    """
    body = (
        "::: {#tab:demo}\n"
        "  ---- ----\n"
        "  H1   H2\n"
        "  ---- ----\n"
        "  a    b\n"
        "  ---- ----\n"
        "\n"
        "  : Lineage uses {cite:t}`smith2023` and Chapter {ref}`ch-foo`"
        " for context.\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    # The {table} opener line must NOT contain backticks (the bug
    # shape that broke MyST's argument parser).
    table_open_line = next(
        line for line in out.split('\n') if line.startswith('````{table}')
    )
    assert '`' not in table_open_line[len('````{table}'):], (
        f'{{table}} opener must not carry inline-role backticks: '
        f'{table_open_line!r}'
    )
    # The caption text — including the inline roles — survives in the
    # body as a markdown paragraph.
    assert '{cite:t}`smith2023`' in out
    assert '{ref}`ch-foo`' in out
    # :name: is on the wrapper from the enclosing ::: {#tab:demo}.
    assert ':name: tab-demo' in out


def test_simple_table_long_math_caption_in_body():
    """Regression for PR #41 v6: long mixed-math captions (~400+
    chars with multiple ``$math$`` runs) on the directive argument
    line tripped MyST's parser even after the v5 ``{table}`` wrapper
    landed — the docutils body validator fired "list-table directive
    must have a list of lists" because the long argument apparently
    bled into the body. Move the caption into the body as a
    paragraph; the argument stays empty.

    Canonical reproducer: Deep-Learning book ``tab-curse_of_dim``,
    429-char caption with 10 inline ``$math$`` runs."""
    body = (
        "::: {#tab:curse_of_dim}\n"
        "  ---- ---------------------- ---------\n"
        "  $d$   Grid points $(10^d)$   Memory\n"
        "  ---- ---------------------- ---------\n"
        "  1    $10^1$                 80 B\n"
        "  ---- ---------------------- ---------\n"
        "\n"
        "  : Size of an $n = 10$ Cartesian grid and the 64-bit memory"
        " required to store one floating-point value per grid point,"
        " as a function of state-space dimension $d$. Grid-based"
        " methods are comfortable only at low dimension; by $d = 10$"
        " even storing one scalar per grid point is borderline.\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Empty argument on the directive opener.
    assert "````{table}\n" in out
    # Caption text including all math runs survives in the body.
    assert "Size of an $n = 10$ Cartesian grid" in out
    assert "by $d = 10$ even storing" in out
    # :name: propagated from the enclosing fence.
    assert ":name: tab-curse_of_dim" in out


def test_simple_table_caption_with_inline_math_and_refs_wraps():
    """Regression for PR #41 v4: a long caption containing inline
    ``$math$`` (and potentially inline directives like ``{ref}`X```)
    on the ``{list-table}`` argument line broke MyST's body parser,
    producing the ``list-table directive must have a list of lists``
    error. The ``{table}`` wrapper sidesteps the cascade — caption
    lives on the wrapper's argument; inner ``{list-table}`` carries
    only ``:header-rows:`` and rows.

    The Deep-Learning book's ``ch02_deqns:19`` curse-of-dimensionality
    table is the canonical reproducer: ~390-char caption with
    multiple inline ``$math$`` runs."""
    body = (
        "  ---- ---------------------- ---------\n"
        "  $d$   Grid points $(10^d)$   Memory\n"
        "  ---- ---------------------- ---------\n"
        "  1    $10^1$                 80 B\n"
        "  5    $10^5$                 800 kB\n"
        "  ---- ---------------------- ---------\n"
        "\n"
        "  : Size of an $n = 10$ Cartesian grid and the 64-bit memory"
        " required to store one floating-point value per grid point,"
        " as a function of state-space dimension $d$. Grid-based"
        " methods are comfortable only at low dimension; by $d = 10$"
        " even storing one scalar per grid point is borderline.\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Outer: {table} wrapper at 4-backtick fence with EMPTY argument;
    # caption lives as the first paragraph of the body.
    assert "````{table}\n" in out
    # Caption text appears in the body — survives in full including
    # trailing clauses with additional $math$ runs.
    assert "Size of an $n = 10$ Cartesian grid" in out
    assert "by $d = 10$" in out
    # Caption did NOT land on the {table} opener line.
    assert "````{table} Size" not in out
    # Inner: pipe-table (NOT a nested {list-table} directive — see
    # R2 fix in PR #41 v8: nested directives consumed a phantom
    # enumerator slot).
    assert "```{list-table}" not in out
    assert "| $d$ | Grid points $(10^d)$ | Memory |" in out
    # Alignment row immediately follows the header.
    assert "|---|---|---|" in out
    # Body rows present.
    assert "| 1 | $10^1$ | 80 B |" in out
    assert "| 5 | $10^5$ | 800 kB |" in out


def test_simple_table_inside_id_fence_emits_explicit_name():
    """Mode B fix for PR #41 silent failures: when a table is wrapped
    in ``::: {#tab:foo}`` (pandoc's emit for ``\\begin{table}\\label{tab:foo}``),
    extract the id and emit ``:name: tab-foo`` on the directive
    directly. This ensures the table AST node carries the identifier
    even when MyST's standalone-anchor attachment misfires through
    the 4-backtick ``{table}`` wrapper.

    Without this fix, the cross-reference resolver falls back to
    "next non-table node with this label" and ``{numref}`tab-foo``
    resolves to a paragraph instead of a table (confirmed in the
    Deep-Learning book's ``tab-relobralo_hp`` case)."""
    body = (
        "::: {#tab:nas_methods}\n"
        "  ---- ----\n"
        "  H1   H2\n"
        "  ---- ----\n"
        "  a    b\n"
        "  ---- ----\n"
        "\n"
        "  : Caption text.\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    # When :name: is emitted, the wrapping ``::: {#tab:nas_methods}``
    # opener and matching ``:::`` closer are SUPPRESSED so
    # convert_environment_divs doesn't emit a competing
    # ``(tab-nas_methods)=`` standalone anchor (R1 in PR #41).
    # ``:name:`` is the single source of truth for the label.
    assert "````{table}\n" in out
    assert ":name: tab-nas_methods" in out
    assert "Caption text." in out
    # Body is a pipe-table, not a nested {list-table} (R2 fix —
    # phantom-enumerator).
    assert "```{list-table}" not in out
    assert "| H1 | H2 |" in out
    assert "| a | b |" in out
    # Fence opener and closer are suppressed.
    assert "::: {#tab:nas_methods}" not in out
    assert ":::" not in out


def test_simple_table_inside_id_fence_no_caption_uses_list_table_name():
    """Mode B for un-captioned tables: ``:name:`` lands on the bare
    ``{list-table}`` directly (no ``{table}`` wrapper, since no
    caption)."""
    body = (
        "::: {#tab:simple}\n"
        "  ---- ----\n"
        "  H1   H2\n"
        "  ---- ----\n"
        "  a    b\n"
        "  ---- ----\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":name: tab-simple" in out
    # No wrapper for the un-captioned case.
    assert "{table}" not in out


def test_simple_table_no_enclosing_fence_no_name_emitted():
    """Regression guard: bare tables (no enclosing ``::: {#id}`` fence)
    don't get a spurious ``:name:`` from leftover stack state. The
    div-id stack is reset per-table-iteration; this test pins that
    contract."""
    body = (
        "::: {#tab:first}\n"
        "  ---- ----\n"
        "  a    b\n"
        "  ---- ----\n"
        ":::\n"
        "\n"
        "Plain prose.\n"
        "\n"
        "  ---- ----\n"
        "  c    d\n"
        "  ---- ----\n"
    )
    out = postprocess.convert_simple_tables(body)
    # First table inside #tab:first → has :name:
    assert ":name: tab-first" in out
    # Second table is bare — no :name: should be emitted.
    # Count :name: occurrences to confirm only one.
    assert out.count(":name:") == 1


def test_simple_table_shape_b_wide_indent_header_accepted():
    """Mode A fix for PR #41 silent failures: pandoc aligns header
    text by data-column position, not by leading-whitespace count.
    Wide tables emit headers at indent 26+ over a rule at indent 2 —
    v5's upper-bound check rejected these, breaking ``tab-seq_compare``
    and similar.

    With the v6 indent-relaxation, ``_collect_header_above`` accepts
    any non-blank line at indent >= opener_indent (no upper bound)."""
    # Synthesised after Deep-Learning ``ch01_intro.md:838``: header at
    # wide indent, dash-rule at indent 2, body rows at indent 2,
    # fewer header cells than rule columns (the first column has no
    # header — it's the row-label column).
    body = (
        "::: {#tab:seq_compare}\n"
        "                          **RNN**            **LSTM**           **Transformer**\n"
        "  ----------------------- ------------------ ------------------ ------------------------\n"
        "  Hidden state            single $\\h_t$      $\\h_t$ and $C_t$   none per step\n"
        "  Path length             $\\mathcal{O}(T)$   $\\mathcal{O}(T)$   $\\mathcal{O}(1)$\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Header is absorbed into the directive — should appear as the
    # first row inside the list-table, NOT as raw text outside.
    assert "```{list-table}" in out
    assert ":header-rows: 1" in out
    # Bold header tokens survived and landed in the bullet rows.
    assert "**RNN**" in out
    assert "**LSTM**" in out
    assert "**Transformer**" in out
    # The original wide-indent header line should NOT appear in the
    # output (it was absorbed into the directive). Check the actual
    # `**RNN**` line is rendered as a list-table cell, not as a raw
    # leading paragraph.
    lines = out.split('\n')
    # Find where the directive starts and ends.
    list_table_start = next(j for j, l in enumerate(lines) if '```{list-table}' in l)
    # Everything before list-table opener should be the ::: opener and blank.
    before = '\n'.join(lines[:list_table_start])
    # The bold header tokens must NOT appear before the directive opens.
    assert "**RNN**" not in before


def test_simple_table_caption_pipe_table_escapes_literal_pipe():
    """Cells containing literal ``|`` (e.g. ``OR``-pipe in code, or
    ``|x|`` absolute-value notation in math) must be escaped to ``\\|``
    so the pipe-table parser doesn't treat them as column separators.

    Conservative guarantee: every ``|`` inside a cell becomes ``\\|``,
    even inside ``$math$`` regions. None of the corpus we've audited
    (Deep-Learning book, book-dp1, book-dp2) has ``|`` inside table-cell
    math today, so the over-escape is defensive rather than load-bearing.
    """
    body = (
        "  ---- -------\n"
        "  Op   Result\n"
        "  ---- -------\n"
        "  AND  a | b\n"
        "  ABS  $|x|$\n"
        "  ---- -------\n"
        "\n"
        "  : Operator legend.\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Every literal pipe inside the cells is escaped.
    assert r"a \| b" in out
    assert r"$\|x\|$" in out
    # The pipe-table structure is otherwise intact.
    assert "| Op | Result |" in out
    assert "|---|---|" in out


def test_simple_table_pandoc_no_borders_broad_rules():
    """Regression for PR #41 v7's ``tab-bm_vs_irbc`` Mode A failure.
    Pandoc's ``\\toprule`` / ``\\bottomrule`` emit (no per-column
    rules on top/bottom) puts a SINGLE long dash-group above the
    header and below the body. These broad rules don't match the
    multi-group ``_RULE_RE`` so they're invisible to ``_rule_columns``
    — but they DO bound the table region and must not bleed into
    parsed cells.

    Pre-fix: ``_collect_header_above`` walked past the top broad
    rule into it (treating it as another header line); multiline
    parsing then joined the dashes with the header text, producing
    cells like ``------ **Brock-Mirman**`` in the first row.
    Bottom broad rule ended up in the body block, polluting the
    last row.

    Fix: ``_is_broad_dash_rule`` recognises ≥10-dash single-group
    rules. ``_collect_header_above`` stops at them (without
    including them in parsing) but counts them in the
    ``out``-removal range. Forward scan treats them as closers
    when followed by blank+caption/boundary/EOF.

    Synthesised from Deep-Learning book ``ch03_irbc.tex``'s
    ``tab:bm_vs_irbc`` (LaTeX uses ``p{0.19\\linewidth}`` cols with
    ``\\toprule``/``\\midrule``/``\\bottomrule``)."""
    body = (
        "::: {#tab:bm_vs_irbc}\n"
        "  -" + "-" * 170 + "\n"
        "                        **Brock-Mirman**                                                                                                     **IRBC**\n"
        "  --------------------- ------------------------------------------------------------------------------------------- "
        "-----------------------------------------------------------------\n"
        "  Countries                                                                                                         $N$\n"
        "\n"
        "  States                $(K, z)$                                                                                    $(k^1,\\ldots,k^N)$\n"
        "  -" + "-" * 170 + "\n"
        "\n"
        "  : Caption text.\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Captioned table → {table} wrapper with caption in body and a
    # pipe-table inner (R2 fix — pipe tables avoid the phantom
    # enumerator from a nested {list-table} directive).
    assert "````{table}" in out
    assert "Caption text." in out
    assert "```{list-table}" not in out
    # Header row: empty first cell, then the bold headers.
    assert "**Brock-Mirman**" in out
    assert "**IRBC**" in out
    # Dashes from the broad rules MUST NOT appear in any cell. A
    # pipe-table cell that starts with dashes would render as
    # "|  --..." — we look for any pipe-then-dashes pattern.
    for line in out.split('\n'):
        if line.lstrip().startswith('| --'):
            raise AssertionError(
                f'broad rule dashes leaked into a pipe-table cell: '
                f'{line!r}\n\nfull output:\n{out}'
            )
    # The body row "Countries / / $N$" — first cell Countries, middle empty.
    assert "| Countries |" in out
    assert "$N$" in out
    # :name: from the id fence, fence itself suppressed (R1 fix).
    assert ":name: tab-bm_vs_irbc" in out
    assert "(tab-bm_vs_irbc)=" not in out
    assert "::: {#tab:bm_vs_irbc}" not in out


def test_simple_table_with_caption():
    """Captioned tables with exactly one header row wrap a markdown
    pipe-table inside a ``{table}`` directive.

    Rationale (R2 fix in PR #41 v8): a nested ``{list-table}`` directive
    inside ``{table}`` causes mystmd to register TWO enumerable table
    containers — the outer ``{table}`` and the inner ``{list-table}``
    — so the inner consumes the next table-counter slot and
    ``{numref}`` text drifts off-by-one across the chapter. A
    pipe-table inside ``{table}`` renders as the same HTML output
    but isn't a directive, so only the outer ``{table}`` is
    enumerable.

    The caption lives as the first paragraph of the ``{table}`` body
    (canonical MyST form per
    https://mystmd.org/guide/figures#tables) so inline roles,
    backticks, and long mixed-math captions all parse normally.

    The pipe-table path is conditional on ``header_rows_count == 1``;
    the 0-header and ≥2-header fallback cases are covered by
    ``test_simple_table_with_caption_zero_header_falls_back_to_list_table``
    and (implicitly) the existing multi-block fixtures."""
    # Shape A with interior separator → header_rows_count == 1.
    body = (
        "  ---------- ----------\n"
        "  Sym        Meaning\n"
        "  ---------- ----------\n"
        "  $X$        State\n"
        "  $A$        Action\n"
        "  ---------- ----------\n"
        "\n"
        "  : My caption\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Outer wrapper: 4-backtick fence with EMPTY argument; caption
    # lives as the first paragraph of the body.
    assert "````{table}\n" in out
    # Caption text appears as a body paragraph, not on the opener line.
    assert "My caption" in out
    assert "````{table} My caption" not in out   # not on opener line
    # Inner: pipe-table (no nested {list-table} directive).
    assert "```{list-table}" not in out
    # Pipe-table header row + alignment row + body rows.
    assert "| Sym | Meaning |" in out
    assert "|---|---|" in out
    assert "| $X$ | State |" in out
    assert "| $A$ | Action |" in out
    # Docutils-style option form must NOT appear anywhere.
    assert ":caption:" not in out
    # Caption line should be consumed, not left behind.
    assert "  : My caption" not in out


def test_simple_table_with_caption_zero_header_falls_back_to_list_table():
    """When the captioned table has no detectable header rows (Shape A
    without an interior separator — pandoc's simple_tables format
    collapses interior ``\\hline`` rules so the LaTeX-side header rows
    arrive as ``header_rows_count == 0``), the inner body falls back
    to ``{list-table}`` rather than pipe-table.

    Rationale (PR #41 v9): pipe-table syntax mandates a header row;
    v8's synthetic-empty-header workaround rendered as a visible blank
    row at the top of the table in mystmd — surfaced by book-dp2's
    ``tab-convergence_cases``. The ``{list-table}`` fallback uses
    ``:header-rows: 0`` which renders as a headerless table cleanly.

    Trade-off: the fallback re-introduces the phantom-enumerator
    behaviour for the inner directive (R2). Limited to captioned-
    AND-0-header tables only — rare in practice (zero such tables
    in the Deep-Learning book corpus). The proper fix is the Path C
    follow-up that bypasses pandoc's lossy LaTeX-tabular reader so
    interior ``\\hline`` rules survive to inform ``header_rows_count``.
    """
    # Shape A with NO interior separator → header_rows_count == 0.
    body = _table("A | B") + "\n  : My caption\n"
    out = postprocess.convert_simple_tables(body)
    # Outer {table} wrapper still present.
    assert "````{table}\n" in out
    assert "My caption" in out
    # Inner: {list-table} fallback, not pipe-table.
    assert "```{list-table}" in out
    assert ":header-rows: 0" in out
    # No synthetic blank pipe-table header row.
    assert "|  |  |" not in out
    # Body rows in list-table form.
    assert "* - A" in out
    assert "  - B" in out


def test_simple_table_three_column_basic():
    """3-col tables convert to {list-table} (#34). Headerless shape
    (top rule + rows + bottom rule, no interior separator) emits
    ``:header-rows: 0``."""
    body = (
        "  ----  ----  ----\n"
        "  A     B     C\n"
        "  D     E     F\n"
        "  ----  ----  ----\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 0" in out
    assert "* - A" in out
    assert "  - B" in out
    assert "  - C" in out
    assert "* - D" in out
    assert "  - E" in out
    assert "  - F" in out
    assert "----  ----  ----" not in out


def test_simple_table_three_column_with_header():
    """An interior dash-rule with the same column count as the opener
    marks the header/body boundary and triggers ``:header-rows: 1``
    (#34). This is pandoc's standard simple_tables-with-header shape."""
    body = (
        "  -------- ---------- ----------\n"
        "  Item     Value      Notes\n"
        "  -------- ---------- ----------\n"
        "  alpha    1.0        first\n"
        "  beta     2.5        second\n"
        "  -------- ---------- ----------\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 1" in out
    # Header row present.
    assert "* - Item" in out
    assert "  - Value" in out
    assert "  - Notes" in out
    # Data rows present.
    assert "* - alpha" in out
    assert "* - beta" in out


def test_simple_table_three_column_with_caption():
    """N-col captioned tables use the ``{table}``-wraps-pipe-table
    shape (same wrapper logic as the 2-col case, see
    ``test_simple_table_with_caption`` for rationale)."""
    body = (
        "  -------- ---------- ----------\n"
        "  Item     Value      Notes\n"
        "  -------- ---------- ----------\n"
        "  alpha    1.0        first\n"
        "  beta     2.5        second\n"
        "  -------- ---------- ----------\n"
        "\n"
        "  : Lineage from plain SGD to AdamW.\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "````{table}\n" in out
    assert "Lineage from plain SGD to AdamW." in out
    assert "````{table} Lineage" not in out   # not on opener line
    # Pipe-table body (no nested {list-table} directive).
    assert "```{list-table}" not in out
    assert "| Item | Value | Notes |" in out
    assert "|---|---|---|" in out
    assert "| alpha | 1.0 | first |" in out
    assert "| beta | 2.5 | second |" in out
    # Docutils-style option form must NOT appear.
    assert ":caption:" not in out
    # Caption line should be consumed.
    assert "  : Lineage" not in out


def test_simple_table_five_column():
    """Tables with 5 columns convert correctly — the column-start
    detection generalizes to any N (#34)."""
    body = (
        "  ----  ----  ----  ----  ----\n"
        "  v     w     x     y     z\n"
        "  ----  ----  ----  ----  ----\n"
        "  1     2     3     4     5\n"
        "  6     7     8     9     10\n"
        "  ----  ----  ----  ----  ----\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 1" in out
    assert "* - v" in out
    assert "  - w" in out
    assert "  - z" in out
    assert "* - 1" in out
    assert "  - 5" in out
    assert "* - 6" in out
    assert "  - 10" in out


def test_simple_table_mismatched_column_count_not_fused():
    """A 3-col opener must NOT close on a downstream 2-col rule —
    different column count = different table. Without the guard
    [tables.py:61, :85 — historical line refs], the scan would fuse
    adjacent tables of different shapes into one mangled list-table."""
    body = (
        "  ----  ----  ----\n"
        "  A     B     C\n"
        "  D     E     F\n"
        "  ----  ----  ----\n"
        "\n"
        "Some prose.\n"
        "\n"
        "  ----------  --------------------\n"
        "  alpha       first\n"
        "  beta        second\n"
        "  ----------  --------------------\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Both tables convert independently — two list-tables.
    assert out.count("```{list-table}") == 2
    # Prose between is preserved.
    assert "Some prose." in out
    # First list-table has 3 columns (3 cells per row).
    first_block = out.split("```{list-table}", 2)[1].split("```", 1)[0]
    # Three "* - " starts (one per row) plus two "  - " per row.
    assert first_block.count("* - ") == 2  # 2 data rows after header
    # Confirm the third column from the first table is present.
    assert "  - C" in first_block
    assert "  - F" in first_block


def test_simple_table_three_column_in_center():
    """3-col multiline-style table bounded by ``::: center`` (no closing
    rule). The boundary-stop logic generalizes from 2-col (#34).

    Also pins the Copilot-review fix: the fenced-div + with-header
    shape used to leave the raw body rows in the output (``next_i``
    landed inside the table body, re-emitting the rows after the
    generated ``{list-table}``). The "raw rows absent" assertions
    below are the regression lock — they failed before the
    closer-vs-interior look-ahead and ``next_i = boundary_idx`` fix.
    """
    body = (
        "::: center\n"
        "  ----  ----  ----------\n"
        "  Code  Type  Description\n"
        "  ----  ----  ----------\n"
        "  A     int   first\n"
        "  B     str   second\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 1" in out
    assert "* - Code" in out
    assert "  - Type" in out
    assert "  - Description" in out
    assert "* - A" in out
    assert "  - int" in out
    assert "  - first" in out
    # ``:::`` boundary must NOT be eaten.
    assert ":::" in out
    # Raw body rows must NOT survive after the list-table.
    assert "  A     int" not in out
    assert "  B     str" not in out
    # Dash-rule lines must be gone too.
    assert "----  ----  ----------" not in out


def test_simple_table_same_column_count_tables_separated_by_prose():
    """Bug pinned by Copilot review: two same-column-count tables in
    the same doc, NOT inside ``::: center``, must convert independently.

    Pre-fix the forward scan greedily collected ALL same-N rules until
    EOF, inflating the block count past 2. The first opener bailed,
    then its *closing rule* was re-tried as a new opener — fusing the
    intervening prose into the second table as if it were row content
    (with the prose sliced at column boundaries).

    The closer-vs-interior look-ahead fix stops the scan at the first
    same-N rule whose next non-blank line is out-of-table content
    (different indent, EOF, caption, fence boundary)."""
    body = (
        "  ----  ----\n"
        "  A     B\n"
        "  ----  ----\n"
        "\n"
        "Some prose.\n"
        "\n"
        "  ----  ----\n"
        "  X     Y\n"
        "  ----  ----\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert out.count("```{list-table}") == 2
    assert "Some prose." in out
    # Prose must NOT be sliced into cells.
    assert "* - Some pro" not in out
    assert "  - se." not in out
    # Both tables' rows present.
    assert "* - A" in out
    assert "  - B" in out
    assert "* - X" in out
    assert "  - Y" in out


def test_simple_table_shape_b_header_above_single_rule():
    """Pandoc's ``\\begin{table}\\begin{tabular}...\\end{tabular}
    \\caption{...}\\end{table}`` (no ``\\toprule`` / ``\\bottomrule``)
    produces a single dash-rule with the header row above it and no
    closing rule. The Deep-Learning book has ~37 tables in this shape
    that the original Shape-A-only logic left as raw text (#34). Now
    handled via header-above detection + blank-line/caption implicit
    termination."""
    body = (
        "  Optimizer            Update rule          Reference\n"
        "  -------------------- -------------------- --------------------------\n"
        "  SGD                  plain SGD            standard\n"
        "  Adam                 per-param adaptive   widely used\n"
        "  AdamW                Adam plus decay      current default\n"
        "\n"
        "  : Lineage from plain SGD to AdamW.\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "````{table}\n" in out
    assert "Lineage from plain SGD to AdamW." in out
    assert "````{table} Lineage" not in out
    # Pipe-table body (R2 fix — no nested directive).
    assert "```{list-table}" not in out
    assert ":caption:" not in out
    # Header row absorbed (popped from `out`, not duplicated).
    assert out.count("Optimizer") == 1
    assert "| Optimizer | Update rule | Reference |" in out
    # Body rows present, exactly once each.
    assert "| SGD | plain SGD | standard |" in out
    assert "| Adam | per-param adaptive | widely used |" in out
    assert "| AdamW | Adam plus decay | current default |" in out
    # Dash-rule and caption-as-line must be gone.
    assert "--------------------" not in out
    assert "  : Lineage" not in out


def test_simple_table_shape_b_no_caption_eof():
    """Shape B without a caption — body runs to EOF. The Shape-B
    EOF fallback (header_above non-empty + no other terminator →
    implicit_end_idx = len(lines)) handles this."""
    body = (
        "  Name    Value\n"
        "  ------- -------\n"
        "  alpha   1.0\n"
        "  beta    2.5\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 1" in out
    assert "* - Name" in out
    assert "  - Value" in out
    assert "* - alpha" in out
    assert "* - beta" in out
    # Header line must be absorbed, not left as raw text.
    assert "Name    Value" not in out


def test_simple_table_shape_b_header_indent_within_first_column():
    """Pandoc column-aligns header cells by character position, not by
    leading-whitespace count. A header row at indent 3 on a rule at
    indent 2 is still column-aligned if the first column spans
    positions [2, N) — the header's first non-blank char sits inside
    the first column.

    Surfaced by the Deep-Learning book's ``execution_map`` table
    where the indent-mismatch caused ``_collect_header_above`` to
    return empty, leaving the header line outside the emitted
    ``{list-table}`` and producing a "list-table directive must have
    a list of lists" MyST build error.

    The relaxed indent check
    (``opener_indent <= prev_indent < col_starts[1]``) absorbs this
    case correctly."""
    body = (
        "   **Ch.**  **Topic**               **Notebooks**\n"
        "  --------- ----------------------- ------------------------\n"
        "      1     Intro to ML & DL        01_Intro_to_DL.ipynb\n"
        "      2     Linear regression       02_LinReg.ipynb\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert ":header-rows: 1" in out
    # Header row absorbed.
    assert "* - **Ch.**" in out
    assert "  - **Topic**" in out
    assert "  - **Notebooks**" in out
    # Body rows present.
    assert "* - 1" in out
    assert "  - Intro to ML & DL" in out
    assert "* - 2" in out
    # Header line and dash rule must NOT survive as raw text.
    assert out.count("**Ch.**") == 1
    assert "---------" not in out


def test_simple_table_shape_b_preceded_by_prose_with_blank_separator():
    """Shape-B header detection must NOT absorb preceding paragraphs.
    The blank line between prose and the header bounds the look-back."""
    body = (
        "An introductory paragraph at indent zero.\n"
        "\n"
        "  Item     Value\n"
        "  -------- -------\n"
        "  alpha    1.0\n"
        "  beta     2.5\n"
        "\n"
        "  : Caption text.\n"
    )
    out = postprocess.convert_simple_tables(body)
    # The intro paragraph survives.
    assert "An introductory paragraph at indent zero." in out
    assert out.count("introductory paragraph") == 1
    # Table converted with caption as {table} body paragraph, pipe-table
    # inner (R2 fix).
    assert "````{table}\n" in out
    assert "Caption text." in out
    assert "````{table} Caption" not in out   # not on opener line
    assert "```{list-table}" not in out
    assert ":caption:" not in out
    assert "| Item | Value |" in out
    assert "| alpha | 1.0 |" in out
    assert "| beta | 2.5 |" in out


def test_simple_table_header_plus_caption_inside_center():
    """The combination that #34 originally broke: ``::: center``-wrapped
    table with BOTH a header (interior dash-rule) and a caption between
    the closer and ``:::``. Pre-fix, the caption inflated the block
    count to 3 (header / body / caption), the converter bailed, the
    header-separator rule was then re-tried as an opener, and the
    output was a cascade of fragmented partial conversions. The
    caption-peel logic (last block all caption-shape → drop, let
    caption-detection pick it up) is what fixes this."""
    body = (
        "::: center\n"
        "  -------- --------------------------------\n"
        "  Symbol   Meaning\n"
        "  -------- --------------------------------\n"
        "  $X$      State space\n"
        "  $A$      Action space\n"
        "  $\\pi$    Policy\n"
        "  -------- --------------------------------\n"
        "\n"
        "  : Common symbols used throughout.\n"
        ":::\n"
    )
    out = postprocess.convert_simple_tables(body)
    # Captioned table → {table} wrapper with pipe-table inner.
    assert "````{table}\n" in out
    assert "Common symbols used throughout." in out
    assert "````{table} Common" not in out
    assert "```{list-table}" not in out
    assert ":caption:" not in out
    # Pipe-table rows.
    assert "| Symbol | Meaning |" in out
    assert "|---|---|" in out
    assert "| $X$ | State space |" in out
    assert "| $A$ | Action space |" in out
    # The opening fenced-div line and its closer must survive intact.
    assert "::: center" in out
    assert ":::" in out
    # No dash-rule leftovers and no caption-as-row leakage.
    assert "----" not in out


def test_simple_table_three_column_multiline_cells():
    """Multiline-table shape with N=3: blank-line-separated rows whose
    cells span multiple lines join with single spaces."""
    body = (
        "  ----  ----  --------------------\n"
        "  A     1     first item\n"
        "\n"
        "  B     2     a longer\n"
        "              wrapped value\n"
        "\n"
        "  ----  ----  --------------------\n"
    )
    out = postprocess.convert_simple_tables(body)
    assert "```{list-table}" in out
    assert "* - A" in out
    assert "  - 1" in out
    assert "  - first item" in out
    assert "* - B" in out
    assert "  - 2" in out
    assert "  - a longer wrapped value" in out





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


def test_simple_table_in_center_survives_pipeline_ordering():
    """GH #27 — the GH #24 fix bounds the table scan on the ``:::``
    fenced-div boundary, but ``convert_environment_divs`` strips
    ``::: center`` wrappers (``ENV_SKIP`` at module top). If
    ``convert_environment_divs`` runs *before* ``convert_simple_tables``,
    the boundary disappears and the scan fuses adjacent tables again —
    exactly the regression the #24 fix was meant to prevent. The
    pipeline must order ``convert_simple_tables`` first.

    Mirrors the real pipeline order (env-divs after tables) rather than
    a direct call so a future re-ordering can't silently re-break this.
    """
    body = (
        "::: center\n"
        "  ----------  --------------------\n"
        "  $\\alpha$    first letter\n"
        "  $\\beta$     second letter\n"
        ":::\n"
        "\n"
        "Paragraph between tables.\n"
        "\n"
        "::: center\n"
        "  ----  ----------\n"
        "  A     first\n"
        "  B     second\n"
        ":::\n"
    )
    # Pipeline order: tables first, then env-divs.
    out = postprocess.convert_environment_divs(
        postprocess.convert_simple_tables(body)
    )
    assert out.count("```{list-table}") == 2, \
        "tables must convert independently before ::: center is stripped"
    assert "Paragraph between tables." in out
    # Confirm the bug shape if the order were reversed: env-divs first
    # would strip the boundary, the scan would fuse, and only one
    # list-table would appear. This isn't asserted (it's the bug we're
    # avoiding) but documenting it here so a future reader sees what
    # ordering matters and why.


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


def test_hoist_heading_labels_two_labels_split_form():
    """`\\subsection{T}\\label{ss:a}\\n\\label{sss:b}` — pandoc folds the
    first label into the heading id and emits the second as a leading
    mid-line span on the next paragraph; hoist it above the heading (#108)."""
    body = (
        '(ss-gfsmdp)=\n'
        '## The MDP Model\n'
        '\n'
        '[]{#sss:fsmdp label="sss:fsmdp"} We study a controller.\n'
    )
    out = postprocess.hoist_consecutive_heading_labels(body)
    assert out == (
        '(ss-gfsmdp)=\n'
        '(sss-fsmdp)=\n'
        '## The MDP Model\n'
        '\n'
        'We study a controller.\n'
    )


def test_hoist_heading_labels_three_labels_one_line():
    """Three consecutive `\\label`s — two spans land on the next paragraph."""
    body = (
        '(ss-a)=\n'
        '## Three Labels\n'
        '\n'
        '[]{#ss:b label="ss:b"}[]{#ss:c label="ss:c"} First paragraph.\n'
    )
    out = postprocess.hoist_consecutive_heading_labels(body)
    assert out == (
        '(ss-a)=\n'
        '(ss-b)=\n'
        '(ss-c)=\n'
        '## Three Labels\n'
        '\n'
        'First paragraph.\n'
    )


def test_hoist_heading_labels_no_orphan_is_noop():
    """A heading whose following paragraph has no leading anchor is untouched."""
    body = (
        '(ss-a)=\n'
        '## Solo Label\n'
        '\n'
        'Just prose, no orphan anchor.\n'
    )
    out = postprocess.hoist_consecutive_heading_labels(body)
    assert out == body


def test_hoist_heading_labels_leaves_non_heading_orphan():
    """A leading anchor on a paragraph NOT preceded by a heading is left for
    the existing strip path (e.g. footnote-body orphan)."""
    body = '[^1]: []{#fn:hcon label="fn:hcon"}Footnote body.\n'
    out = postprocess.hoist_consecutive_heading_labels(body)
    assert out == body


def test_hoist_heading_labels_leaves_chapter_h1_explicit_label():
    """A ``# Chapter`` H1 with an explicit following ``[]{#c:...}`` label must
    NOT be hoisted — that label is consumed later by ``add_frontmatter``'s
    "prefer explicit chapter label" path (lesson 017). Stacking the label
    above the H1 would stop ``add_frontmatter`` from matching/absorbing the
    heading. Only section-level (H2+) headings are hoist targets, so the H1
    case is left untouched (both the own-line and mid-line label shapes)."""
    own_line = (
        '(c-intro-auto)=\n'
        '# The Introduction\n'
        '\n'
        '[]{#c:climate label="c:climate"}\n'
        'This chapter studies climate.\n'
    )
    mid_line = (
        '(c-intro-auto)=\n'
        '# The Introduction\n'
        '\n'
        '[]{#c:climate label="c:climate"} This chapter studies climate.\n'
    )
    assert postprocess.hoist_consecutive_heading_labels(own_line) == own_line
    assert postprocess.hoist_consecutive_heading_labels(mid_line) == mid_line


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


def test_environment_div_widens_fence_around_nested_code_block():
    """Issue #79 — a prose directive (here an Exercise) whose body
    contains a ```` ```python ```` block must open/close with a *four*-
    backtick fence, else the inner block's bare closing ``` terminates
    the directive early (lesson 040). Code blocks are emitted by
    ``convert_pandoc_attr_code_blocks`` before this pass, so they are
    present in the body when the fence width is chosen."""
    body = (
        '::: Exercise\n'
        '[]{#ex:code label="ex:code"} Implement the loss:\n'
        '\n'
        '```python\n'
        'def loss(y, yhat):\n'
        '    return ((y - yhat) ** 2).mean()\n'
        '```\n'
        ':::\n'
    )
    out = postprocess.convert_environment_divs(body)
    assert '````{exercise}' in out          # four-backtick opener
    assert '`````{exercise}' not in out      # not over-widened
    assert ':label: ex-code' in out
    assert '```python' in out                # inner block intact
    # Exactly one bare four-backtick line — the directive's own closer.
    assert out.splitlines().count('````') == 1


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


# ── Pandoc HTML-comment separator artifacts (issue #23) ─────────────────────


def test_strip_pandoc_html_separators_inline_math_followed_by_digit():
    """GH #23 — pandoc inserts ``\\`<!-- -->\\`{=html}`` between an
    inline ``$math$`` and a following digit (its CommonMark
    lexer-defeat trick). MyST doesn't need the separator, so it
    surfaces as raw text in the rendered HTML."""
    src = "Took ($\\sim$`<!-- -->`{=html}30 s, sanity check) on this run."
    out = postprocess.strip_pandoc_html_separators(src)
    assert out == "Took ($\\sim$30 s, sanity check) on this run."


def test_strip_pandoc_html_separators_multiple_occurrences():
    src = (
        "Use $c$`<!-- -->`{=html}9 collocation points; "
        "convergence took $\\sim$`<!-- -->`{=html}5 min.\n"
    )
    out = postprocess.strip_pandoc_html_separators(src)
    assert "<!-- -->" not in out
    assert "{=html}" not in out
    assert "Use $c$9 collocation points" in out
    assert "$\\sim$5 min" in out


def test_strip_pandoc_html_separators_does_not_touch_real_html_comments():
    """A comment that carries content is a genuine HTML comment, not
    pandoc's empty separator artifact — leave it alone."""
    src = "<!-- TODO: cite this --> The result follows."
    out = postprocess.strip_pandoc_html_separators(src)
    assert out == src


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


def test_convert_equations_multirow_align_per_row_labels_emit_anchors():
    """GH #30 / #70 — ``\\begin{align}`` with 2+ per-row ``\\label{}``
    markers (no leading label after ``\\begin{align}``). Each label
    must yield its own resolvable anchor; ``\\label{}`` must not
    survive into the body (KaTeX silently drops it, leaving
    ``\\eqref{}`` unresolved).

    Updated for #70: previously the converter emitted one ``aligned``
    block with N ``(name)=`` anchors stacked above. MyST collapses
    consecutive ``(name)=`` lines to one target — only the first
    label survived; non-first refs dangled. The fix splits the align
    body into per-row ``$$...$$`` blocks each with their own trailing
    label. Column alignment (``&``) is lost as a result; per-row
    cross-references are preserved."""
    text = (
        "$$\\begin{align}\n"
        "a &= b, \\label{eq:row_a}\\\\\n"
        "c &= d. \\label{eq:row_b}\n"
        "\\end{align}$$\n"
    )
    out = postprocess.convert_equations(text)
    # Both labels resolve via the trailing-paren shape on their own
    # split block.
    assert "$$ (eq-row_a)" in out
    assert "$$ (eq-row_b)" in out
    assert "\\label{" not in out
    # The aligned wrapper is gone — split path emits bare $$...$$.
    assert "\\begin{aligned}" not in out
    # Each row's content survives into its own block.
    assert "a = b" in out
    assert "c = d" in out


def test_convert_equations_align_leading_plus_per_row_labels():
    """A ``\\begin{align}\\label{X}`` (leading label) plus additional
    per-row ``\\label{}``s: the leading label keeps the trailing
    ``(X)`` form for backward compatibility, extras stack as anchors
    above. All refs resolve to the same block — numbering collapses but
    no cross-ref is broken."""
    text = (
        "$$\\begin{align}\\label{eq:lead}\n"
        "a &= b, \\label{eq:row_a}\\\\\n"
        "c &= d.\n"
        "\\end{align}$$\n"
    )
    out = postprocess.convert_equations(text)
    assert "(eq-row_a)=" in out
    assert "$$ (eq-lead)" in out
    assert "\\label{" not in out


def test_convert_equations_align_no_labels_unchanged_shape():
    """Regression guard: an unlabeled multi-row align still produces
    just the ``\\begin{aligned}`` wrap with no spurious anchors."""
    text = (
        "$$\\begin{align}\n"
        "a &= b,\\\\\n"
        "c &= d.\n"
        "\\end{align}$$\n"
    )
    out = postprocess.convert_equations(text)
    assert "\\begin{aligned}" in out
    assert "=" not in [line.strip() for line in out.splitlines() if line.strip().startswith("(")]


def test_convert_equations_align_2plus_per_row_labels_splits_to_avoid_collision():
    """GH #70 — when an align body has 2+ per-row ``\\label{}`` calls,
    stacking them as ``(name)=`` anchors above a single
    ``\\begin{aligned}`` block makes MyST collapse all anchors to the
    SAME target (only the first survives, the rest get renamed and
    non-first refs dangle). Reproducer mirrors dp-deep-learning's
    ch11_climate temperature equations. The fix splits the align body
    into per-row ``$$...$$`` blocks each carrying its own trailing
    label — each anchor lands on a distinct block."""
    text = (
        "$$\\begin{align}\n"
        "T^{\\mathrm{AT}}_{t+1} &= T^{\\mathrm{AT}}_t + c_1 X_t, \\label{eq:temp_at}\\\\\n"
        "T^{\\mathrm{OC}}_{t+1} &= T^{\\mathrm{OC}}_t + c_4 Y_t. \\label{eq:temp_oc}\n"
        "\\end{align}$$\n"
    )
    out = postprocess.convert_equations(text)
    # Both labels land on their own block (trailing-paren shape).
    assert "$$ (eq-temp_at)" in out
    assert "$$ (eq-temp_oc)" in out
    # No `aligned` wrapper survives — split path takes over.
    assert "\\begin{aligned}" not in out
    # `&` alignment markers removed from each row.
    assert "&=" not in out
    # The bridging `,` before each `\label{}` is gone too (sentence-
    # style separator, not part of the equation).
    assert "c_1 X_t," not in out
    # Original `\label{}` calls do not survive.
    assert "\\label{" not in out


def test_convert_equations_align_2plus_tags_splits_to_avoid_multiple_tag_error():
    """GH #46 — when an align body has 2+ per-row ``\\tag*{}`` calls,
    keeping them inside one ``\\begin{aligned}`` triggers KaTeX's
    ``Multiple \\tag`` error (KaTeX allows at most one tag per equation
    env). Mirrors dp-deep-learning's ch11_climate IAM-loss block (8
    rows, 8 tags). The fix shares the per-row split with #70 — each
    tag now lives in its own ``$$...$$`` block where one tag per env
    is the supported shape."""
    text = (
        "$$\\begin{align}\n"
        "l_1 &= F_1(x) \\tag*{(capital Euler)}\\\\\n"
        "l_2 &= F_2(x) \\tag*{(budget)}\\\\\n"
        "l_3 &= F_3(x) \\tag*{(atm. carbon)}\n"
        "\\end{align}$$\n"
    )
    out = postprocess.convert_equations(text)
    # Aligned wrapper is gone — each tagged row gets its own block.
    assert "\\begin{aligned}" not in out
    # Three separate $$...$$ blocks emitted.
    assert out.count("$$\n") + out.count("\n$$") >= 6  # 3 opens + 3 closes
    # All three tags survive (the `\tag*{}` content itself is left
    # intact in the per-row content — KaTeX renders it as the row's
    # equation label).
    assert "\\tag*{(capital Euler)}" in out
    assert "\\tag*{(budget)}" in out
    assert "\\tag*{(atm. carbon)}" in out


def test_convert_equations_align_leading_plus_2plus_per_row_splits():
    """When a labeled-align (``\\begin{align}\\label{X}``) ALSO has
    2+ per-row labels in its body, the per-row collision still
    applies — fall back to the split path. The leading label becomes
    a ``(name)=`` anchor above the first per-row block (no other
    natural place to attach an "outer" label once the aligned wrapper
    is dissolved)."""
    text = (
        "$$\\begin{align}\\label{eq:outer}\n"
        "a &= b, \\label{eq:row_a}\\\\\n"
        "c &= d. \\label{eq:row_b}\n"
        "\\end{align}$$\n"
    )
    out = postprocess.convert_equations(text)
    # Leading label attaches as anchor above the first block.
    assert "(eq-outer)=" in out
    # Per-row labels each get their own trailing form.
    assert "$$ (eq-row_a)" in out
    assert "$$ (eq-row_b)" in out
    # Outer-anchor sits before the first per-row block.
    assert out.index("(eq-outer)=") < out.index("$$ (eq-row_a)")
    assert "\\begin{aligned}" not in out


def test_convert_equations_multline_trailing_label_extracted():
    """GH #37 — ``\\begin{multline}`` standard convention puts the
    label at the *end* of the body. The pre-fix regex required the
    label *immediately* after ``\\begin{multline}``, so this dominant
    shape was missed and the label survived into the math body —
    KaTeX silently drops it and ``\\eqref{}`` resolves to nothing.
    Same shape of bug that #26 fixed for ``equation`` and #30 fixed
    for ``align``."""
    text = (
        "$$\\begin{multline}\n"
        "a + b\\\\\n"
        "+ c = d\n"
        "\\label{eq:foo}\n"
        "\\end{multline}$$\n"
    )
    out = postprocess.convert_equations(text)
    assert "$$ (eq-foo)" in out
    assert "\\label{" not in out


def test_convert_equations_multline_no_label_unchanged():
    """Regression guard: an unlabeled ``multline`` still produces a
    bare ``$$ … $$`` block."""
    text = (
        "$$\\begin{multline}\n"
        "a + b\\\\\n"
        "+ c = d\n"
        "\\end{multline}$$\n"
    )
    out = postprocess.convert_equations(text)
    assert "$$" in out
    # No trailing-label artifact.
    assert "()" not in out
    assert "\\begin{multline}" not in out


def test_convert_equations_gather_per_row_labels():
    """GH #37 — ``\\begin{gather}`` legitimately carries per-row
    labels (one number per stacked equation). First label becomes
    the block's trailing ``(label)`` for backward-compat; the rest
    stack as anchors above (the same convention #30 chose for
    multi-row align)."""
    text = (
        "$$\\begin{gather}\n"
        "a = 1 \\label{eq:a}\\\\\n"
        "b = 2 \\label{eq:b}\n"
        "\\end{gather}$$\n"
    )
    out = postprocess.convert_equations(text)
    assert "$$ (eq-a)" in out
    assert "(eq-b)=" in out
    assert "\\label{" not in out
    # Stacked anchor comes before the math block.
    assert out.index("(eq-b)=") < out.index("$$")


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


def test_html_figure_caption_ref_becomes_myst_directive_not_baked_number():
    """GH #33 — a ``\\ref{sec:X}`` inside a ``\\caption{}`` is resolved
    by pandoc to a chapter-unaware number BEFORE MyST gets a chance.
    The HTML caption arrives shaped like ``§<a data-reference="sec:X">
    1.12</a>`` where ``1.12`` is wrong (the book number is §11.12).
    Strip the baked-in number, keep the label, emit a MyST ``{ref}``
    directive that MyST resolves with full project context. The
    leading ``§`` doubles with MyST's auto-rendered ``Section …`` and
    must be removed."""
    pandoc_out = (
        '<figure id="fig:bar">\n'
        '<img src="img.png" />\n'
        '<figcaption>The bilevel search of §<a href="#sec:foo" '
        'data-reference-type="ref" data-reference="sec:foo">1.12</a> '
        'is end-to-end feasible.</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert '{ref}`sec-foo`' in out
    # Pre-resolved number must be gone.
    assert '1.12' not in out
    # Leading § must be dropped (sphinx-proof auto-renders the noun).
    assert '§{ref}`sec-foo`' not in out
    assert '§ {ref}`sec-foo`' not in out


def test_html_figure_caption_ref_preserves_non_section_targets():
    """A non-section target (e.g. ``eq:`` / ``thm:``) inside a caption
    routes to ``{eq}`` / ``{prf:ref}`` via the existing label-routing
    rules. Regression guard: ``extract_caption`` shouldn't bypass that
    routing — for now it produces ``{ref}`` and the downstream
    cross-ref converter doesn't re-touch caption text, so this just
    documents current behaviour (still resolves; numbering may differ
    from a ``{eq}`` role but no broken refs)."""
    pandoc_out = (
        '<figure id="fig:bar">\n'
        '<img src="img.png" />\n'
        '<figcaption>See <a href="#thm:main" '
        'data-reference-type="ref" data-reference="thm:main">2</a>.'
        '</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    # Label survives; pre-resolved number does not leak as literal text.
    assert 'thm-main' in out
    assert '>2</a>' not in out
    assert 'See 2.' not in out  # the baked number must not survive as plain text


def test_html_figure_caption_no_refs_unchanged_shape():
    """Regression guard: a caption with no HTML ref anchors keeps the
    existing strip-all-html behaviour."""
    pandoc_out = (
        '<figure id="fig:bar">\n'
        '<img src="img.png" />\n'
        '<figcaption>Plain caption with <em>emphasis</em>.</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert 'Plain caption with emphasis.' in out


def test_non_nested_figure_with_img_src_emits_figure_not_admonition():
    """GH #25 — pandoc emits ``<img src=...>`` (not ``<embed>``) for
    plain ``\\includegraphics`` figures. The Pass 2 (non-nested) branch
    used to call ``make_admonition`` unconditionally, mis-classifying
    every such figure as a TikZ placeholder."""
    pandoc_out = (
        '<figure id="fig:loss_kernels" data-latex-placement="ht">\n'
        '<img src="loss_kernel_convergence.png" />\n'
        '<figcaption>Convergence of relative Euler-error.</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert '```{figure}' in out
    assert 'loss_kernel_convergence.png' in out
    assert ':name: fig-loss_kernels' in out
    assert 'TikZ' not in out


def test_nested_subfigure_with_img_src_emits_figure():
    """GH #25 — the Pass 1 nested-subfigure branch must also recognise
    ``<img src=...>``, not just ``<embed>``."""
    pandoc_out = (
        '<figure id="fig:panels">\n'
        '<figure>\n'
        '<img src="panel_a.png" />\n'
        '<figcaption>Panel A</figcaption>\n'
        '</figure>\n'
        '<figure>\n'
        '<img src="panel_b.png" />\n'
        '<figcaption>Panel B</figcaption>\n'
        '</figure>\n'
        '<figcaption>Two panels.</figcaption>\n'
        '</figure>\n'
    )
    out = postprocess.convert_html_figures(pandoc_out)
    assert 'panel_a.png' in out
    assert 'panel_b.png' in out
    assert 'TikZ' not in out


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
