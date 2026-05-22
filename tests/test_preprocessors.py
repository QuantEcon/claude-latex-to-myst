"""Tests for the pre-pandoc preprocessor scripts (algorithm + listing
marker emitters). These run on raw .tex bytes and produce the
HTML-comment markers that pandoc passes through verbatim.
"""

from __future__ import annotations

import base64
import re

# Module names are dotted because they live alongside other scripts under
# the `scripts/` directory, which pyproject.toml already adds to sys.path.
import pytest

import _apply_algorithm_markers as alg
import _apply_chapter_splits as split
import _apply_description_markers as desc
import _apply_listing_markers as lst
import _apply_rewrites as rew


def _apply_natbib(text: str) -> str:
    for pat, repl in rew._NATBIB_REWRITES:
        text = re.sub(pat, repl, text)
    return text


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


def test_algorithm_marker_skips_commented_out_block():
    """FOLLOWUP #014, Gap A: a `\\begin{algorithm}` on a line that's
    already commented out with `%` must NOT be rewritten — otherwise
    the END marker ends up on a fresh (uncommented) line and leaks
    into pandoc's output."""
    tex = (
        "%\\begin{algorithm}\n"
        "%    body \\;\n"
        "%    \\caption{T}\n"
        "%\\end{algorithm}\n"
    )
    # Should be left unchanged (pandoc will strip the comments naturally).
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


def test_listing_marker_skips_commented_out_block():
    """FOLLOWUP #014, Gap A (listing variant): same as the algorithm
    case — commented-out `\\begin{listing}` must not be rewritten or
    we leak a literal `<!--LISTING-END-->` into the .md output."""
    tex = (
        "%\\begin{listing}\n"
        "%\\inputminted[firstline=1, lastline=5]{python}{src.py}\n"
        "%\\caption{\\label{list:foo} ignored}\n"
        "%\\end{listing}\n"
    )
    assert lst.process_text(tex) == tex


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


# ── Natbib pre-pandoc rewrites ───────────────────────────────────────────────


def test_natbib_rewrite_plain_citep():
    assert _apply_natbib(r"\citep{smith2020}") == "[[CITEP:smith2020]]"


def test_natbib_rewrite_plain_citealp_multi_key():
    assert _apply_natbib(r"\citealp{a, b}") == "[[CITEALP:a, b]]"


def test_natbib_rewrite_citeyearpar_wins_over_citeyear():
    """Both share a prefix; the longer pattern must win — regression
    guard for the ordering inside ``_NATBIB_REWRITES``."""
    assert _apply_natbib(r"\citeyearpar{k}") == "[[CITEYEARPAR:k]]"
    assert _apply_natbib(r"\citeyear{k}") == "[[CITEYEAR:k]]"


@pytest.mark.parametrize("src,want", [
    # GH #13: single locator
    (r"\citep[p.~351]{loewenstein1991negative}",
     "[[CITEP:loewenstein1991negative]]"),
    # natbib's pre + post locators
    (r"\citep[see][p.~12]{key}", "[[CITEP:key]]"),
    # whitespace between cite and locator
    (r"\citep [p.~7]{key}", "[[CITEP:key]]"),
    # all variants accept locators
    (r"\citealp[p.~1]{k}",    "[[CITEALP:k]]"),
    (r"\citealt[p.~1]{k}",    "[[CITEALT:k]]"),
    (r"\citeauthor[p.~1]{k}", "[[CITEAUTHOR:k]]"),
    (r"\citeyear[p.~1]{k}",   "[[CITEYEAR:k]]"),
    (r"\citeyearpar[p.~1]{k}", "[[CITEYEARPAR:k]]"),
])
def test_natbib_rewrite_drops_locator_arg(src, want):
    """Locator args (``[p.~351]``) must not block the rewrite, and must
    be discarded (MyST has no locator-suffix syntax). GH #13."""
    assert _apply_natbib(src) == want


# ── Chapter splits (multi-chapter source files) ──────────────────────────────


def test_chapter_split_two_chapters(tmp_path):
    src = tmp_path / "appendix.tex"
    src.write_text(
        "\\chapter{Suprema and Infima}\\label{c:areal}\n"
        "Body of A.\n"
        "\\chapter{Remaining Proofs}\\label{c:ai}\n"
        "Body of B.\n",
        encoding="utf-8",
    )
    split.split_one(src, ["appA", "appB"], skip_extra=False, tmp_dir=tmp_path)
    assert not src.exists()  # source consumed
    appA = (tmp_path / "appA.tex").read_text(encoding="utf-8")
    appB = (tmp_path / "appB.tex").read_text(encoding="utf-8")
    assert appA.startswith("\\chapter{Suprema and Infima}")
    assert "Body of A." in appA
    assert "Body of B." not in appA
    assert appB.startswith("\\chapter{Remaining Proofs}")
    assert "Body of B." in appB


def test_chapter_split_skip_extra_discards_trailing(tmp_path):
    """dp1's appendix.tex has 3 \\chapter blocks; the 3rd
    (\\shipoutAnswer) produces no usable content and should be
    discarded via skip_extra: true."""
    src = tmp_path / "appendix.tex"
    src.write_text(
        "\\chapter{One}\nA\n"
        "\\chapter{Two}\nB\n"
        "\\chapter{Three discarded}\nC\n",
        encoding="utf-8",
    )
    split.split_one(src, ["appA", "appB"], skip_extra=True, tmp_dir=tmp_path)
    assert (tmp_path / "appA.tex").exists()
    assert (tmp_path / "appB.tex").exists()
    # No third output:
    assert not list(tmp_path.glob("*Three*"))
    assert "Three discarded" not in (tmp_path / "appB.tex").read_text(encoding="utf-8")


def test_chapter_split_errors_on_extra_without_skip(tmp_path):
    src = tmp_path / "appendix.tex"
    src.write_text(
        "\\chapter{One}\nA\n\\chapter{Two}\nB\n\\chapter{Three}\nC\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        split.split_one(src, ["appA", "appB"], skip_extra=False, tmp_dir=tmp_path)
    assert "skip_extra" in str(exc.value)


def test_chapter_split_errors_if_too_few_chapters(tmp_path):
    src = tmp_path / "appendix.tex"
    src.write_text("\\chapter{Only One}\nA\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        split.split_one(src, ["appA", "appB"], skip_extra=False, tmp_dir=tmp_path)
    assert "only 1" in str(exc.value).lower() or "1 \\chapter" in str(exc.value)


def test_chapter_split_handles_chapter_star(tmp_path):
    """\\chapter*{Title} (unnumbered) is also a chapter boundary."""
    src = tmp_path / "src.tex"
    src.write_text(
        "\\chapter{First}\nA\n\\chapter*{Unnumbered}\nB\n",
        encoding="utf-8",
    )
    split.split_one(src, ["one", "two"], skip_extra=False, tmp_dir=tmp_path)
    assert "First" in (tmp_path / "one.tex").read_text(encoding="utf-8")
    assert "Unnumbered" in (tmp_path / "two.tex").read_text(encoding="utf-8")


def test_chapter_split_handles_optional_short_title(tmp_path):
    """GH #18: ``\\chapter[short]{long}`` is used when the TOC/running
    head needs a different label than the body title. The splitter
    must recognise it as a chapter boundary."""
    src = tmp_path / "src.tex"
    src.write_text(
        "\\chapter{Plain}\nA\n"
        "\\chapter[Short]{Long body title}\nB\n",
        encoding="utf-8",
    )
    split.split_one(src, ["one", "two"], skip_extra=False, tmp_dir=tmp_path)
    assert "Plain" in (tmp_path / "one.tex").read_text(encoding="utf-8")
    assert "Long body title" in (tmp_path / "two.tex").read_text(encoding="utf-8")


def test_chapter_split_handles_chapter_star_with_optional_arg(tmp_path):
    """``\\chapter*[short]{long}`` is rare but legal."""
    src = tmp_path / "src.tex"
    src.write_text(
        "\\chapter{First}\nA\n"
        "\\chapter*[Short]{Unnumbered long}\nB\n",
        encoding="utf-8",
    )
    split.split_one(src, ["one", "two"], skip_extra=False, tmp_dir=tmp_path)
    assert "First" in (tmp_path / "one.tex").read_text(encoding="utf-8")
    assert "Unnumbered long" in (tmp_path / "two.tex").read_text(encoding="utf-8")


def test_chapter_split_no_chapter_blocks_errors(tmp_path):
    src = tmp_path / "src.tex"
    src.write_text("No chapter macros here.\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        split.split_one(src, ["a"], skip_extra=False, tmp_dir=tmp_path)
    assert "no \\chapter" in str(exc.value).lower()


# ── Description list markers (issue #19) ─────────────────────────────────────


def _decode_desc(out: str) -> list[tuple[str, str]]:
    """Pull the (term, body) pairs out of a DESCRIPTION-marked string."""
    items = []
    for m in re.finditer(
        r'<!--DESCITEM term=([A-Za-z0-9+/=]*)-->\n+(.*?)(?=\n+<!--DESCITEM|\n+<!--DESCRIPTION-END)',
        out,
        re.DOTALL,
    ):
        term = base64.b64decode(m.group(1)).decode("utf-8")
        items.append((term, m.group(2).strip()))
    return items


def test_description_marker_basic_two_items():
    tex = (
        r"\begin{description}" "\n"
        r"\item[Term One] Body one." "\n"
        r"\item[Term Two] Body two." "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    assert "<!--DESCRIPTION-START-->" in out
    assert "<!--DESCRIPTION-END-->" in out
    items = _decode_desc(out)
    assert items == [("Term One", "Body one."), ("Term Two", "Body two.")]


def test_description_marker_strips_optional_arg():
    """``\\begin{description}[opts]`` formatting options have no MyST
    analogue and must be dropped, not leaked into the body."""
    tex = (
        r"\begin{description}[itemsep=3pt, leftmargin=1.4em]" "\n"
        r"\item[T] B" "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    assert "itemsep" not in out
    assert _decode_desc(out) == [("T", "B")]


def test_description_marker_handles_multi_paragraph_body():
    tex = (
        r"\begin{description}" "\n"
        r"\item[Term] First paragraph." "\n"
        "\n"
        "Second paragraph still under term.\n"
        r"\item[Other] Just one para." "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    items = _decode_desc(out)
    assert items[0][0] == "Term"
    assert "First paragraph" in items[0][1]
    assert "Second paragraph still under term" in items[0][1]
    assert items[1] == ("Other", "Just one para.")


def test_description_marker_item_without_optional_arg():
    """``\\item`` with no ``[…]`` is legal LaTeX (renders with no term)."""
    tex = (
        r"\begin{description}" "\n"
        r"\item Term-less body." "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    items = _decode_desc(out)
    assert items == [("", "Term-less body.")]


def test_description_marker_skips_commented_block():
    """A ``\\begin{description}`` on a commented-out line must be left
    alone — same guard as the algorithm + listing preprocessors."""
    tex = (
        "%\\begin{description}\n"
        "%\\item[T] B\n"
        "%\\end{description}\n"
    )
    assert desc.process_text(tex) == tex


def test_description_marker_no_items_left_intact():
    """A description env with no \\item inside is malformed; better to
    leave it in the source for a human to look at than to silently emit
    an empty marker block."""
    tex = "\\begin{description}\nempty\n\\end{description}\n"
    assert "<!--DESCRIPTION" not in desc.process_text(tex)


def test_description_marker_term_with_brackets_and_math():
    """Term labels can contain inline math and other punctuation;
    base64 encoding lets us round-trip them safely."""
    tex = (
        r"\begin{description}" "\n"
        r"\item[$x \in [0, 1]$] Body." "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    # The naive [^\]]+ parser stops at the FIRST `]`, so the term in
    # this edge case truncates to ``$x \in [0, 1`` — acceptable per the
    # scope decision in GH #19. Body picks up the remainder, which is
    # visible to the author for hand-correction.
    items = _decode_desc(out)
    assert len(items) == 1
    assert items[0][0].startswith("$x \\in [0, 1")
