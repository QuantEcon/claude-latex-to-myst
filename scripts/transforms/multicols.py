"""``multicols`` paired enumerate → MyST ``{grid}`` (#170).

book-dp1 places a set of math statements beside their property names with a
``\\begin{multicols}{2}`` wrapping a custom-label ``enumerate``: the first half
of the items are the statements ``(a)–(d)`` and the second half the matching
``\\item[]`` names. ``multicols`` balances the items **column-first** (4-and-4),
so each statement sits next to its name in the PDF. Otherwise ``multicols`` is
dropped (it is in ``DEFAULT_ENV_SKIP``) and the list flattens into one stacked
column — separating every name from the statement it belongs to. That is the
unfinished part of #111 (the custom ``(a)–(d)`` labels and the stray
column-count leak were fixed there; the *layout* was not).

This module reproduces the two-column layout as a MyST ``{grid}``: the
custom-label enumerate is split column-first into ``N`` balanced groups, each
group becoming one ``{grid-item}`` cell. The grid is responsive
(``{grid} 1 1 N N`` — one column on mobile, ``N`` on desktop), and the browser
stacks each cell's items so statement ``(a)`` lines up beside name
``(nonnegativity)``, just like ``multicols``.

Marker pattern (``transforms/_markers``) — pandoc mangles literal ``:::``
directive markup from LaTeX input, so the structure is hidden from pandoc:
``_apply_multicols_grid.py`` extracts the block pre-pandoc, batch-converts each
item's content LaTeX→markdown, and stores the result in a
``<!--MULTICOLSGRID payload=…-->`` marker; ``resolve_multicols_grid`` decodes
it post-pandoc and emits the grid.

Conservative bail (the marker-preprocessor doctrine — a pre-pandoc pass can't
see post-pandoc config): a ``multicols`` block is marker-ized only when its
body is a **single custom-label enumerate** (every ``\\item`` carries an
explicit ``[label]``) surrounded by nothing but whitespace / ``\\setlength`` /
``\\label`` / comments. Any other ``multicols`` content — backmatter prose, an
auto-counter list, a wrapped tabular, nested ``multicols`` — returns ``None``
and falls through to the existing column-strip + ``ENV_SKIP`` path unchanged.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ._helpers import convert_label_colons
from ._markers import decode_payload, encode_payload


@dataclass
class MulticolsSpec:
    """A marker-ized ``multicols`` paired enumerate. ``items`` are the
    ``label + content`` cells already converted to markdown (in source order);
    ``columns`` is the original ``{N}``; ``head_labels`` are any ``\\label``
    anchors that sat on the enumerate itself."""
    columns: int
    items: list[str]
    head_labels: list[str] = field(default_factory=list)


# ``\begin{multicols}{N}[pretext]? … \end{multicols}`` — non-greedy body. The
# nested-multicols case is bailed in ``parse_multicols_block`` (the simple
# non-recursive match can't pair nested begin/end).
_MULTICOLS_BLOCK_RE = re.compile(
    r'\\begin\{multicols\*?\}\s*\{(?P<cols>\d+)\}(?:\s*\[[^\]]*\])?'
    r'(?P<body>.*?)\\end\{multicols\*?\}',
    re.DOTALL,
)
_ENUM_BLOCK_RE = re.compile(
    r'\\begin\{enumerate\}(?:\[[^\]]*\])?(?P<ebody>.*?)\\end\{enumerate\}',
    re.DOTALL,
)
_SETLENGTH_RE = re.compile(r'\\setlength\{[^}]*\}\{[^}]*\}')
_LABEL_RE = re.compile(r'\\label\{[^}]*\}')

# ``\begin{multicols}{N}[pre-text]`` — the mandatory column-count argument and
# the optional spanning pre-text, for the NON-grid multicols left in place
# (wrapped tabulars, backmatter prose, …). multicols is dropped post-pandoc
# (the wrapper is in ``DEFAULT_ENV_SKIP``), but pandoc renders the ``{N}`` arg
# as a stray ``N`` paragraph that leaks into the body (#111). MyST has no
# multi-column primitive for these, so strip the ``{N}``. The optional
# ``[pre-text]`` is real content (multicols prints it full-width before the
# columns) but pandoc silently drops an optional arg on the count-less env, so
# hoist it OUT as a paragraph before the env (lesson 028). Moved here from
# ``_apply_rewrites.py`` (#170) so a single pass owns all multicols handling.
_MULTICOLS_ARGS = re.compile(
    r'(\\begin\{multicols\*?\})\s*\{[^}]*\}(?:\s*\[([^\]]*)\])?'
)


def _strip_multicols_args(m: re.Match) -> str:
    env, pretext = m.group(1), m.group(2)
    if pretext and pretext.strip():
        return f'{pretext.strip()}\n\n{env}'
    return env


def strip_remaining_multicols_args(text: str) -> str:
    """Strip the ``{N}`` count (and hoist any ``[pre-text]``) from every
    ``multicols`` still present after the grid-eligible ones were marker-ized
    (#111). The grid blocks are already base64 inside markers, so this only
    touches the non-grid ones left for the ``ENV_SKIP`` path."""
    return _MULTICOLS_ARGS.sub(_strip_multicols_args, text)


def _starts_in_comment(text: str, pos: int) -> bool:
    """Same guard as the sibling preprocessors: a block whose ``\\begin`` sits
    on a ``%``-commented line is not a real block."""
    line_start = text.rfind('\n', 0, pos) + 1
    i = line_start
    while i < pos:
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == '%':
            return True
        i += 1
    return False


def find_multicols_blocks(text: str) -> list[tuple[int, int, int, str]]:
    """Return ``[(start, end, columns, body), …]`` for every ``multicols``
    block in source order. Commented-out blocks are skipped."""
    blocks: list[tuple[int, int, int, str]] = []
    for m in _MULTICOLS_BLOCK_RE.finditer(text):
        if _starts_in_comment(text, m.start()):
            continue
        blocks.append((m.start(), m.end(), int(m.group('cols')), m.group('body')))
    return blocks


def parse_multicols_block(columns: int, body: str):
    """Return a ``(MulticolsSpec, item_latex_cells)`` pair when ``body`` is a
    single custom-label enumerate; else ``None`` (leave the block to the
    existing column-strip path). ``item_latex_cells`` are the raw ``label +
    content`` strings the caller batch-converts before encoding the marker."""
    # The item parser is the same one the enumerate flattener uses (#111);
    # imported lazily so this module imports cleanly in any context.
    from _apply_custom_label_enumerates import parse_custom_label_items

    if columns < 2:
        return None
    if '\\begin{multicols' in body:
        return None  # nested multicols — not modelled
    enum_iter = list(_ENUM_BLOCK_RE.finditer(body))
    if len(enum_iter) != 1:
        return None  # zero or multiple enumerates — not the paired shape
    em = enum_iter[0]
    # Everything OUTSIDE the enumerate must be inert (whitespace / setlength /
    # label / comment); otherwise this multicols carries content we don't model.
    # Strip non-escaped ``%`` comments — full-line AND trailing — so a
    # ``\setlength{…}{…} % tweak`` doesn't leave a residual ``% tweak`` and
    # bail (Copilot review). Same idiom as ``_algpseudo_tokenize``.
    outside = body[: em.start()] + body[em.end():]
    outside_live = re.sub(r'(?<!\\)%.*$', '', outside, flags=re.MULTILINE)
    residual = _LABEL_RE.sub('', _SETLENGTH_RE.sub('', outside_live))
    if residual.strip():
        return None
    parsed = parse_custom_label_items(em.group('ebody'))
    if parsed is None:
        return None
    items, head_labels = parsed
    if len(items) < columns:
        return None  # fewer items than columns — nothing to balance
    cells = [f'{label} {content}'.strip() for label, content in items]
    spec = MulticolsSpec(columns=columns, items=[], head_labels=head_labels)
    return spec, cells


def encode_marker(spec: MulticolsSpec) -> str:
    """Encode a ``MulticolsSpec`` as a one-line ``<!--MULTICOLSGRID payload=…-->``
    marker (shared base64+JSON codec)."""
    return encode_payload('MULTICOLSGRID', asdict(spec))


def decode_marker(payload_b64: str) -> MulticolsSpec:
    data = decode_payload(payload_b64)
    return MulticolsSpec(
        columns=data['columns'],
        items=data['items'],
        head_labels=data.get('head_labels', []),
    )


def _split_columns(items: list[str], n: int) -> list[list[str]]:
    """Split ``items`` column-first into ``n`` balanced groups, matching
    ``multicols`` balancing (earlier columns absorb the remainder)."""
    total = len(items)
    base, rem = divmod(total, n)
    cols: list[list[str]] = []
    idx = 0
    for c in range(n):
        size = base + (1 if c < rem else 0)
        cols.append(items[idx: idx + size])
        idx += size
    return cols


def _emit_grid(spec: MulticolsSpec) -> str:
    n = spec.columns
    cols = _split_columns(spec.items, n)
    lines: list[str] = []
    for lbl in spec.head_labels:
        lines.append(f'({convert_label_colons(lbl)})=')
    if spec.head_labels:
        lines.append('')
    # Responsive: 1 column on xs/sm, N on md/lg — the browser balances each
    # cell's stacked items, reproducing multicols' row pairing.
    lines.append(f'::::{{grid}} 1 1 {n} {n}')
    for col in cols:
        lines.append(':::{grid-item}')
        lines.append('\n\n'.join(item for item in col if item))
        lines.append(':::')
    lines.append('::::')
    return '\n'.join(lines)


_MARKER_RE = re.compile(
    r'\\?<!--MULTICOLSGRID\s+payload=([A-Za-z0-9+/=]+?)--\\?>',
)


def resolve_multicols_grid(text: str, ctx=None) -> str:
    """Decode every ``<!--MULTICOLSGRID payload=…-->`` marker into a MyST
    ``{grid}``. A corrupted payload leaves the marker in place (mirrors the
    figure / table resolvers)."""
    def repl(m: re.Match) -> str:
        try:
            spec = decode_marker(m.group(1))
            return _emit_grid(spec)
        except Exception:
            return m.group(0)

    return _MARKER_RE.sub(repl, text)
