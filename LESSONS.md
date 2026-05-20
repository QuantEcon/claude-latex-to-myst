# Lessons Index

Pitfalls learned across LaTeX → MyST conversions. See [`lessons/README.md`](lessons/README.md)
for schema and lifecycle. Add new lessons with `/capture-lesson`.

Severity legend: 🔴 high · 🟡 medium · 🟢 low

| ID  | Title | Category | Severity | Status |
|----:|-------|----------|----------|--------|
| 001 | [Blank lines inside $$ math blocks silently terminate them](lessons/001-blank-lines-in-math-blocks.md) | post-processing | 🔴 | codified |
| 002 | [Cross-ref regex consumes equation blocks via [0,1) bracket false-match](lessons/002-cross-ref-regex-eats-equations.md) | regex-safety | 🔴 | codified |
| 003 | [KaTeX cannot parse $ inside \\text{...}](lessons/003-text-dollar-katex-incompat.md) | katex | 🔴 | codified |
| 004 | [Never use id(list) to auto-generate labels](lessons/004-id-recycling-duplicate-labels.md) | post-processing | 🟡 | codified |
| 005 | [Skipping unsupported nested divs needs depth tracking](lessons/005-env-skip-depth-tracking.md) | post-processing | 🟡 | codified |
| 006 | [LaTeX % comments inside math blocks break KaTeX](lessons/006-percent-comments-in-math.md) | katex | 🟢 | codified |
| 007 | [\\cref{a,b,c} becomes a single broken pandoc link](lessons/007-cref-comma-split.md) | post-processing | 🟡 | codified |
| 008 | [Post-processing transform order is critical and fragile](lessons/008-pipeline-ordering.md) | post-processing | 🔴 | codified |
| 009 | [BSD sed and bash 3.2 break the preprocess pipeline on macOS](lessons/009-bsd-sed-mapfile-portability.md) | tooling | 🟡 | codified |
| 010 | [PEP 668 blocks pip install on modern system Python — always document a venv](lessons/010-pep-668-system-python.md) | tooling | 🟢 | codified |

## By category

- **post-processing:** 001, 004, 005, 007, 008
- **regex-safety:** 002
- **katex:** 003, 006
- **tooling:** 009, 010
