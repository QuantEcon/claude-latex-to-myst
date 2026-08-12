"""Shared marker-preprocessor base (Phase 2 — see
``docs/design/phase-2-marker-shared-base.md``).

The figure and table preprocessors are the two closest cousins of the
marker pattern: each extracts a LaTeX construct *pre-pandoc*, hides it in a
base64 HTML-comment marker that pandoc passes through verbatim, then a
post-pandoc resolver decodes it into a MyST directive. Before this module
they re-implemented the same scaffolding near line-for-line. This is that
scaffolding, factored once:

  - ``pandoc_batch_convert`` — one pandoc call over a list of cells joined
    by ``<!--CELL_N-->`` sentinels, split back out on the way out (with the
    ``\\mbox{}`` empty-cell guard, the optional ``~`` paren-guard, and the
    ``` `<!-- -->`{=html} ``` adjacency-artifact scrub).
  - ``encode_payload`` / ``decode_payload`` — the base64+JSON marker codec.
  - ``reassemble`` — blank-line-wrapped, source-order stream rebuild.

**Plain functions, no ``MarkerPlugin`` class.** The win is *deduplication*,
not *extensibility* — a registration/lifecycle base class is the
plugin-framework trap the project has declined (CLAUDE.md "no plugin
framework"; phase 2 §1).

## The pandoc/marker boundary

Pandoc owns inline prose, paragraph/inline math, native inline citations
(``\\cite``/``\\citet``/``\\citep``) and cross-ref plumbing. Everything
*structural* — floats, tabulars, algorithms, listings, description/enumerate
lists — is extracted to a marker pre-pandoc and decoded post-pandoc. See the
"Settled architectural decisions" entry in CLAUDE.md.

## Scope of this base

Only the constructs whose *cell contents need pandoc conversion* use
``pandoc_batch_convert`` — that is figure and table. The body-base64
constructs (algorithm, listing, description, enumerate) encode their bodies
verbatim and don't batch through pandoc, so they keep their own simpler
marker shapes; they are not forced through this base.

## Bail-predicate conservatism (the #98 #3 lesson)

A marker preprocessor runs as a separate pre-pandoc process and *cannot see*
post-pandoc config state (``TIKZ_FIGURE_MAP``, ``ENV_MAP``, cross-ref
routing). So each preprocessor's "should I marker-ize this block?" decision
must be **purely syntactic** and **conservative**: bail (return ``None`` for
the spec, leaving the block for the post-pandoc path) on any shape it cannot
fully model. The audited bail predicates per construct:

  - **figure** (``parse_figure_block``):
      * ``\\begin{subfigure}`` floats are marker-ized when *every* panel is a
        plain ``\\includegraphics`` (#94, Phase 4 — one ``{figure}`` per
        panel); a panel that isn't (dp1's ``\\scalebox{\\input{…pdf_t}}``)
        bails the whole float.
      * a raw ``\\begin{tikzpicture}`` body is marker-ized **caption-only**
        (Phase 6, lesson 045 — the tikz region is stripped first so node text
        isn't scooped, #98 #3); the image comes from the post-pandoc
        ``TIKZ_FIGURE_MAP`` override (``_emit_figure`` does the lookup).
      * multi-image ``\\input{tikz/…}`` blocks bail (would drop all but the
        first).
  - **table** (``parse_table_block``): longtable is routed to a dedicated
    multi-page parser; unparseable shapes return ``None`` and fall through
    to ``convert_simple_tables``.

Default stance: **model only what's fully modelled; bail (or, for the
tikz/subfigure cases above, carry only the part that IS modelled — the
caption — and let the override supply the image).**
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys

# Pandoc batch-conversion sentinel. Cells are joined by ``<!--CELL_N-->``
# markers; pandoc preserves the HTML comments (escaping them as
# ``\<!--CELL_N--\>``) and converts the LaTeX between them. The regex
# tolerates both the escaped and unescaped form.
CELL_SENTINEL_OUT_RE = re.compile(r'\\?<!--CELL_(\d+)--\\?>')

# Pandoc's adjacency-separator artifact: ``` `<!-- -->`{=html} ``. Emitted
# defensively between e.g. ``$math$`` and an immediately-following digit so
# some markdown parsers don't misread the adjacency. mystmd handles the
# adjacency natively, so the separator is pure noise — safe to strip.
PANDOC_ADJACENCY_ARTIFACT_RE = re.compile(r'`<!-- -->`\{=html\}')


def pandoc_batch_convert(
    cells: list[str], *, paren_guard: bool = False, caller: str = 'marker',
) -> list[str]:
    """Convert a list of LaTeX cell-content strings to markdown in ONE
    pandoc invocation. Returns a list of markdown strings, same length and
    order as ``cells``.

    - Empty cells become ``\\mbox{}`` so pandoc still emits a paragraph for
      them and the sentinel split stays unambiguous; they are mapped back to
      ``''`` on the way out.
    - ``paren_guard=True`` prefixes each cell with a LaTeX non-breaking space
      (``~``) so pandoc doesn't mis-read a paragraph-leading ``(a)`` as the
      math ``\\(a\\)`` — a quirk that bites multi-panel sub-captions like
      ``(a) the unit ball …``. The leading space is stripped on output.
    - The ``` `<!-- -->`{=html} ``` adjacency artifact is scrubbed.

    Fallback: if pandoc fails, or doesn't preserve the sentinels, return the
    original LaTeX cells unchanged — correctness over conversion. ``caller``
    names the preprocessor in the warning so a failure is attributable.
    """
    if not cells:
        return []

    parts: list[str] = []
    for i, cell in enumerate(cells):
        parts.append(f'<!--CELL_{i}-->')
        content = cell.strip() or r'\mbox{}'
        parts.append(('~' + content) if paren_guard else content)
    latex_in = '\n\n'.join(parts) + '\n'

    try:
        result = subprocess.run(
            ['pandoc', '-f', 'latex', '-t', 'markdown', '--wrap=none'],
            input=latex_in,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(
            f'{caller}: pandoc batch conversion failed '
            f'({type(e).__name__}); falling back to raw-LaTeX cells. '
            f'stderr: {getattr(e, "stderr", "")!r}',
            file=sys.stderr,
        )
        return list(cells)

    pieces = CELL_SENTINEL_OUT_RE.split(result.stdout)
    if len(pieces) < 3:
        # Pandoc didn't preserve any sentinels — fall back to original cells.
        return list(cells)

    out_cells: list[str] = [''] * len(cells)
    # pieces[0] is pre-first-sentinel text (usually empty); thereafter the
    # structure is [idx0, content0, idx1, content1, …].
    for i in range(1, len(pieces), 2):
        try:
            idx = int(pieces[i])
        except (ValueError, IndexError):
            continue
        content = pieces[i + 1] if i + 1 < len(pieces) else ''
        content = content.strip()
        if content in (r'\mbox{}', ''):
            content = ''
        content = PANDOC_ADJACENCY_ARTIFACT_RE.sub('', content)
        if 0 <= idx < len(out_cells):
            out_cells[idx] = content

    return out_cells


def encode_payload(kind: str, data) -> str:
    """Encode ``data`` (a JSON-serialisable dict) as a single-line
    HTML-comment marker ``<!--KIND payload=BASE64-->``. Single-line so
    pandoc treats it as a self-contained block."""
    payload = base64.b64encode(
        json.dumps(data, ensure_ascii=False).encode('utf-8')
    ).decode('ascii')
    return f'<!--{kind} payload={payload}-->'


def decode_payload(payload_b64: str):
    """Decode a base64 marker payload back into the JSON dict. Raises on
    malformed payloads (invalid base64 / non-JSON); callers leave the
    original marker in place on failure."""
    return json.loads(base64.b64decode(payload_b64.encode('ascii')).decode('utf-8'))


def reassemble(text: str, spans: list[tuple[int, int]], rendered: list[str | None]) -> str:
    """Rebuild ``text`` with each ``spans[i] = (start, end)`` slice replaced
    by ``rendered[i]`` (a marker string), or left as the original block text
    when ``rendered[i] is None`` (the defensive bail path).

    The marker is wrapped in ``\\n\\n`` on both sides so it sits on its own
    paragraph — pandoc otherwise glues the marker to adjacent prose, which
    breaks directive parsing on decode (see PR #53). ``spans`` must be in
    source order (the ``find_*_blocks`` finders return them so).
    """
    out: list[str] = []
    last_end = 0
    for (start, end), r in zip(spans, rendered):
        out.append(text[last_end:start])
        out.append(text[start:end] if r is None else f'\n\n{r}\n\n')
        last_end = end
    out.append(text[last_end:])
    return ''.join(out)
