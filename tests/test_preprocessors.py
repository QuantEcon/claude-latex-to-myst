"""Tests for the pre-pandoc preprocessor scripts (algorithm + listing
marker emitters). These run on raw .tex bytes and produce the
HTML-comment markers that pandoc passes through verbatim.
"""

from __future__ import annotations

import base64
import re

# Module names are dotted because they live alongside other scripts under
# the `scripts/` directory, which pyproject.toml already adds to sys.path.
import _apply_algorithm_markers as alg
import _apply_listing_markers as lst


# ── Algorithm markers ────────────────────────────────────────────────────────


def _extract_marker(out: str) -> dict:
    m = re.search(
        r'<!--ALGORITHM name=(\S+) title=(.*?) body=([A-Za-z0-9+/=]+)-->',
        out,
        re.DOTALL,
    )
    assert m, f"no marker in output: {out!r}"
    return {
        "name": m.group(1),
        "title": m.group(2),
        "body": base64.b64decode(m.group(3)).decode("utf-8"),
    }


def test_algorithm_marker_with_caption_label():
    tex = (
        "\\begin{algorithm}\n"
        "    \\DontPrintSemicolon\n"
        "    input $v$ \\;\n"
        "    \\caption{\\label{algo:vfi_os} Value function iteration}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="x")
    m = _extract_marker(out)
    assert m["name"] == "algo-vfi_os"  # colon→hyphen
    assert m["title"] == "Value function iteration"
    # Body has caption stripped but the rest is preserved
    assert "\\DontPrintSemicolon" in m["body"]
    assert "input $v$" in m["body"]
    assert "\\caption" not in m["body"]


def test_algorithm_marker_caption_without_label():
    tex = (
        "\\begin{algorithm}\n"
        "    body \\;\n"
        "    \\caption{Just a title}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    m = _extract_marker(out)
    assert m["name"] == "algo-ch-auto-1"  # auto-generated
    assert m["title"] == "Just a title"


def test_algorithm_marker_no_caption_auto_labels():
    tex = (
        "\\begin{algorithm}\nbody1 \\;\n\\end{algorithm}\n"
        "\\begin{algorithm}\nbody2 \\;\n\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    # Two markers, each with an auto-generated name
    markers = re.findall(r'name=(\S+)', out)
    assert markers == ["algo-ch-auto-1", "algo-ch-auto-2"]


def test_algorithm_marker_optional_arg_ignored():
    """``\\begin{algorithm}[H]`` is the LaTeX float-placement option;
    the preprocessor must skip it without including in the body."""
    tex = (
        "\\begin{algorithm}[H]\n"
        "    body \\;\n"
        "    \\caption{T}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="x")
    m = _extract_marker(out)
    assert "[H]" not in m["body"]


def test_algorithm_marker_idempotent_noop_on_no_match():
    tex = "no algorithm blocks here\n"
    assert alg.process_text(tex, auto_prefix="x") == tex


# ── Listing markers ──────────────────────────────────────────────────────────


def test_listing_marker_extracts_fields():
    tex = (
        "\\begin{listing}\n"
        "\\inputminted[firstline=3, lastline=20, fontsize=\\small]"
        "{julia}{../source_code_jl/foo.jl}\n"
        "\\caption{\\label{list:foo} Foo caption}\n"
        "\\end{listing}\n"
    )
    out = lst.process_text(tex)
    m = re.search(
        r'<!--LISTING-START name=(\S+) lang=(\S+) path=(\S+) '
        r'first=(\d*) last=(\d*)-->\n(.*?)\n<!--LISTING-END-->',
        out,
        re.DOTALL,
    )
    assert m, f"no marker: {out!r}"
    name, lang, path, first, last, caption = m.groups()
    assert name == "list-foo"
    assert lang == "julia"
    assert path == "../source_code_jl/foo.jl"
    assert first == "3"
    assert last == "20"
    assert caption == "Foo caption"


def test_listing_marker_missing_inputminted_defaults_lang_text():
    tex = (
        "\\begin{listing}\n"
        "\\caption{\\label{list:x} no minted}\n"
        "\\end{listing}\n"
    )
    out = lst.process_text(tex)
    assert "lang=text" in out


def test_listing_marker_handles_multiline_caption():
    """Captions can span lines and contain inline math; the regex collapses
    whitespace."""
    tex = (
        "\\begin{listing}\n"
        "\\inputminted{python}{src.py}\n"
        "\\caption{\\label{list:m} Multi-line\n"
        "    caption that spans}\n"
        "\\end{listing}\n"
    )
    out = lst.process_text(tex)
    assert "Multi-line caption that spans" in out
