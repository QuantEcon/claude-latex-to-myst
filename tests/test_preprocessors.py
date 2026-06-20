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
import _apply_enumerate_markers as enum_m
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
        r'<!--ALGORITHM name=(\S+) numbered=([01]) title=(.*?) body=([A-Za-z0-9+/=]+)-->',
        out,
        re.DOTALL,
    )
    assert m, f"no marker in output: {out!r}"
    return {
        "name": m.group(1),
        "numbered": m.group(2),
        "title": m.group(3),
        "body": base64.b64decode(m.group(4)).decode("utf-8"),
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


def test_algorithm_marker_no_caption_unnumbered_no_label():
    """algorithm2e numbers only captioned floats — an uncaptioned block is
    unnumbered, so it gets no auto-label and numbered=0 (#109)."""
    tex = (
        "\\begin{algorithm}\nbody1 \\;\n\\end{algorithm}\n"
        "\\begin{algorithm}\nbody2 \\;\n\\end{algorithm}\n"
    )
    out = alg.process_text(tex, auto_prefix="ch")
    assert re.findall(r'name=(\S+)', out) == ["NOLABEL", "NOLABEL"]
    assert re.findall(r'numbered=(\d)', out) == ["0", "0"]


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
    # GH #74: plain \cite gets intercepted ONLY when a locator is present.
    (r"\cite[p.~351]{loewenstein1971negative}",
     "[[CITE:loewenstein1971negative]]"),
    (r"\cite[see][p.~12]{key}", "[[CITE:key]]"),
    (r"\cite [p.~7]{key}",      "[[CITE:key]]"),
])
def test_natbib_rewrite_drops_locator_arg(src, want):
    """Locator args (``[p.~351]``) must not block the rewrite, and must
    be discarded (MyST has no locator-suffix syntax). GH #13 / #74."""
    assert _apply_natbib(src) == want


@pytest.mark.parametrize("src", [
    r"\cite{smith2020}",          # the common, no-locator form
    r"\cite {smith2020}",         # whitespace before the key brace
])
def test_natbib_rewrite_leaves_plain_cite_without_locator(src):
    """GH #74: plain ``\\cite{key}`` (no ``[loc]``) round-trips correctly
    through pandoc's native path → ``{cite}``, so the preprocess rewrite
    must leave it untouched. Only the locator form is intercepted."""
    assert _apply_natbib(src) == src


def test_natbib_rewrite_cite_locator_does_not_hijack_citep():
    """Regression guard: the new ``\\cite[loc]`` rule must not steal a
    ``\\citep[loc]`` — ``\\cite\\b`` has no word boundary before the
    ``p``, so ``\\citep`` still decodes to CITEP, not CITE (GH #74)."""
    assert _apply_natbib(r"\citep[p.~1]{key}") == "[[CITEP:key]]"
    assert _apply_natbib(r"\citet[p.~1]{key}") == r"\citet[p.~1]{key}"


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


# ── Orphaned \pageref clause strip (issue #158A) ─────────────────────────────


@pytest.mark.parametrize("src,want", [
    # Inline "on page" companion — the \cref stays, the locator + trailing
    # punctuation collapse to just the punctuation.
    (r"from \cref{l:exgre} on page~\pageref{l:exgre}.",
     r"from \cref{l:exgre}."),
    # Comma-led: the comma before "on" goes with the clause.
    (r"in \cref{t:fintroop}, on page~\pageref{eq:fintroie}.",
     r"in \cref{t:fintroop}."),
    # LaTeX line-wrap between "on" and "page".
    ("applying \\cref{l:snms} on\n    page~\\pageref{l:snms}, the rest",
     r"applying \cref{l:snms}, the rest"),
    # "from page" lead-in.
    (r"properties from page~\pageref{enum:b13}. Let",
     r"properties. Let"),
    # Abbreviated "on p.~".
    (r"using \eqref{eq:adjrules} on p.~\pageref{eq:adjrules} to obtain",
     r"using \eqref{eq:adjrules} to obtain"),
    # Stray closing paren after the clause is preserved.
    (r"See \cref{l:fo} on page~\pageref{l:fo}) for details.",
     r"See \cref{l:fo}) for details."),
])
def test_pageref_inline_clause_stripped(src, want):
    assert rew.strip_orphan_pagerefs(src) == want


@pytest.mark.parametrize("src,want", [
    # Parenthetical-only locator — the whole "(page~…)" with its leading
    # space goes, leaving the sentence punctuation.
    (r"fixed point theorem (page~\pageref{t:bfpt}), the ADP",
     r"fixed point theorem, the ADP"),
    (r"Neumann series lemma (page~\pageref{t:nslbs}). See also",
     r"Neumann series lemma. See also"),
    # "(see p.~…)" filler word inside the paren.
    (r"measure theory (see p.~\pageref{l:scheffe}). Standard",
     r"measure theory. Standard"),
    (r"partial order (see page~\pageref{eq:cpor}).",
     r"partial order."),
])
def test_pageref_parenthetical_clause_stripped(src, want):
    assert rew.strip_orphan_pagerefs(src) == want


def test_pageref_paren_wrapping_more_keeps_inner_ref():
    """A parenthetical that wraps a \\cref plus the page locator keeps the
    \\cref — only the inner ``on page~\\pageref`` clause is stripped."""
    src = r"(see, in particular, \cref{c:ibnl} on page~\pageref{c:ibnl}), the map"
    assert rew.strip_orphan_pagerefs(src) == r"(see, in particular, \cref{c:ibnl}), the map"


def test_pageref_bare_loadbearing_not_touched():
    """A bare ``page~\\pageref`` with no locator preposition and no
    surrounding parens is left alone — without an ``on``/``from`` lead-in
    we can't tell a redundant locator from load-bearing prose."""
    src = r"Equation \eqref{X}, page~\pageref{Y}, shows the bound."
    assert rew.strip_orphan_pagerefs(src) == src


# ── \paragraph run-in headings (issue #160B) ─────────────────────────────────


def test_paragraph_rewritten_to_bold_runin():
    """``\\paragraph{Title.}`` becomes ``\\textbf{Title.}`` so it never
    enters the heading numbering tree as a deep ##### heading."""
    src = "\\paragraph{Connection to the production chain.}\n\nBody."
    out = rew.convert_paragraph_runins(src)
    assert out == "\\textbf{Connection to the production chain.}\n\nBody."


def test_subparagraph_also_rewritten():
    assert rew.convert_paragraph_runins(r"\subparagraph{Deeper.}") == r"\textbf{Deeper.}"


def test_paragraph_with_nested_braces_balanced():
    """The title may carry nested braces / math — balanced matching keeps
    the whole title."""
    src = r"\paragraph{The $\mathcal{Q}$ operator}"
    assert rew.convert_paragraph_runins(src) == r"\textbf{The $\mathcal{Q}$ operator}"


def test_paragraph_optional_short_title_dropped():
    src = r"\paragraph[Conn.]{Connection to the production chain.}"
    assert rew.convert_paragraph_runins(src) == r"\textbf{Connection to the production chain.}"


def test_paragraph_runin_noop_without_paragraph():
    src = r"Plain \textbf{already bold} text."
    assert rew.convert_paragraph_runins(src) == src


@pytest.mark.parametrize("src", [
    # immediate label (dl's \paragraph{…}\label{sec:matern})
    r"\paragraph{The Matérn kernel family.}\label{sec:matern}  body",
    # space before the label
    r"\paragraph{Kernel.} \label{sec:k} body",
    # single newline before the label (still the paragraph's label)
    "\\paragraph{Kernel.}\n\\label{sec:k} body",
    # the %-line-join idiom: title-EOL comment then label (Copilot #165)
    "\\paragraph{Kernel.}%\n\\label{sec:k} body",
    # a comment-only line between the title and the label
    "\\paragraph{Kernel.}\n% set the label\n\\label{sec:k} body",
])
def test_paragraph_with_label_kept_as_heading(src):
    """#160B follow-up: a labelled \\paragraph keeps its heading form so the
    \\label survives as a (name)= anchor — converting it to a bold run-in
    drops the anchor and breaks every cross-ref to it (dl sec-matern /
    sec-irbc went unresolved in a fixture pass)."""
    out = rew.convert_paragraph_runins(src)
    assert out == src                 # left verbatim → pandoc renders a heading
    assert r"\textbf" not in out


def test_paragraph_with_label_after_blank_line_still_bolded():
    """A \\label separated from the \\paragraph by a blank line belongs to a
    later construct (e.g. an equation), not the paragraph — so the paragraph
    is still a run-in and the conversion fires."""
    src = "\\paragraph{Foo.}\n\nBody.\n\n\\label{eq:x}"
    out = rew.convert_paragraph_runins(src)
    assert out.startswith(r"\textbf{Foo.}")
    assert r"\label{eq:x}" in out      # the equation's label is untouched


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


def test_description_commented_item_not_resurrected():
    """#138: a %-commented \\item[Term] must not become a live DESCITEM —
    pre-fix the commented-out term was published in the rendered
    definition list. The commented line rides inside the preceding
    item's body, where pandoc drops the % comment."""
    tex = (
        "\\begin{description}\n"
        "\\item[Alpha] First term.\n"
        "% \\item[Beta] Commented term.\n"
        "\\item[Gamma] Third term.\n"
        "\\end{description}\n"
    )
    out = desc.process_text(tex)
    items = _decode_desc(out)
    assert [t for t, _ in items] == ["Alpha", "Gamma"]
    # The commented line stays inside Alpha's body for pandoc to drop.
    assert "% \\item[Beta] Commented term." in items[0][1]


def test_description_commented_nest_tokens_do_not_corrupt_depth():
    """#138: commented \\begin{itemize}/\\end{itemize} lines are not
    depth events — pre-fix a commented opener left depth elevated and
    swallowed every later real \\item into the preceding body."""
    tex = (
        "\\begin{description}\n"
        "\\item[Alpha] First term.\n"
        "% \\begin{itemize}\n"
        "\\item[Beta] Second term.\n"
        "\\end{description}\n"
    )
    out = desc.process_text(tex)
    items = _decode_desc(out)
    assert [t for t, _ in items] == ["Alpha", "Beta"]


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


def test_warn_package_unknown_arg_flagged_for_manual_fill(tmp_path):
    """An unknown ``\\ding`` number — no default glyph in the registry —
    must still be reported so the author can pick a replacement, but
    NOT auto-suggested (we don't want to invent glyph mappings)."""
    text = r"Special: \ding{999}."
    found = wdtm.find_package_macro_usages(text)
    assert found["ding"]["arg_counts"]["999"] == 1
    msg = wdtm.format_package_warning(
        wdtm.scan_package_macros(
            _files_with_content(tmp_path, text)
        )
    )
    assert "999" in msg
    assert "no default" in msg


def test_warn_package_zero_arg_replacement_suggested(tmp_path):
    """``\\checkmark`` (from ``amssymb``) is a zero-arg macro with a
    fixed unicode equivalent — registry provides the replacement
    directly. The suggested rewrite pattern uses the same trailing
    negative-lookahead as the detector so every counted occurrence
    is covered (see ``_package_bare_pattern``)."""
    text = r"All good \checkmark here."
    found = wdtm.find_package_macro_usages(text)
    assert found["checkmark"]["count"] == 1
    assert found["checkmark"]["arg_counts"] is None
    usage = wdtm.scan_package_macros(_files_with_content(tmp_path, text))
    msg = wdtm.format_package_warning(usage)
    assert r"\\checkmark(?![A-Za-z@])" in msg
    assert "✓" in msg


def test_warn_package_macro_word_boundary():
    """``\\ding`` must not match ``\\dingbat`` (or any longer macro name
    with the same prefix). Regex uses a trailing ``(?![A-Za-z@])``
    negative lookahead."""
    text = r"\dingbat{x} should not flag, but \ding{51} should."
    found = wdtm.find_package_macro_usages(text)
    assert found["ding"]["count"] == 1
    assert found["ding"]["arg_counts"]["51"] == 1


def test_warn_package_no_usage_is_quiet(tmp_path):
    text = "Plain prose."
    assert wdtm.find_package_macro_usages(text) == {}
    assert wdtm.format_package_warning(
        wdtm.scan_package_macros(_files_with_content(tmp_path, text))
    ) == ""


def test_warn_package_warning_contains_paste_ready_rewrite(tmp_path):
    """Smoke test: the warning text contains paste-ready
    ``preprocess.rewrites`` entries with the correct regex shape."""
    usage = wdtm.scan_package_macros(_files_with_content(
        tmp_path, r"\ding{51} and \ding{55}."
    ))
    msg = wdtm.format_package_warning(usage)
    # The rewrite shape matches what `_apply_rewrites.py` consumes.
    assert r"\\ding\{51\}" in msg
    assert r"\\ding\{55\}" in msg
    assert "preprocess.rewrites" in msg


def _files_with_content(tmp_path, text: str):
    """Helper: stash ``text`` into a temp ``.tex`` file under pytest's
    ``tmp_path`` fixture (auto-cleaned at end of test) and return the
    path list ``scan_package_macros`` expects."""
    ch = tmp_path / "ch.tex"
    ch.write_text(text, encoding="utf-8")
    return [ch]


# ── Auto-apply known pifont glyphs (issue #159) ──────────────────────────────


def test_apply_known_glyphs_rewrites_ding_checkmarks():
    """GH #159 — the unambiguous ``\\ding{N}`` glyphs are auto-applied
    pre-pandoc (a dropped ``\\ding{51}`` leaves a blank table cell)."""
    out = wdtm.apply_known_glyphs(r"Hit \ding{51} miss \ding{55}.")
    assert out == "Hit ✓ miss ✗."


def test_apply_known_glyphs_circled_step_numbers():
    """``\\ding{172}``–``{181}`` → ①–⑩, ``{182}``–``{191}`` → ❶–❿ (the FDP
    diagram's circled step numbers, book-dp2#155)."""
    out = wdtm.apply_known_glyphs(r"\ding{172}\ding{173} then \ding{182}.")
    assert out == "①② then ❶."


def test_apply_known_glyphs_leaves_unmapped_and_argless_untouched():
    """An unknown ``\\ding`` number, ``\\faIcon`` (empty glyph table) and
    arg-less macros are left for the warn path — we don't invent glyphs."""
    src = r"Pick \ding{999} and \faIcon{rocket} and \checkmark."
    assert wdtm.apply_known_glyphs(src) == src


def test_apply_known_glyphs_then_warn_surfaces_only_leftovers(tmp_path):
    """After auto-apply, the warn scan (which runs later on the same tmp
    file) only reports the args with no registered glyph."""
    applied = wdtm.apply_known_glyphs(r"\ding{51} known, \ding{999} unknown.")
    usage = wdtm.scan_package_macros(_files_with_content(tmp_path, applied))
    msg = wdtm.format_package_warning(usage)
    assert "999" in msg
    assert "51" not in msg  # the mapped one was already substituted


# ── Enumerate exercise markers (issue #69) ───────────────────────────────────


def test_enum_marker_rewrites_fully_labelled_exercise_list():
    """GH #69 — an ``enumerate`` whose every ``\\item`` has an
    ``\\label{ex:...}`` becomes a sequence of EXERCISE marker pairs.
    The enumerate wrapper is dissolved; the resolver later decodes
    each pair into a ``{exercise}`` directive."""
    tex = (
        "Before the exercises.\n"
        "\\begin{enumerate}[itemsep=4pt]\n"
        "\\item\\label{ex:ch1:1} \\textbf{[Core] Backprop.} body 1\n"
        "\\item\\label{ex:ch1:2} \\textbf{[Core] MSE.} body 2\n"
        "\\end{enumerate}\n"
        "After.\n"
    )
    out = enum_m.process_text(tex)
    # The enumerate wrapper is gone.
    assert "\\begin{enumerate}" not in out
    assert "\\end{enumerate}" not in out
    # No surviving \item / \label{ex:...} — both consumed into markers.
    assert "\\item" not in out
    assert "\\label{ex:" not in out
    # Each labelled item carries its own marker pair with the
    # colon-converted label.
    assert "<!--EXERCISE-START label=ex-ch1-1-->" in out
    assert "<!--EXERCISE-START label=ex-ch1-2-->" in out
    assert out.count("<!--EXERCISE-END-->") == 2
    # Item bodies survive verbatim (raw LaTeX — pandoc converts later).
    assert "\\textbf{[Core] Backprop.} body 1" in out
    assert "\\textbf{[Core] MSE.} body 2" in out


def test_enum_marker_skips_mixed_list_some_unlabelled():
    """Conservative trigger: if ANY ``\\item`` in the enumerate lacks
    an ``ex:`` label, the whole block is left for pandoc to render
    as a normal bullet list. Mixing exercise directives with bullet
    items in one rendered block would be incoherent."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:ch1:1} labelled item\n"
        "\\item bare bullet, no label\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    assert out == tex


def test_enum_marker_skips_non_ex_label_prefix():
    """Conservative trigger: a ``\\label{step:1}`` etc. is not an
    exercise label and should not be promoted to an ``{exercise}``
    directive. Only ``ex:``-prefixed labels qualify."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{step:1} first step\n"
        "\\item\\label{step:2} second step\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    assert out == tex


def test_enum_marker_idempotent_noop_on_no_enumerate():
    """No ``\\begin{enumerate}`` in source → no-op."""
    tex = "Plain prose with no list.\n"
    assert enum_m.process_text(tex) == tex


def test_enum_marker_skips_commented_block():
    """A whole-line-commented enumerate must not be rewritten — the
    START marker would survive on a comment line but the END marker
    would land on a fresh uncommented line and leak the literal
    ``<!--EXERCISE-END-->`` into the output (same defensive shape as
    the listing-marker comment guard, lesson 014 Gap A)."""
    tex = (
        "% \\begin{enumerate}\n"
        "% \\item\\label{ex:x} commented\n"
        "% \\end{enumerate}\n"
    )
    assert enum_m.process_text(tex) == tex


def test_enum_parse_returns_label_content_pairs():
    """Direct unit test for the parse helper: a fully-labelled body
    yields per-item ``(label, content)`` tuples; the original LaTeX
    ``\\label{...}`` is stripped from each content (it was captured
    by the label slot)."""
    body = (
        "\n"
        "\\item\\label{ex:a} foo body\n"
        "\\item\\label{ex:b} bar body\n"
    )
    items = enum_m.parse_enum_items(body)
    assert items == [("ex:a", "foo body"), ("ex:b", "bar body")]


def test_enum_marker_handles_multiline_item_body():
    """Item bodies can span multiple physical lines (long exercises
    routinely do). The marker payload must preserve the newlines so
    pandoc later sees the correct paragraph structure inside the
    item."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:multi} First paragraph of the item.\n"
        "\n"
        "Second paragraph still inside the same item.\n"
        "\\item\\label{ex:next} A simpler item.\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    # The multi-line item body sits between its own marker pair.
    assert (
        "<!--EXERCISE-START label=ex-multi-->\n"
        "First paragraph of the item.\n"
        "\n"
        "Second paragraph still inside the same item.\n"
        "<!--EXERCISE-END-->"
    ) in out


def test_enum_marker_preserves_nested_itemize_in_exercise():
    """GH #69 regression — an exercise statement that contains a nested
    ``itemize`` must still be rewritten. The nested ``\\item`` tokens are
    unlabelled, but they're depth-1: they belong to the inner list and
    ride along inside their parent exercise's body, so they must NOT
    disqualify the block. (A flat ``\\item`` scan counted them and left
    the whole block to pandoc, dropping the ``ex:`` labels — the very bug
    #69 set out to fix.)"""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:ch1:1} Consider the following cases:\n"
        "  \\begin{itemize}\n"
        "  \\item first sub-point\n"
        "  \\item second sub-point\n"
        "  \\end{itemize}\n"
        "\\item\\label{ex:ch1:2} A simpler exercise.\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    # Two top-level exercises → two marker pairs.
    assert out.count("<!--EXERCISE-START label=ex-ch1-1-->") == 1
    assert out.count("<!--EXERCISE-START label=ex-ch1-2-->") == 1
    assert out.count("<!--EXERCISE-END-->") == 2
    # The nested itemize travels intact inside the first exercise body.
    assert "\\begin{itemize}" in out
    assert "\\item first sub-point" in out
    assert "\\item second sub-point" in out
    # The outer enumerate wrapper is gone.
    assert "\\begin{enumerate}" not in out


def test_enum_marker_preserves_nested_enumerate_subparts():
    """GH #69 regression — a multi-part exercise whose sub-parts are a
    nested ``enumerate`` (``(a)/(b)``). Two hazards at once: a flat scan
    counts the nested ``\\item`` (depth must gate them out), and a
    non-greedy ``\\begin..\\end`` regex stops at the inner
    ``\\end{enumerate}`` (block pairing must balance by depth)."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:ch2:1} Prove each of the following:\n"
        "  \\begin{enumerate}\n"
        "  \\item part a\n"
        "  \\item part b\n"
        "  \\end{enumerate}\n"
        "\\item\\label{ex:ch2:2} Second exercise.\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    assert out.count("<!--EXERCISE-START label=ex-ch2-1-->") == 1
    assert out.count("<!--EXERCISE-START label=ex-ch2-2-->") == 1
    assert out.count("<!--EXERCISE-END-->") == 2
    # The inner enumerate (with its own unlabelled items) survives inside
    # the first exercise's body, not lifted to a top-level exercise.
    assert "\\begin{enumerate}" in out
    assert "\\end{enumerate}" in out
    assert "\\item part a" in out
    assert "\\item part b" in out


def test_enum_parse_ignores_nested_item_boundaries():
    """Direct unit test for the depth-aware parse: only the two
    depth-0 ``\\item`` tokens are exercise boundaries; the nested
    ``itemize`` items stay inside the first exercise's content."""
    body = (
        "\n"
        "\\item\\label{ex:a} stem a\n"
        "\\begin{itemize}\n"
        "\\item nested 1\n"
        "\\item nested 2\n"
        "\\end{itemize}\n"
        "\\item\\label{ex:b} stem b\n"
    )
    items = enum_m.parse_enum_items(body)
    assert items is not None
    assert len(items) == 2
    assert items[0][0] == "ex:a" and items[1][0] == "ex:b"
    assert items[0][1].count("\\item nested") == 2
    assert "\\begin{itemize}" in items[0][1]


def test_enum_marker_commented_exercise_not_resurrected():
    """#138: a %-commented ``\\item\\label{ex:..}`` must not become a
    live {exercise} directive — pre-fix the commented-out exercise was
    published AND shifted the numbering of every exercise after it.
    The commented line rides inside the preceding exercise's content,
    where pandoc drops the % comment."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:ch1:1} Real exercise one.\n"
        "% \\item\\label{ex:ch1:2} Commented-out exercise.\n"
        "\\item\\label{ex:ch1:3} Real exercise two.\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    assert out.count("EXERCISE-START") == 2
    assert "label=ex-ch1-1" in out
    assert "label=ex-ch1-3" in out
    assert "label=ex-ch1-2" not in out
    # The commented line survives inside exercise one's content.
    assert "% \\item\\label{ex:ch1:2} Commented-out exercise." in out


def test_enum_marker_commented_nest_opener_does_not_disqualify():
    """#138: a commented ``% \\begin{itemize}`` is not a depth event —
    pre-fix it left the depth elevated, so the following real \\item
    wasn't seen as a boundary and the whole block was disqualified
    (silent exercise-label loss)."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:a} stem a\n"
        "% \\begin{itemize}\n"
        "\\item\\label{ex:b} stem b\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    assert out.count("EXERCISE-START") == 2
    assert "label=ex-a" in out and "label=ex-b" in out


def test_enum_marker_commented_end_does_not_close_block_early():
    """#138: a commented ``% \\end{enumerate}`` inside the block must not
    terminate it — pre-fix the block-pairing scan closed at the comment,
    truncating the block and leaking the tail."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:a} stem a\n"
        "% \\end{enumerate}\n"
        "\\item\\label{ex:b} stem b\n"
        "\\end{enumerate}\n"
    )
    out = enum_m.process_text(tex)
    assert out.count("EXERCISE-START") == 2
    assert "label=ex-a" in out and "label=ex-b" in out
    # Wrapper fully dissolved: only the COMMENTED \end{enumerate} remains
    # (inside ex:a's content, where pandoc drops it).
    assert not re.search(r"^\\end\{enumerate\}", out, re.MULTILINE)
    assert "% \\end{enumerate}" in out


# ── Declaration font forms + texttt brace flattening (#107 gap1, #105) ─────────


def test_declaration_form_sc_to_textsc():
    assert rew.normalize_declaration_forms(r'{\sc iid}') == r'\textsc{iid}'


def test_declaration_form_all_five():
    src = r'{\sc a} {\sf b} {\bf c} {\it d} {\tt e}'
    out = rew.normalize_declaration_forms(src)
    assert out == r'\textsc{a} \textsf{b} \textbf{c} \textit{d} \texttt{e}'


def test_declaration_form_nested_braces_balanced():
    assert rew.normalize_declaration_forms(r'{\sc a \textbf{b} c}') == r'\textsc{a \textbf{b} c}'


def test_declaration_form_leaves_real_commands():
    """``{\\section}`` is a brace-wrapped command, not a declaration."""
    src = r'before {\section} after'
    assert rew.normalize_declaration_forms(src) == src


def test_texttt_flattens_at_brace_group():
    assert rew.flatten_texttt_brace_groups(r'\texttt{{@}tf.function}') == r'\texttt{@tf.function}'


def test_texttt_preserves_command_argument():
    """A real command arg inside texttt (``\\textbf{keep}``) must NOT flatten."""
    assert rew.flatten_texttt_brace_groups(r'\texttt{\textbf{keep}}') == r'\texttt{\textbf{keep}}'


def test_texttt_preserves_command_argument_with_whitespace():
    """Valid LaTeX puts whitespace between a command and its argument
    (``\\textbf {keep}``); that brace group is still a command argument and
    must NOT be flattened (Copilot review)."""
    assert (rew.flatten_texttt_brace_groups(r'\texttt{\textbf {keep}}')
            == r'\texttt{\textbf {keep}}')


def test_texttt_preserves_nested_math_command_argument():
    src = r'\texttt{\textbf{$\mathcal{Q}$ x}}'
    assert rew.flatten_texttt_brace_groups(src) == src


def test_texttt_plain_arg_unchanged():
    assert rew.flatten_texttt_brace_groups(r'\texttt{@plain}') == r'\texttt{@plain}'


# ── multicols column-count strip (#111) ────────────────────────────────────────
# Moved out of _apply_rewrites into transforms.multicols (#170) so a single
# pass owns all multicols handling (grid extraction + count strip).


def _strip_multicols(text: str) -> str:
    from transforms.multicols import strip_remaining_multicols_args
    return strip_remaining_multicols_args(text)


def test_multicols_count_argument_stripped():
    assert _strip_multicols(r"\begin{multicols}{2}") == r"\begin{multicols}"


def test_multicols_star_pretext_hoisted_above_env():
    """The optional ``[pre-text]`` is real spanning content. It can't be left
    in the optional-arg slot — pandoc silently drops an optional arg on the
    count-less env (verified; worse than the pre-fix garbled leak). Hoist it
    out as a paragraph above the env, matching multicols' own semantics
    (full-width text printed before the columns)."""
    out = _strip_multicols(r"\begin{multicols*}{3}[Intro text]")
    assert out == "Intro text\n\n\\begin{multicols*}"


def test_multicols_count_strip_keeps_following_content():
    src = "\\begin{multicols}{2}\n\\item a\n"
    assert _strip_multicols(src) == "\\begin{multicols}\n\\item a\n"


def test_multicols_empty_pretext_dropped():
    assert _strip_multicols(r"\begin{multicols}{2}[ ]") == r"\begin{multicols}"


# ── multicols paired enumerate → MyST grid (#170) ──────────────────────────────


_PAIRED = (
    "\\begin{multicols}{2}\n"
    "\\begin{enumerate}\n"
    "\\item[(a)] $\\| u \\| \\geq 0$\n"
    "\\item[(b)] $\\| u \\| = 0$\n"
    "\\item[] (nonnegativity)\n"
    "\\item[] (positive definiteness)\n"
    "\\end{enumerate}\n"
    "\\end{multicols}\n"
)


def test_multicols_grid_parse_paired_enumerate():
    from transforms.multicols import find_multicols_blocks, parse_multicols_block
    blocks = find_multicols_blocks(_PAIRED)
    assert len(blocks) == 1
    _start, _end, cols, body = blocks[0]
    assert cols == 2
    spec, cells = parse_multicols_block(cols, body)
    assert spec.columns == 2
    assert spec.head_labels == []
    assert cells == [
        "(a) $\\| u \\| \\geq 0$",
        "(b) $\\| u \\| = 0$",
        "(nonnegativity)",
        "(positive definiteness)",
    ]


def test_multicols_grid_bails_on_wrapped_tabular():
    """A multicols wrapping a tabular (not a custom-label enumerate) is not
    modelled — leave it to the count-strip + ENV_SKIP path."""
    from transforms.multicols import parse_multicols_block
    body = "\n\\begin{tabular}{cc}\na & b \\\\\n\\end{tabular}\n"
    assert parse_multicols_block(2, body) is None


def test_multicols_grid_bails_on_extra_content_around_enumerate():
    from transforms.multicols import parse_multicols_block
    body = (
        "Some spanning prose.\n"
        "\\begin{enumerate}\n\\item[(a)] x\n\\item[] y\n\\end{enumerate}\n"
    )
    assert parse_multicols_block(2, body) is None


def test_multicols_grid_tolerates_inert_setlength_and_comments():
    """\\setlength + full-line AND trailing comments around the enumerate are
    inert — they must not bail the grid extraction (Copilot review on #173)."""
    from transforms.multicols import parse_multicols_block
    body = (
        "% spanning note\n"
        "\\setlength{\\columnsep}{2em} % tweak\n"
        "\\begin{enumerate}\n\\item[(a)] x\n\\item[] y\n\\end{enumerate}\n"
        "% trailing note\n"
    )
    result = parse_multicols_block(2, body)
    assert result is not None
    spec, cells = result
    assert cells == ["(a) x", "y"]


def test_multicols_grid_bails_on_nested_multicols():
    from transforms.multicols import parse_multicols_block
    body = (
        "\\begin{multicols}{2}\n\\begin{enumerate}\n\\item[(a)] x\n"
        "\\end{enumerate}\n\\end{multicols}\n"
    )
    assert parse_multicols_block(2, body) is None


def test_multicols_grid_bails_on_auto_counter_list():
    """An item without an explicit [label] is an auto-counter list — bail."""
    from transforms.multicols import parse_multicols_block
    body = "\\begin{enumerate}\n\\item a\n\\item b\n\\end{enumerate}\n"
    assert parse_multicols_block(2, body) is None


def test_multicols_grid_split_columns_balances_column_first():
    from transforms.multicols import _split_columns
    assert _split_columns(list("abcdefgh"), 2) == [list("abcd"), list("efgh")]
    # Odd remainder rides in the earlier columns (multicols balancing).
    assert _split_columns(list("abcde"), 2) == [list("abc"), list("de")]
    assert _split_columns(list("abcdefg"), 3) == [list("abc"), list("de"), list("fg")]


def test_multicols_grid_resolver_emits_grid():
    from transforms.multicols import MulticolsSpec, encode_marker, resolve_multicols_grid
    spec = MulticolsSpec(
        columns=2,
        items=["(a) x", "(b) y", "(nonnegativity)", "(positive definiteness)"],
    )
    out = resolve_multicols_grid(f"pre\n\n{encode_marker(spec)}\n\npost")
    assert "::::{grid} 1 1 2 2" in out
    assert out.count(":::{grid-item}") == 2
    # column-first split: statements in cell 1, names in cell 2
    first = out.index("(a) x")
    second = out.index("(nonnegativity)")
    mid = out.index(":::{grid-item}", out.index(":::{grid-item}") + 1)
    assert first < mid < second


def test_multicols_grid_preprocessor_emits_marker():
    """End-to-end (needs pandoc): the preprocessor replaces the paired block
    with a MULTICOLSGRID marker and leaves the rest."""
    import _apply_multicols_grid as mg
    out = mg.process_text(_PAIRED)
    assert "<!--MULTICOLSGRID payload=" in out
    assert "\\begin{multicols}" not in out  # the whole block is consumed


def test_multicols_grid_preprocessor_strips_nongrid_count():
    """A non-grid multicols (wrapped tabular) keeps the #111 behaviour: count
    stripped, block left for ENV_SKIP."""
    import _apply_multicols_grid as mg
    src = "\\begin{multicols}{2}\n\\begin{tabular}{c}\na\n\\end{tabular}\n\\end{multicols}\n"
    out = mg.process_text(src)
    assert "<!--MULTICOLSGRID" not in out
    assert "\\begin{multicols}{2}" not in out
    assert "\\begin{multicols}" in out


# ── Custom-label enumerate flattening (#111) ───────────────────────────────────

import _apply_custom_label_enumerates as clbl


def test_custom_label_enumerate_flattened_to_labelled_paragraphs():
    """dp1's norm-properties shape: every \\item carries an explicit
    [label] (some empty) → labelled paragraphs, not an auto-counter
    list pandoc would renumber 1..N."""
    tex = (
        "\\begin{enumerate}\n"
        "    \\item[(a)] $\\| u \\| \\geq 0$\n"
        "    \\item[(b)] $\\| u \\| = 0 \\iff u=0$\n"
        "    \\item[] (nonnegativity)\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    assert "\\begin{enumerate}" not in out
    assert "\\item" not in out
    assert "(a) $\\| u \\| \\geq 0$" in out
    assert "(b) $\\| u \\| = 0 \\iff u=0$" in out
    # Empty label → bare content paragraph (no leading space).
    assert "\n(nonnegativity)" in out


def test_custom_label_enumerate_bails_on_mixed_items():
    """One auto-counter \\item disqualifies the block — it IS an
    ordered list; pandoc handles it."""
    tex = (
        "\\begin{enumerate}\n"
        "    \\item[(a)] labelled\n"
        "    \\item unlabelled\n"
        "\\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_bails_on_plain_list():
    tex = (
        "\\begin{enumerate}\n"
        "    \\item first\n"
        "    \\item second\n"
        "\\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_bails_on_nested_list():
    """A nested list env inside the body is not modelled — bail."""
    tex = (
        "\\begin{enumerate}\n"
        "    \\item[(a)] outer\n"
        "    \\begin{itemize}\n"
        "        \\item inner\n"
        "    \\end{itemize}\n"
        "    \\item[(b)] more\n"
        "\\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_skips_commented_block():
    tex = (
        "% \\begin{enumerate}\n"
        "%     \\item[(a)] commented out\n"
        "% \\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_leaves_exercise_enumerates_alone():
    """The #69 exercise shape (\\item\\label{ex:..}, no [label]) must
    pass through untouched for ``_apply_enumerate_markers``."""
    tex = (
        "\\begin{enumerate}\n"
        "\\item\\label{ex:ch1:1} Derive the gradient.\n"
        "\\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_commented_item_not_uncommented():
    """A %-commented \\item inside the body is not a boundary (Copilot
    review on #136) — it must not be emitted as a live paragraph. The
    commented line rides inside the preceding item's content, where
    pandoc drops the % comment."""
    tex = (
        "\\begin{enumerate}\n"
        "    \\item[(a)] real item\n"
        "    % \\item[(b)] commented out\n"
        "    \\item[(c)] another real item\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    assert "\\begin{enumerate}" not in out
    assert "(a) real item" in out
    assert "(c) another real item" in out
    # The commented item is NOT a top-level paragraph; it stays behind
    # its % marker inside (a)'s content for pandoc to drop.
    assert "\n(b) commented out" not in out
    assert "% \\item[(b)] commented out" in out


def test_custom_label_enumerate_only_commented_items_bails():
    tex = (
        "\\begin{enumerate}\n"
        "    % \\item[(a)] all commented\n"
        "\\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_commented_nest_does_not_bail():
    """#138: a commented ``% \\begin{itemize}`` is not a real nested
    list — it must not trigger the nested-env bail."""
    tex = (
        "\\begin{enumerate}\n"
        "    \\item[(a)] first\n"
        "    % \\begin{itemize}\n"
        "    \\item[(b)] second\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    assert "\\begin{enumerate}" not in out
    assert "(a) first" in out
    assert "(b) second" in out


def test_custom_label_enumerate_commented_end_does_not_close_early():
    """#138: a commented ``% \\end{enumerate}`` must not terminate the
    block-pairing scan early."""
    tex = (
        "\\begin{enumerate}\n"
        "    \\item[(a)] first\n"
        "    % \\end{enumerate}\n"
        "    \\item[(b)] second\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    # Only the COMMENTED \end{enumerate} remains (inside (a)'s content,
    # where pandoc drops it); the real wrapper is dissolved.
    assert not re.search(r"^\s*\\end\{enumerate\}", out, re.MULTILINE)
    assert "(a) first" in out
    assert "(b) second" in out


def test_custom_label_enumerate_bails_on_content_before_first_item():
    tex = (
        "\\begin{enumerate}\n"
        "stray prose\n"
        "    \\item[(a)] item\n"
        "\\end{enumerate}\n"
    )
    assert clbl.process_text(tex) == tex


def test_custom_label_enumerate_leading_label_does_not_bail(tmp_path):
    """#157A: ``\\begin{enumerate}\\label{enum:b13}`` must still flatten —
    the leading ``\\label`` is a no-output token, not real content. The
    custom labels (B1)/(B3) survive instead of being clobbered to
    (i),(ii),(iii) by the downstream enumerate_style restyle."""
    tex = (
        "\\begin{enumerate}\\label{enum:b13}\n"
        "    \\item[(B1)] first property\n"
        "    \\item[(B3)] third property\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    assert "\\begin{enumerate}" not in out
    assert "(B1) first property" in out
    assert "(B3) third property" in out
    # The list anchor is hoisted to its own line so it becomes a
    # ``(enum-b13)=`` target post-pandoc (cross-refs keep resolving).
    assert "\\label{enum:b13}\n\n(B1) first property" in out


def test_custom_label_enumerate_leading_setlength_and_label_skipped():
    """Leading no-output spacing tweaks (``\\setlength``) alongside a
    ``\\label`` are skipped without bailing."""
    tex = (
        "\\begin{enumerate}\\label{enum:x}\\setlength{\\itemsep}{0pt}\n"
        "    \\item[(a)] one\n"
        "    \\item[(b)] two\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    assert "\\begin{enumerate}" not in out
    assert "(a) one" in out and "(b) two" in out
    assert "\\label{enum:x}" in out
    assert "\\setlength" not in out  # spacing tweak dropped, not hoisted


def test_custom_label_enumerate_commented_leading_label_not_hoisted():
    """A ``%``-commented ``\\label`` before the first item is neither a
    bail trigger nor hoisted as a live anchor."""
    tex = (
        "\\begin{enumerate}\n"
        "    % \\label{enum:dead}\n"
        "    \\item[(a)] one\n"
        "\\end{enumerate}\n"
    )
    out = clbl.process_text(tex)
    assert "\\begin{enumerate}" not in out
    assert "(a) one" in out
    # The commented label is not promoted to an own-line anchor.
    assert "\n\n\\label{enum:dead}" not in out


# ── PRF title markers (#112) ───────────────────────────────────────────────────

import _apply_prf_title_markers as prft


def _apply_prf(text: str) -> str:
    return prft.apply_markers(text, prft._DEFAULT_PRF_ENVS)


def test_prf_title_theorem_optional_arg_moved_to_marker():
    src = "\\begin{theorem}[Neumann Series Lemma]\\label{t:nsl}\nBody.\n\\end{theorem}\n"
    out = _apply_prf(src)
    assert "[Neumann Series Lemma]" not in out
    assert "\\begin{theorem}\\label{t:nsl}" in out
    assert "<!--PRFTITLE-START-->Neumann Series Lemma<!--PRFTITLE-END-->" in out


def test_prf_title_proof_optional_arg_with_ref():
    src = "\\begin{proof}[Proof of Proposition~\\ref{p:js0be}]\nIt follows.\n\\end{proof}\n"
    out = _apply_prf(src)
    assert "\\begin{proof}\n" in out
    assert "<!--PRFTITLE-START-->Proof of Proposition~\\ref{p:js0be}<!--PRFTITLE-END-->" in out


def test_prf_title_no_optional_arg_is_noop():
    src = "\\begin{theorem}\\label{t:plain}\nBody.\n\\end{theorem}\n"
    assert _apply_prf(src) == src


def test_prf_title_does_not_match_bracket_in_body():
    """A ``[0,1]`` on a following line is body content, not the optional arg."""
    src = "\\begin{remark}\n$[0,1]$ is the unit interval.\n\\end{remark}\n"
    assert _apply_prf(src) == src


def test_prf_title_skips_commented_out_begin():
    """A commented-out ``% \\begin{theorem}[T]`` must be left alone — injecting
    an uncommented marker would leak it into pandoc output (same leak-prevention
    guard as the algorithm / listing preprocessors)."""
    src = "% \\begin{theorem}[Hidden]\\label{t:x}\n% body\n% \\end{theorem}\n"
    assert _apply_prf(src) == src
    assert "PRFTITLE" not in _apply_prf(src)


def test_prf_title_balanced_brackets_in_title():
    src = "\\begin{lemma}[Bound on $f[x]$ growth]\\label{l:b}\nBody.\n\\end{lemma}\n"
    out = _apply_prf(src)
    assert "<!--PRFTITLE-START-->Bound on $f[x]$ growth<!--PRFTITLE-END-->" in out
    assert "[Bound on" not in out
