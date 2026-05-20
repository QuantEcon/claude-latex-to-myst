#!/bin/bash
# =============================================================================
# new-book.sh — Scaffold a `mystmd/` directory for converting a new LaTeX book.
# =============================================================================
#
# Picks a starter config from one of the bundled examples, copies it into
# the destination, rewrites the obvious placeholders (paths, chapter list
# auto-discovered from .tex files in the source dir), and prints next-steps.
#
# Usage:
#   scripts/new-book.sh --source <DIR> --dest <DIR> [--template dp2|dp1|minimal]
#
#   --source <DIR>     Directory holding the book's .tex sources.
#   --dest <DIR>       Where to scaffold the mystmd/ workspace. Will be
#                      created if it doesn't exist; must be empty if it does.
#   --template NAME    Which example to start from. Defaults to ``dp2``:
#                        dp2      — full-featured (TikZ overrides, scalebox,
#                                   etc.). The originating project's config.
#                        dp1      — book/ subdir layout, standalone
#                                   frontmatter, pageref strips.
#                        minimal  — strip + rewrite empty; you fill in.
#   --force            Allow scaffolding into a non-empty destination
#                      (overwrites existing config.yaml / tikz_overrides.py).
#
# After scaffolding:
#   1. Edit ``$DEST/config.yaml`` — chapter titles, bib filename, etc.
#   2. Edit ``$DEST/tikz_overrides.py`` if the book has TikZ diagrams.
#   3. Run: bash scripts/convert.sh --config $DEST/config.yaml
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
EXAMPLES_DIR="$PROJECT_DIR/examples"

SOURCE=""
DEST=""
TEMPLATE="dp2"
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)   SOURCE="$2"; shift 2 ;;
    --dest)     DEST="$2";   shift 2 ;;
    --template) TEMPLATE="$2"; shift 2 ;;
    --force)    FORCE=1; shift ;;
    --help|-h)
      sed -n '2,/^# ===/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$SOURCE" ]] && { echo "ERROR: --source is required" >&2; exit 1; }
[[ -z "$DEST" ]]   && { echo "ERROR: --dest is required" >&2; exit 1; }
[[ ! -d "$SOURCE" ]] && { echo "ERROR: --source not found: $SOURCE" >&2; exit 1; }

case "$TEMPLATE" in
  dp1|dp2)
    TEMPLATE_DIR="$EXAMPLES_DIR/book-$TEMPLATE"
    if [[ ! -f "$TEMPLATE_DIR/config.yaml" ]]; then
      echo "ERROR: template directory missing: $TEMPLATE_DIR" >&2
      exit 1
    fi
    ;;
  minimal)
    TEMPLATE_DIR=""  # use config.example.yaml at project root
    if [[ ! -f "$PROJECT_DIR/config.example.yaml" ]]; then
      echo "ERROR: config.example.yaml not found at $PROJECT_DIR" >&2
      exit 1
    fi
    ;;
  *)
    echo "ERROR: --template must be one of: dp2, dp1, minimal (got '$TEMPLATE')" >&2
    exit 1
    ;;
esac

# Resolve paths to absolute, prepare destination.
SOURCE="$(cd "$SOURCE" && pwd)"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"

if [[ -e "$DEST/config.yaml" && "$FORCE" -ne 1 ]]; then
  echo "ERROR: $DEST/config.yaml already exists (use --force to overwrite)" >&2
  exit 1
fi

# Copy the template files.
if [[ -n "$TEMPLATE_DIR" ]]; then
  cp "$TEMPLATE_DIR/config.yaml" "$DEST/config.yaml"
  [[ -f "$TEMPLATE_DIR/tikz_overrides.py" ]] && \
    cp "$TEMPLATE_DIR/tikz_overrides.py" "$DEST/tikz_overrides.py"
else
  cp "$PROJECT_DIR/config.example.yaml" "$DEST/config.yaml"
fi

# Compute the source_dir relative path (from DEST to SOURCE).
REL_SOURCE="$(python3 -c "import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$SOURCE" "$DEST")"

# Auto-discover chapters: any .tex file directly in SOURCE whose stem
# starts with ``ch`` (covers ``ch_intro``, ``ch01_foo``, ``chapter_1``).
DISCOVERED=$(cd "$SOURCE" && ls *.tex 2>/dev/null | sed 's/\.tex$//' | grep -E '^ch' | sort || true)

# Rewrite the config: source_dir, plus a discovered chapter block so the
# user has a starting point instead of leftover example titles.
python3 - "$DEST/config.yaml" "$REL_SOURCE" <<PYEOF
import sys, re, pathlib

config_path = pathlib.Path(sys.argv[1])
rel_source  = sys.argv[2]
discovered  = """$DISCOVERED""".strip().splitlines()

text = config_path.read_text(encoding='utf-8')

# Point source_dir at the user's tex tree (relative to DEST).
text = re.sub(
    r'^source_dir:\s*"[^"]*"',
    f'source_dir: "{rel_source}"',
    text,
    count=1,
    flags=re.MULTILINE,
)

# Replace the chapter block (between ``chapters:`` and the next top-level
# key) with auto-discovered stems. Leave titles as placeholders for the
# user to fill in — we don't try to guess them.
if discovered:
    new_block = 'chapters:\n' + '\n'.join(
        f'  - {{ stem: {stem}, title: "TODO: {stem}" }}' for stem in discovered
    ) + '\n'
    text = re.sub(
        r'^chapters:.*?(?=^\S)',
        new_block + '\n',
        text,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )

config_path.write_text(text, encoding='utf-8')
print(f"  wrote {len(discovered)} chapter stem(s) to {config_path.name}")
PYEOF

echo ""
echo "Scaffolded: $DEST"
echo "  config.yaml         (template: $TEMPLATE)"
[[ -f "$DEST/tikz_overrides.py" ]] && echo "  tikz_overrides.py   (edit if the book has TikZ diagrams)"
echo ""
echo "Next steps:"
echo "  1. Edit $DEST/config.yaml — fill in 'TODO: …' chapter titles,"
echo "     adjust bibliography filename, project-specific rewrites, etc."
echo "  2. Run:"
echo "       bash $SCRIPT_DIR/convert.sh --config $DEST/config.yaml"
echo "  3. Build the output:"
echo "       cd $DEST && myst build --html"
echo ""
echo "See CLAUDE.md ('Iterative error reduction') for the typical first-run workflow."
