#!/usr/bin/env python3
"""Apply preprocess.strip and preprocess.rewrites to a single .tex file.

Reads the config, finds the rules, applies them in place. All transforms are
Python re.sub — no sed (BSD/GNU portability traps) and no perl (extra dep).

Usage:
    _apply_rewrites.py CONFIG_PATH TEX_FILE
"""

import re
import sys
from pathlib import Path

from _config import load


# natbib variants pandoc cannot losslessly map.
#
# Pandoc handles ``\cite`` and ``\citep`` identically (both → ``[@key]``)
# and ``\citet`` / ``\citealt`` identically (both → ``@key``), losing the
# parenthetical-vs-textual / paren-vs-no-paren distinction. We rewrite
# the lossy variants to bracket-marker sentinels that survive pandoc
# unchanged; ``postprocess.convert_citations`` decodes them.
#
# Variants pandoc handles correctly (``\cite`` → ``{cite}``, ``\citet``
# → ``{cite:t}``) are left alone.
#
# Optional ``[...]`` locator arguments (natbib accepts up to two:
# ``\citep[prenote][postnote]{key}``) are matched and discarded — MyST's
# ``{cite:*}`` roles have no locator-suffix syntax to route them into.
# Without this, ``\citep[p.~351]{key}`` slipped past the rewrite, pandoc
# emitted ``[@key, p.~351]``, and downstream regex produced an empty
# ``{cite}`` role (GH #13).
# Inline ``\itemsep<dim>`` on a list/env opener confuses pandoc when the
# construct is nested inside another list (GH #28). ``\itemsep`` is a TeX
# low-level spacing command with no MyST analogue, so we strip it globally
# (the form attached to ``\begin{itemize}…`` and the form on its own line
# are both handled by the same pattern). Matches optional ``=``, a signed
# decimal dimension, any TeX length unit, and trailing whitespace / ``\\``.
_ITEMSEP_STRIP = re.compile(
    r'\\itemsep\s*=?\s*-?[0-9.]+'
    r'(?:pt|em|ex|in|cm|mm|pc|bp|dd|cc|sp)\b'
    r'(?:\s*\\\\)?\s*'
)

# ``\begin{multicols}{N}[pre-text]`` — the mandatory column-count argument
# and the optional spanning pre-text. multicols is skipped post-pandoc (the
# wrapper is dropped, content kept), but pandoc renders the ``{N}`` arg as a
# stray ``N`` paragraph at the top of the div, which then leaks into the body
# (#111). MyST has no multi-column primitive, so the count carries no meaning
# downstream — strip the ``{N}``.
#
# The optional ``[pre-text]`` is real content (multicols prints it full-width
# before the columns begin), but it CANNOT simply be left in place: pandoc
# silently drops an optional arg on the count-less env (verified — worse than
# the pre-fix garbled leak, per the lesson-028 "silent drops are the worst
# failure mode" rule). Hoist it OUT as a paragraph before the env instead,
# which matches multicols' own semantics (spanning text above the columns).
_MULTICOLS_ARGS = re.compile(
    r'(\\begin\{multicols\*?\})\s*\{[^}]*\}(?:\s*\[([^\]]*)\])?'
)


def _strip_multicols_args(m: re.Match) -> str:
    env, pretext = m.group(1), m.group(2)
    if pretext and pretext.strip():
        return f'{pretext.strip()}\n\n{env}'
    return env

_NATBIB_OPT = r'(?:\s*\[[^\]]*\]){0,2}'
# Same optional-locator shape as ``_NATBIB_OPT`` but with at least one
# ``[...]`` required (one or two) — used to gate the plain-``\cite``
# rewrite on the presence of a locator.
_NATBIB_OPT_REQUIRED = r'\s*\[[^\]]*\](?:\s*\[[^\]]*\])?'
_NATBIB_REWRITES = [
    (rf'\\citep\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}',       r'[[CITEP:\1]]'),
    (rf'\\citealp\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}',     r'[[CITEALP:\1]]'),
    (rf'\\citealt\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}',     r'[[CITEALT:\1]]'),
    (rf'\\citeauthor\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}',  r'[[CITEAUTHOR:\1]]'),
    # \citeyearpar must precede \citeyear — both share a prefix and the
    # shorter pattern would otherwise win.
    (rf'\\citeyearpar\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}', r'[[CITEYEARPAR:\1]]'),
    (rf'\\citeyear\b{_NATBIB_OPT}\s*\{{([^}}]+)\}}',    r'[[CITEYEAR:\1]]'),
    # Plain \cite{key} (no locator) round-trips correctly through pandoc
    # → {cite}, so it is left alone. Only the locator form
    # \cite[p.~351]{key} needs intercepting — pandoc emits [@key, p.~351]
    # and the downstream regex loses the key, leaving an empty {cite} role
    # (GH #74, sister of #13). ``\cite\b`` excludes \citep/\citet/etc.
    # (no word boundary before their trailing letter), and requiring a
    # leading ``[`` keeps plain \cite{key} on pandoc's native path.
    (rf'\\cite\b{_NATBIB_OPT_REQUIRED}\s*\{{([^}}]+)\}}', r'[[CITE:\1]]'),
]


# Legacy TeX *declaration* font forms (``{\sc ...}``) that pandoc drops the
# formatting from — it handles the ``\textsc{...}`` command form natively but
# silently flattens the declaration form to plain text (#107 gap 1, adjacent
# to lesson 028). ``\bf`` / ``\it`` / ``\tt`` happen to survive pandoc, but we
# normalise all five uniformly so the loss can't depend on pandoc internals.
_DECLARATION_FORMS = {
    'sc': 'textsc',
    'sf': 'textsf',
    'bf': 'textbf',
    'it': 'textit',
    'tt': 'texttt',
}


# Orphaned page references (#158A). LaTeX's ``… on page~\pageref{X}`` has no
# meaning in single-page HTML — pandoc drops the ``\pageref`` and strands the
# lead-in, leaving "on page .", "on page ,", "(page )". The companion
# ``\cref``/``\ref`` immediately before it already renders a working link, so
# the whole locator clause is redundant. Strip it pre-pandoc, while the
# ``\pageref`` token is still intact and unambiguous (post-pandoc the orphan
# "page " is much harder to tell from a real "page 5").
#
# Two shapes, stripped in this order:
#   1. parenthetical-only — ``(page~\pageref{X})`` / ``(see p.~\pageref{X})``
#      with the leading space, so "theorem (page~\pageref{X}), the" → "theorem,
#      the". A parenthetical that wraps *more* than the page ref (e.g.
#      ``(see, in particular, \cref{Y} on page~\pageref{X})``) is left for the
#      inline pass, which strips only the inner clause and keeps "(… \cref{Y})".
#   2. inline companion clause — ``[,] on page~\pageref{X}`` /
#      ``from page~\pageref{X}`` / ``on p.~\pageref{X}``. A locator preposition
#      (``on``/``from``) is required, so a bare load-bearing "page~\pageref" is
#      never touched; ``\s+`` between the preposition and ``page`` absorbs the
#      LaTeX line-wrap ``\cref{X} on\n    page~\pageref{X}``.
_PAGEREF = r'\\pageref\{[^}]*\}'
_PAGEREF_PAREN_RE = re.compile(
    r'[ \t]*\(\s*(?:see\s+|on\s+|from\s+)?(?:pages?|pp?\.)\s*[~ ]*'
    + _PAGEREF + r'\s*\)'
)
_PAGEREF_INLINE_RE = re.compile(
    r'(?:[ \t]*,)?\s+(?:on|from)\s+(?:pages?|pp?\.)\s*[~ ]*' + _PAGEREF
)


def strip_orphan_pagerefs(text: str) -> str:
    """Drop redundant ``on page~\\pageref{X}`` locator clauses (#158A)."""
    text = _PAGEREF_PAREN_RE.sub('', text)
    text = _PAGEREF_INLINE_RE.sub('', text)
    return text


def _find_matching_brace(s: str, open_idx: int) -> int:
    """``s[open_idx] == '{'`` → index of the matching ``}`` (or -1)."""
    depth = 0
    i = open_idx
    while i < len(s):
        c = s[i]
        if c == '\\':            # skip an escaped brace like ``\{``
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def normalize_declaration_forms(text: str) -> str:
    """``{\\sc iid}`` → ``\\textsc{iid}`` for the five legacy font declarations.

    Scans for ``{\\<decl> `` openers and rewrites the *balanced* group so
    nested braces in the body are preserved."""
    decl_re = re.compile(r'\{\\(' + '|'.join(_DECLARATION_FORMS) + r')(\s+|(?=[^A-Za-z]))')
    out = []
    pos = 0
    for m in decl_re.finditer(text):
        open_brace = m.start()
        close = _find_matching_brace(text, open_brace)
        if close < 0:
            continue
        cmd = _DECLARATION_FORMS[m.group(1)]
        body = text[m.end():close]
        out.append(text[pos:open_brace])
        out.append(f'\\{cmd}{{{body}}}')
        pos = close + 1
    out.append(text[pos:])
    return ''.join(out)


def _flatten_grouping_braces(arg: str) -> str:
    """Flatten *grouping* brace groups inside a ``\\texttt`` argument, leaving
    command arguments intact. A ``{...}`` is a command argument when the text
    before it — **after skipping whitespace** — ends in a letter (the tail of a
    command name like ``\\textbf``), so both ``\\textbf{keep}`` and the valid
    ``\\textbf {keep}`` (whitespace before the brace) are preserved. Only a
    group whose inner text has no nested braces / backslash is flattened (e.g.
    the ``{@}`` citation-suppression idiom → ``@``)."""
    out = ''
    i = 0
    while i < len(arg):
        c = arg[i]
        if c == '\\' and i + 1 < len(arg):
            out += arg[i:i + 2]      # escaped char / command token — emit as-is
            i += 2
            continue
        if c == '{':
            j = _find_matching_brace(arg, i)
            if j >= 0:
                inner = arg[i + 1:j]
                prev = out.rstrip()
                is_command_arg = bool(prev) and prev[-1].isalpha()
                if not is_command_arg and '{' not in inner and '\\' not in inner:
                    out += inner            # grouping braces → flatten
                else:
                    out += arg[i:j + 1]     # command arg / nested → keep
                i = j + 1
                continue
        out += c
        i += 1
    return out


# ``\paragraph``/``\subparagraph`` are run-in, *unnumbered* headings in LaTeX,
# but pandoc emits them as deep ATX headings (``####``/``#####``) that qe-v5
# book-mode numbering then labels with a full multi-level number (the reporter
# saw a paragraph carrying §8.3.1.2.1 — #160B). Rewrite them to a bold run-in
# (``\textbf{…}`` → ``**…**``) pre-pandoc so they never enter the heading
# numbering tree at all. Matches LaTeX's own run-in semantics (the title flows
# into the following body). An optional ``[short-title]`` arg is dropped.
#
# EXCEPTION — a ``\paragraph`` carrying a ``\label{}`` keeps its heading form.
# The bold run-in would drop the anchor (a ``\label`` after ``\textbf`` becomes
# a mid-line ``[]{#…}`` span the post-pass strips), breaking every cross-ref to
# it — caught in a fixture pass: dl's ``\paragraph{…}\label{sec:matern}`` /
# ``\label{sec:irbc_…}`` are ``\ref``'d and went unresolved. Left as a heading,
# pandoc folds the ``\label`` into the heading id → ``(name)=`` anchor and the
# ref resolves (as a heading, which also renders the nicer ref text). The
# trailing ``\label`` must follow within the same paragraph (no blank line).
_PARAGRAPH_RE = re.compile(r'\\(?:sub)?paragraph\b\s*(?:\[[^\]]*\])?\s*\{')


def _label_follows(text: str, pos: int) -> bool:
    """True if a ``\\label{`` follows ``text[pos:]`` separated only by
    horizontal whitespace, ``%``-comments, and single newlines — i.e. still
    the same LaTeX paragraph. A *blank* line (two newlines with only
    whitespace between) ends the paragraph, so a ``\\label`` past it belongs
    to a later construct and is not the paragraph's. A scanner (not a regex)
    so the ``\\paragraph{T}%\n\\label`` line-join idiom and comment-only lines
    between the title and the label are handled, per the fence-aware doctrine
    (Copilot review on #165)."""
    i, n, pending_newline = pos, len(text), False
    while i < n:
        c = text[i]
        if c in ' \t':
            i += 1
        elif c == '%':                       # comment to end of line (content,
            nl = text.find('\n', i)          # so the line is not blank)
            i = n if nl < 0 else nl
            pending_newline = False
        elif c == '\n':
            if pending_newline:              # second newline → blank line
                return False
            pending_newline = True
            i += 1
        elif text.startswith(r'\label{', i):
            return True
        else:
            return False
    return False


def convert_paragraph_runins(text: str) -> str:
    """``\\paragraph{Title.}`` → ``\\textbf{Title.}`` (#160B), unless the
    ``\\paragraph`` is labelled (then keep the heading so the anchor survives)."""
    out = []
    pos = 0
    for m in _PARAGRAPH_RE.finditer(text):
        if m.start() < pos:
            continue
        open_brace = m.end() - 1
        close = _find_matching_brace(text, open_brace)
        if close < 0:
            continue
        # Labelled \paragraph → leave verbatim (kept as a heading); the
        # skipped span rides into the next emitted slice unchanged.
        if _label_follows(text, close + 1):
            continue
        title = text[open_brace + 1:close]
        out.append(text[pos:m.start()])
        out.append(f'\\textbf{{{title}}}')
        pos = close + 1
    out.append(text[pos:])
    return ''.join(out)


def flatten_texttt_brace_groups(text: str) -> str:
    """``\\texttt{{@}foo}`` → ``\\texttt{@foo}`` (#105).

    Authors wrap ``@`` in a brace group (``{@}``) to stop it being read as a
    citation key, but inside ``\\texttt`` pandoc turns the group into a second
    code span, emitting the broken ``` `@``foo` ```. The braces are invisible
    grouping in LaTeX, so flatten such grouping braces inside a ``\\texttt``
    argument while preserving real command arguments (``\\textbf{keep}`` and the
    whitespace form ``\\textbf {keep}``) — see ``_flatten_grouping_braces``."""
    out = []
    pos = 0
    for m in re.finditer(r'\\texttt\{', text):
        open_brace = m.end() - 1
        close = _find_matching_brace(text, open_brace)
        if close < 0:
            continue
        arg = text[open_brace + 1:close]
        out.append(text[pos:open_brace + 1])
        out.append(_flatten_grouping_braces(arg))
        pos = close
    out.append(text[pos:])
    return ''.join(out)


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: _apply_rewrites.py CONFIG TEX_FILE")
    config = load(Path(sys.argv[1]))
    tex_file = Path(sys.argv[2])

    pre = config.get('preprocess') or {}
    text = tex_file.read_text(encoding='utf-8')

    # 1. Strip patterns: regexes to delete (replace with empty)
    for pat in pre.get('strip') or []:
        if not pat:
            continue
        text = re.sub(pat, '', text)

    # 2. natbib rewrites — built-in, run before user rewrites so a book
    # can still post-process the markers (or override) if needed.
    for pat, repl in _NATBIB_REWRITES:
        text = re.sub(pat, repl, text)

    # 3. Strip inline ``\itemsep<dim>`` — confuses pandoc inside nested
    # lists (GH #28). No MyST analogue regardless, so a global strip is
    # safe.
    text = _ITEMSEP_STRIP.sub('', text)

    # 3b. Normalise legacy declaration font forms ({\sc ..}) pandoc would drop
    # (#107 gap 1), and flatten {@}-style brace groups inside \texttt that
    # pandoc splits into a second code span (#105).
    text = normalize_declaration_forms(text)
    text = flatten_texttt_brace_groups(text)

    # 3b'. Rewrite \paragraph/\subparagraph run-in headings to bold so they
    # don't enter qe-v5 book-mode heading numbering as deep ##### headings
    # (#160B).
    text = convert_paragraph_runins(text)

    # 3c. Strip the multicols column-count argument so it doesn't leak as a
    # stray number into the (column-less) MyST output, hoisting any optional
    # [pre-text] out as a paragraph before the env so pandoc doesn't silently
    # drop it (#111).
    text = _MULTICOLS_ARGS.sub(_strip_multicols_args, text)

    # 3d. Strip redundant ``on page~\pageref{X}`` locator clauses — pandoc
    # drops \pageref and strands "on page ." in single-page HTML (#158A).
    text = strip_orphan_pagerefs(text)

    # 4. Search-and-replace: { from: regex, to: replacement }
    for rule in pre.get('rewrites') or []:
        if not rule:
            continue
        text = re.sub(rule['from'], rule['to'], text)

    tex_file.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
