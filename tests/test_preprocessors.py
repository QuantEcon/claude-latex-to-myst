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
import _apply_algorithmic_markers as algic
import _apply_chapter_splits as split
import _apply_description_markers as desc
import _apply_listing_markers as lst
import _apply_rewrites as rew
import _warn_dropped_text_macros as wdtm


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


def test_algorithm_marker_sibling_label_after_caption():
    """GH #39 — the dominant LaTeX convention places ``\\label{}`` as a
    sibling AFTER ``\\caption{}`` rather than inside it. Pre-fix the
    preprocessor only recognised the inside-caption form and fell back
    to an auto-generated label, breaking every body cross-reference."""
    tex = (
        "\\begin{algorithm}\n"
        "    body \\;\n"
        "    \\caption{Young's histogram update}\n"
        "    \\label{alg:young}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    m = _extract_marker(out)
    assert m["name"] == "alg-young"  # NOT algo-ch-auto-1
    assert m["title"] == "Young's histogram update"
    assert "\\label" not in m["body"]


def test_algorithm_marker_sibling_label_before_caption():
    """Some authors write ``\\label{}`` BEFORE the caption. Same rule:
    extract the label, strip it from the body, keep the title."""
    tex = (
        "\\begin{algorithm}\n"
        "    \\label{alg:eminn}\n"
        "    body \\;\n"
        "    \\caption{EMINN procedure}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    m = _extract_marker(out)
    assert m["name"] == "alg-eminn"
    assert m["title"] == "EMINN procedure"
    assert "\\label" not in m["body"]


def test_algorithm_marker_caption_and_label_before_body():
    """GH #43 — the dominant LaTeX convention places caption + label BEFORE the
    ``\\begin{algorithmic}`` body (mirroring how figures/tables are written).
    Pre-fix, the strict trailing-only scan early-bailed when non-whitespace
    followed the caption, dropping the label and returning an empty title."""
    tex = (
        "\\begin{algorithm}[H]\n"
        "    \\caption{Young's histogram update}\n"
        "    \\label{alg:young}\n"
        "    \\begin{algorithmic}\n"
        "    \\REQUIRE Histogram\n"
        "    \\STATE Update\n"
        "    \\end{algorithmic}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    m = _extract_marker(out)
    assert m["name"] == "alg-young"  # NOT algo-ch-auto-1
    assert m["title"] == "Young's histogram update"
    assert "\\label" not in m["body"]
    assert "\\caption" not in m["body"]
    assert "\\REQUIRE Histogram" in m["body"]
    assert "\\STATE Update" in m["body"]


def test_algorithm_marker_inside_caption_label_still_works():
    """Regression guard — the legacy inside-caption form continues
    to extract the label correctly."""
    tex = (
        "\\begin{algorithm}\n"
        "    body \\;\n"
        "    \\caption{\\label{algo:demo} Inside-caption form}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    m = _extract_marker(out)
    assert m["name"] == "algo-demo"
    assert m["title"] == "Inside-caption form"


def test_algorithm_marker_inside_caption_takes_precedence_over_sibling():
    """Vanishingly unlikely shape (both forms present), but lock the
    precedence: inside-caption wins so behaviour is deterministic."""
    tex = (
        "\\begin{algorithm}\n"
        "    body \\;\n"
        "    \\caption{\\label{algo:inner} Title}\n"
        "    \\label{alg:sibling}\n"
        "\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    m = _extract_marker(out)
    assert m["name"] == "algo-inner"


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


# ── Inline \itemsep<dim> strip (issue #28) ───────────────────────────────────


def _apply_itemsep_strip(text: str) -> str:
    return rew._ITEMSEP_STRIP.sub('', text)


def test_itemsep_attached_to_itemize_open_stripped():
    """``\\begin{itemize}\\itemsep1pt`` is the canonical form that breaks
    pandoc when nested in a description. The strip must remove the
    spacing directive while leaving the env-open intact (GH #28)."""
    src = r"\begin{itemize}\itemsep1pt"
    out = _apply_itemsep_strip(src)
    assert r"\itemsep" not in out
    assert r"\begin{itemize}" in out


@pytest.mark.parametrize("src,want", [
    (r"\begin{itemize}\itemsep1pt",      r"\begin{itemize}"),
    (r"\begin{itemize}\itemsep 3pt",     r"\begin{itemize}"),
    (r"\begin{itemize}\itemsep=2em",     r"\begin{itemize}"),
    (r"\begin{itemize}\itemsep0.5ex",    r"\begin{itemize}"),
    (r"\begin{enumerate}\itemsep1pt",    r"\begin{enumerate}"),
    (r"\itemsep1pt\\",                   ""),
])
def test_itemsep_strip_variants(src, want):
    assert _apply_itemsep_strip(src) == want


def test_itemsep_strip_does_not_touch_setlength_form():
    """``\\setlength{\\itemsep}{1pt}`` is a different shape that doesn't
    trip pandoc (no bare ``\\itemsep`` token before the dimension). Leave
    it alone — the strip should only consume the inline ``\\itemsep<dim>``
    form."""
    src = r"\setlength{\itemsep}{1pt}"
    assert _apply_itemsep_strip(src) == src


def test_itemsep_strip_full_nested_example():
    """End-to-end example mirroring GH #28's reproducer: nested itemize
    inside description, with the inline ``\\itemsep1pt`` that triggers
    pandoc's ``Unknown environment`` cascade."""
    src = (
        r"\begin{description}" "\n"
        r"\item[Hard.] Body." "\n"
        r"  \begin{itemize}\itemsep1pt" "\n"
        r"  \item nested 1" "\n"
        r"  \end{itemize}" "\n"
        r"\end{description}" "\n"
    )
    out = _apply_itemsep_strip(src)
    assert r"\itemsep" not in out
    # The env opens / closes / items must all survive.
    assert r"\begin{itemize}" in out
    assert r"\end{itemize}" in out
    assert r"\item nested 1" in out


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


def test_description_marker_preserves_nested_itemize():
    """A ``\\begin{itemize}…\\end{itemize}`` nested inside a description
    body must keep its own ``\\item`` markers — they belong to the inner
    env, not to the outer description (GH #29). The flat finditer of the
    original implementation consumed them and left the nested itemize
    with zero items, which pandoc then dropped as ``Unknown environment``
    and cascaded into MyST dropping every following figure."""
    tex = (
        r"\begin{description}" "\n"
        r"\item[Outer A.] Body of A." "\n"
        r"  \begin{itemize}" "\n"
        r"  \item nested 1" "\n"
        r"  \item nested 2" "\n"
        r"  \end{itemize}" "\n"
        r"\item[Outer B.] Body of B." "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    # Exactly the two top-level items get DESCITEM markers; the nested
    # \item markers must NOT be replaced.
    assert out.count("<!--DESCITEM term=") == 2
    items = _decode_desc(out)
    assert [t for t, _ in items] == ["Outer A.", "Outer B."]
    # The nested itemize body lives inside the first description item
    # and the inner \item markers must survive verbatim for pandoc.
    assert items[0][1].count(r"\item nested") == 2
    assert r"\begin{itemize}" in items[0][1]
    assert r"\end{itemize}" in items[0][1]


def test_description_marker_preserves_nested_enumerate():
    """Same as nested itemize, but for ``\\begin{enumerate}`` (GH #29)."""
    tex = (
        r"\begin{description}" "\n"
        r"\item[Term] Body." "\n"
        r"  \begin{enumerate}" "\n"
        r"  \item first" "\n"
        r"  \item second" "\n"
        r"  \end{enumerate}" "\n"
        r"\end{description}" "\n"
    )
    out = desc.process_text(tex)
    assert out.count("<!--DESCITEM term=") == 1
    items = _decode_desc(out)
    assert items[0][0] == "Term"
    assert items[0][1].count(r"\item first") == 1
    assert items[0][1].count(r"\item second") == 1


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


# ── Standalone algorithmic markers (issue #20) ───────────────────────────────


def _decode_algic(out: str) -> str:
    m = re.search(r'<!--ALGORITHMIC body=([A-Za-z0-9+/=]+)-->', out)
    assert m, f"no ALGORITHMIC marker: {out!r}"
    return base64.b64decode(m.group(1)).decode("utf-8")


def test_algorithmic_marker_basic():
    tex = (
        r"\begin{algorithmic}" "\n"
        r"\STATE Init" "\n"
        r"\STATE Step" "\n"
        r"\end{algorithmic}" "\n"
    )
    out = algic.process_text(tex)
    body = _decode_algic(out)
    assert "\\STATE Init" in body
    assert "\\STATE Step" in body


def test_algorithmic_marker_strips_optional_arg():
    """``\\begin{algorithmic}[1]`` is line-numbering style; no MyST analogue."""
    tex = (
        r"\begin{algorithmic}[1]" "\n"
        r"\STATE Body" "\n"
        r"\end{algorithmic}" "\n"
    )
    out = algic.process_text(tex)
    body = _decode_algic(out)
    assert "[1]" not in body
    assert "\\STATE Body" in body


def test_algorithmic_marker_skips_commented_block():
    """A ``\\begin{algorithmic}`` on a commented-out line stays as source."""
    tex = (
        "%\\begin{algorithmic}\n"
        "%\\STATE x\n"
        "%\\end{algorithmic}\n"
    )
    assert algic.process_text(tex) == tex


def test_algorithmic_marker_no_op_when_no_blocks():
    tex = "Just prose, no algorithmic envs.\n"
    assert algic.process_text(tex) == tex


def test_algorithmic_marker_leaves_algorithm_wrapped_block_alone():
    """When the standalone preprocessor runs AFTER _apply_algorithm_markers
    (the convert.sh ordering), an algorithmic block already inside a
    base64-encoded ALGORITHM marker is invisible to this scanner.
    Smoke test: nothing matches in a string that's been algorithm-encoded."""
    pre_encoded = (
        "\n\n<!--ALGORITHM name=algo-foo title=T body=YWxnb2JvZHk=-->\n\n"
        "Some prose with no algorithmic env at the top level.\n"
    )
    assert algic.process_text(pre_encoded) == pre_encoded


# ── Dropped-text-macro warning (issue #22) ───────────────────────────────────


def test_warn_declare_url_command_detected_with_suggestion():
    """GH #22 — pandoc has no handler for ``\\DeclareUrlCommand``, so
    every ``\\tpath{…}`` in the body would be dropped along with its
    argument. Always flag and suggest ``\\texttt``."""
    preamble = r"\DeclareUrlCommand\tpath{\urlstyle{tt}}"
    found = wdtm.find_custom_text_macros(preamble)
    assert found == {"tpath": r"\texttt"}


def test_warn_newcommand_textcolor_textbf_suggests_textbf():
    src = (
        r"\newcommand{\emphc}[1]{\textcolor{harvardcrimson}{\textbf{#1}}}"
    )
    found = wdtm.find_custom_text_macros(src)
    assert found == {"emphc": r"\textbf"}


def test_warn_newcommand_math_only_not_flagged():
    """A math-only macro (no ``#1`` in body, or body purely math) is
    not at risk of the silent-drop bug — pandoc passes it into math
    mode untouched. Don't waste warning noise on it."""
    src = r"\newcommand{\R}{\mathbb{R}}"
    assert wdtm.find_custom_text_macros(src) == {}
    src2 = r"\newcommand{\norm}[1]{\|#1\|}"
    assert wdtm.find_custom_text_macros(src2) == {}


def test_warn_count_usages_skips_definitions():
    """Definitions should be subtracted before counting body uses;
    otherwise a single ``\\newcommand{\\X}…`` would always self-count."""
    src = (
        r"\newcommand{\foo}[1]{\textbf{#1}}" "\n"
        r"Body uses \foo{first} and \foo{second}." "\n"
    )
    assert wdtm.count_usages(src, "foo") == 2


def test_warn_scan_end_to_end(tmp_path):
    """Wire-up smoke test: a preamble file + chapter file, scanned
    together, produce a non-empty warning block referencing the
    chapter by name."""
    src = tmp_path
    (src / "preamble.tex").write_text(
        r"\DeclareUrlCommand\tpath{\urlstyle{tt}}" + "\n",
        encoding="utf-8",
    )
    ch = src / "ch01.tex"
    ch.write_text(
        r"The notebook \tpath{lecture_03.ipynb} shows convergence." + "\n",
        encoding="utf-8",
    )
    usage = wdtm.scan(src, [ch])
    assert "tpath" in usage
    assert usage["tpath"]["count"] == 1
    assert "ch01.tex" in usage["tpath"]["files"]
    msg = wdtm.format_warning(usage)
    assert "\\tpath" in msg
    assert "preprocess.rewrites" in msg


def test_warn_scan_no_macros_is_quiet(tmp_path):
    src = tmp_path
    (src / "ch01.tex").write_text("Plain prose, no macros.\n", encoding="utf-8")
    usage = wdtm.scan(src, [src / "ch01.tex"])
    assert usage == {}
    assert wdtm.format_warning(usage) == ""


# ── Package-imported text macros (issue #50) ─────────────────────────────────


def test_warn_package_ding_detected_with_arg_glyphs():
    """GH #50 — ``\\ding{N}`` from ``pifont`` is silently dropped by
    pandoc. Detector counts per-arg usage and suggests the unicode
    glyph the project author can paste into ``preprocess.rewrites``."""
    text = (
        r"Hit \ding{51} miss \ding{55} hit \ding{51}."
    )
    found = wdtm.find_package_macro_usages(text)
    assert "ding" in found
    assert found["ding"]["count"] == 3
    assert found["ding"]["arg_counts"]["51"] == 2
    assert found["ding"]["arg_counts"]["55"] == 1


def test_warn_package_unknown_arg_flagged_for_manual_fill():
    """An unknown ``\\ding`` number — no default glyph in the registry —
    must still be reported so the author can pick a replacement, but
    NOT auto-suggested (we don't want to invent glyph mappings)."""
    text = r"Special: \ding{999}."
    found = wdtm.find_package_macro_usages(text)
    assert found["ding"]["arg_counts"]["999"] == 1
    msg = wdtm.format_package_warning(
        wdtm.scan_package_macros(
            _files_with_content(text)
        )
    )
    assert "999" in msg
    assert "no default" in msg


def test_warn_package_zero_arg_replacement_suggested():
    """``\\checkmark`` (from ``amssymb``) is a zero-arg macro with a
    fixed unicode equivalent — registry provides the replacement
    directly."""
    text = r"All good \checkmark here."
    found = wdtm.find_package_macro_usages(text)
    assert found["checkmark"]["count"] == 1
    assert found["checkmark"]["arg_counts"] is None
    usage = wdtm.scan_package_macros(_files_with_content(text))
    msg = wdtm.format_package_warning(usage)
    assert r"\\checkmark\b" in msg
    assert "✓" in msg


def test_warn_package_macro_word_boundary():
    """``\\ding`` must not match ``\\dingbat`` (or any longer macro name
    with the same prefix). Regex uses a trailing ``[^A-Za-z@]`` guard."""
    text = r"\dingbat{x} should not flag, but \ding{51} should."
    found = wdtm.find_package_macro_usages(text)
    assert found["ding"]["count"] == 1
    assert found["ding"]["arg_counts"]["51"] == 1


def test_warn_package_no_usage_is_quiet():
    text = "Plain prose."
    assert wdtm.find_package_macro_usages(text) == {}
    assert wdtm.format_package_warning(
        wdtm.scan_package_macros(_files_with_content(text))
    ) == ""


def test_warn_package_warning_contains_paste_ready_rewrite():
    """Smoke test: the warning text contains paste-ready
    ``preprocess.rewrites`` entries with the correct regex shape."""
    usage = wdtm.scan_package_macros(_files_with_content(
        r"\ding{51} and \ding{55}."
    ))
    msg = wdtm.format_package_warning(usage)
    # The rewrite shape matches what `_apply_rewrites.py` consumes.
    assert r"\\ding\{51\}" in msg
    assert r"\\ding\{55\}" in msg
    assert "preprocess.rewrites" in msg


def _files_with_content(text: str):
    """Helper: stash ``text`` into a temp ``.tex`` file and return the
    path list ``scan_package_macros`` expects. Used by package-macro
    tests above."""
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / "ch.tex"
    tmp.write_text(text, encoding="utf-8")
    return [tmp]
