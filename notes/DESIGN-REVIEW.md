# Design review notes — for later

Personal notes for the deep design review the user wants to do later.
Not a proposal — a structured set of questions and observations to start
that conversation from.

## Provoking questions the user raised

1. **Is pandoc the right choice for the LaTeX → MyST conversion path?**
2. **Should we build a custom lightweight AST of our own?**
3. **What does the long-term architecture look like?**

Below: arguments on each side, evidence from the current codebase, and
suggested experiments / decision criteria.

---

## 1. Pandoc — what works, what doesn't

### Pandoc's strengths in this pipeline

- **Free industrial-strength LaTeX reader.** Math conversion (`$...$`,
  `\begin{align}`, `\eqref`), citation handling (`@key`), basic prose
  → markdown is rock-solid. We'd need years to match that.
- **Cross-reference plumbing.** Pandoc resolves `\ref{}` /
  `\eqref{}` into `<a data-reference="...">` HTML, which our typed-
  dispatch (`refs.routing_role`) turns into `{eq}` / `{numref}` /
  `{prf:ref}`. That data-reference attribute is load-bearing for
  lesson [033].
- **Universal markdown writer.** When pandoc emits a clean
  markdown form (`$math$`, `[@cite]`, image syntax, simple tables),
  downstream MyST handling is trivial.

### Pandoc's failure modes (every one of these has cost us bugs)

| Failure mode | Bugs it caused | Lesson(s) |
|---|---|---|
| LaTeX-tabular reader collapses `\hline` separators | #51 (table marker rebuild) | #019 / #025 |
| HTML emission for figures uses *attributes* for cite keys | #89, #92 | #043 |
| Empty `<span class="citation">` form drops keys on strip | #89 | #043 |
| Brackets escaped in markdown context but not HTML | #92 | #043 |
| `(a)` → `\(a\)` math misinterpretation at paragraph start | #95 (defensive `~` prefix) | #043 |
| `<embed>` vs `<img>` inconsistency for `\includegraphics` | #25 | #026 |
| Pre-resolves `\ref{}` to chapter-unaware numbers | #33 | #033 |
| HTML entities `&gt;` etc. survive into math regions | #40 | (codified in extract_caption) |
| Lossy minipage handling — sub-captions dropped or mangled | #90, #93 | #043 |
| Class attribute leaks into MyST label tokens | #17 | #017 |
| Pandoc-attr fenced code blocks not MyST-compatible | #34 | #034 |
| `\text{$x$}` math nesting broken in KaTeX | (code-block fix) | #003 |
| `\citep[loc]{key}` drops the key | #74 | #020 follow-on |
| `\citet{key:colon:tag}` truncates at colon in textual form | #31, #35 | #031 |

That's **14 distinct bug classes** stemming from pandoc's LaTeX→markdown
or LaTeX→HTML output choices, all worked around in our postprocess
or preprocess layers. The marker preprocessor pattern (tables → #51,
figures → #95) is now our standard escape hatch: extract the construct
pre-pandoc, hide it in a base64 marker, decode post-pandoc.

### The hidden cost we don't usually measure

The lesson catalogue currently has 43 lessons. By rough categorization:
- ~30 of them describe pandoc-emission quirks the postprocess must
  work around. That's ~70% of our accumulated knowledge being "how to
  patch around pandoc."
- Every new book is likely to surface more, because pandoc's behaviour
  is sensitive to LaTeX-package usage, custom macros, environment
  shapes we haven't seen.

### Decision: keep pandoc?

The strongest argument for keeping it is the math + cite + ref reader.
Those are big and rock-solid. The strongest argument against is the
HTML-emission fragility for figures / tables / structured content —
where we've now built two marker preprocessors (tables, figures) to
sidestep it entirely.

A useful pattern to recognize: the marker preprocessor approach is
basically **"pandoc for prose, our own parser for structure."** We've
been doing this incrementally — first tables (#51), now figures (#95)
— without saying it explicitly. Algorithms (`_apply_algorithm_markers`),
listings (`_apply_listing_markers`), description lists, enumerate
exercises follow the same shape: extract structure pre-pandoc, hand
pandoc only the prose.

### Question to answer in the review

If we kept extending this pattern, what's left for pandoc to do?

- Math expressions (`$...$`, `\begin{align}` etc.) — we'd still want
  pandoc here.
- Inline cites (`\cite`, `\citet`) — pandoc's native cite handling is
  good for these.
- Plain prose (paragraphs, italics, bold) — trivial.

Everything else has been handed off to marker preprocessors or is
trending that way. The pandoc layer is becoming a "pandoc for inline
prose, ours for structure" hybrid.

---

## 2. Custom AST — what would it look like?

### What we'd need to build

A LaTeX → AST → MyST pipeline that we own end-to-end. Components:

1. **LaTeX lexer/parser**: tokenize `\command{arg}[opt]{arg}`,
   `\begin{env}...\end{env}`, math regions, comments, prose.
2. **AST**: nodes for each construct (Paragraph, MathInline,
   MathDisplay, Figure, Table, Citation, Reference, …).
3. **MyST emitter**: walk the AST, emit MyST markdown for each node
   kind.
4. **Config-driven extensions**: per-project macro definitions
   (`\newcommand`), TIKZ overrides, custom envs.

### What we'd gain

- **No pandoc-emission quirks ever again.** The bug class that's
  driven most of our work disappears.
- **Source of truth ownership.** Every transform is in our codebase;
  every behaviour is testable in isolation.
- **Better error messages.** When something fails, we can pinpoint
  the source location and the failing rule.
- **Eliminating the "I don't know what pandoc will emit" guessing
  game** that has been the root cause of every figure/table/citation
  patch in the lesson catalogue.

### What we'd lose / pay

- **Months of work** to match what pandoc gives us for math, prose,
  basic cite handling. Realistically a multi-quarter project.
- **Edge cases pandoc has already solved**: nested groups, fragile
  arguments, robust commands, weird braces. Every LaTeX corner case
  is a potential bug we have to discover.
- **Risk of inventing-our-own-syntax problems.** Pandoc has been
  hardened by ~15 years of use. Our parser would be brand new.
- **Maintenance burden in perpetuity.** Currently pandoc fixes its
  own bugs upstream; we get them for free. Our parser, we own forever.

### A middle path: hybrid

Continue what we're doing — extend the marker-preprocessor pattern to
the remaining structural shapes (subfigure in Phase 2, equations
maybe?), keep pandoc for what it does well (math, inline cites, prose).

This is essentially the current trajectory **made explicit**. It's
hybrid not by accident but by design:

- **Marker preprocessors (ours):** tables, figures, algorithms,
  listings, description lists, enumerate exercises. Anything where
  pandoc's emission is lossy or fragile.
- **Pandoc:** prose, paragraph-level math, inline citations (`\cite`,
  `\citet` native path), cross-refs (via `data-reference` recovery).

The question for the review is whether to **make this hybrid
explicit in the architecture** (and the contributing docs) or
continue letting it accrete one marker preprocessor at a time.

### Strawman: what an explicit hybrid commitment looks like

```
preprocess.sh stages:
  Stage 1 (config): _apply_rewrites (natbib, user)
  Stage 2 (chapters): _apply_chapter_splits
  Stage 3 (structural markers — extract per construct):
    _apply_table_markers
    _apply_figure_markers          # Phase 1 done, Phase 2 → subfigure
    _apply_algorithm_markers
    _apply_listing_markers
    _apply_description_markers
    _apply_enumerate_markers
    _apply_<NEW>_markers as needed
  Stage 4 (final cleanup): _apply_itemsep_strip (already in rewrites)

pandoc (only sees inline prose + math + native cites + refs)

postprocess (resolve markers + minor pandoc-quirk fixes)
```

The PR #95 / #96 trajectory suggests Phase 2 should be subfigure
migration (issue #94). After that, the lesson catalogue's
"pandoc quirk" category should stop growing.

---

## 3. Cross-cutting observations

### The marker pattern is the load-bearing architecture

5 of our 8 preprocess scripts are marker-pattern preprocessors. They
share a common shape: parse the construct from LaTeX, extract structural
fields, batch-convert prose-bearing fields through pandoc, base64
the spec, emit `<!--FOO payload=...-->` marker. The post-pandoc
resolver decodes and emits MyST.

**Worth codifying:** a shared abstract base for marker preprocessors
(parser → spec → batch-convert → encode) and resolvers (decode → emit).
Each new shape becomes ~50 LOC of "what's specific to me" plus the
shared infrastructure.

This is conceptually the same as recognizing the hybrid: instead of
each marker preprocessor reinventing `_pandoc_batch_convert`,
`_starts_in_comment`, marker regex, etc., we factor them.

### The validation gap

The #95 → #96 trajectory revealed that synthetic e2e tests pass while
consumer-book e2e fails. Process-level fix: a `fixtures/` clone of
each consumer book + a `make validate-against-book` step that
counts surviving figures, tables, cites, etc. before any merge
that touches the relevant transforms.

This is more important than any architectural decision below. Even
if we keep pandoc forever, consumer-book validation would have caught
#96 in 10 minutes pre-merge.

### Test coverage shape

Current: 603 unit tests + a few golden-file integration tests +
synthetic e2e tests in test_figure_markers.py / test_table_markers.

Missing:
- **Real-book end-to-end validation gates**. Currently only the user
  runs convert.sh against book-dp-deep-learning. We should automate
  this for PRs that touch figure/table/citation paths.
- **Per-book regression baselines**. If we commit a "this is what
  the conversion looked like at SHA X" snapshot for each consumer
  book, every PR can diff against it.
- **Coverage of TIKZ_FIGURE_MAP, per-project config interactions**.
  None of our synthetic tests exercise these.

### Code organization

The split `tables.py` / `tables_from_latex.py` (and now `figures.py`
/ `figures_from_latex.py`) is a useful pattern: parser + emit + spec
in `*_from_latex.py`, post-pandoc HTML-pattern matchers in the older
file. As we migrate more shapes to markers, the older files shrink to
"fallback paths only."

Worth tracking: which transforms still depend on pandoc's HTML / markdown
emission? An audit might reveal candidates for the next marker
preprocessor migration.

### Lesson-driven development

Looking at the 43 lessons in `lessons/`, the codebase has accumulated
deep institutional knowledge. The lesson catalogue itself is one of
the most valuable artifacts. Worth considering:

- Should new contributors read the catalogue first? (Currently
  CLAUDE.md says yes.)
- Are lessons machine-actionable? Could we generate test cases from
  them?
- Are some lessons obsolete (codified fixes have been superseded)?
  Periodic review might be worthwhile.

---

## 4. Concrete decision questions for the review

Pick any subset. Most are independent.

1. **Commit to the hybrid?** Document it as the explicit architecture,
   not just an accreting pattern. Update CLAUDE.md, name the boundary
   between "pandoc territory" and "our territory."

2. **Codify the marker-preprocessor shared infrastructure?** Reduce
   per-shape boilerplate; standardize naming.

3. **Phase 2 figure-marker (subfigure)?** Issue #94 already tracks
   this. Schedule it explicitly — within DL R15 timeframe or punt?

4. **Validation gate against consumer books?** Maintainer-side or
   automated? This is the most important process question.

5. **Audit the remaining pandoc-quirk patches in postprocess?**
   Which ones are candidates for marker-preprocessor migration
   (`convert_equations`? `convert_simple_tables`? something in
   citations?). Each migration eliminates a bug-class generator.

6. **Lesson catalogue review?** Are any lessons obsolete? Any
   patterns the catalogue suggests but the codebase hasn't acted on?

7. **Custom AST: dismiss or schedule for future?** If we're committed
   to the hybrid, a custom AST is overkill. But worth a 1-page
   "we evaluated this and chose not to" decision record so future-
   maintainers don't re-litigate.

---

## 5. My honest recommendation (if asked)

**Don't build a custom AST.** The marker-preprocessor hybrid is
working — we've used it for tables, figures, algorithms, listings,
description lists, enumerate. The pattern is well-understood. The
remaining pandoc-quirk patches are mostly small (cite-key colon
truncation, HTML-entity unescape, etc.).

**Do commit to the hybrid explicitly:**
1. Document the boundary in CLAUDE.md ("pandoc handles prose / math
   / inline cites / refs; everything else uses marker preprocessors").
2. Codify shared infrastructure across marker preprocessors.
3. Establish consumer-book validation as a pre-merge gate.
4. Schedule Phase 2 subfigure migration (#94).
5. Periodic lesson-catalogue review.

This avoids the "build everything ourselves" cost while making the
current pattern intentional rather than emergent. The validation gate
is the most urgent piece — that's what would have prevented #96.

The "should we replace pandoc" question itself might become moot
once the hybrid is explicit: we use pandoc for what it does well,
and we've already replaced its weak spots with our own code. There's
not much "pandoc-only territory" left worth attacking.
