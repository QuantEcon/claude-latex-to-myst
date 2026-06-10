#!/bin/bash
# =============================================================================
# validate_fixture.sh — one common validation process for every book fixture
# =============================================================================
#
# Runs the identical regen → validate → diff sequence against any of the three
# consumer-book fixtures, so "is this book still clean?" is one command rather
# than three bespoke invocations. Used by the architecture-phase work and by
# hand.
#
# TWO BASELINES, two purposes (see notes/design + the architecture-phases
# session prompt):
#
#   --against baseline   (default)  diff regen vs the committed, human-worked-on
#                                    mystmd/ on the mystmd-conversion branch.
#                                    This is the PARITY target — an objective to
#                                    drive down, NOT a hard gate (the worked-on
#                                    output has irreducible hand-edits the
#                                    deterministic tool won't reproduce).
#   --against snapshot               diff regen vs fixtures/<book>/_snapshot/,
#                                    a pinned copy of the tool's own output.
#                                    This is the REFACTOR-SAFETY check — a
#                                    behavior-preserving phase must keep regen
#                                    BYTE-IDENTICAL to the snapshot (tool-vs-
#                                    tool, always achievable).
#
#   --pin                            (re)pin the snapshot: after a clean regen,
#                                    copy the regenerated stems into _snapshot/.
#                                    Do this at Phase 0, and again only after a
#                                    phase INTENTIONALLY changes output (Phase 4),
#                                    once the change is reviewed.
#
# Per book it: regenerates via convert.sh, runs validate.py (signal B), then
# either pins the snapshot or diffs <stem>.md against the chosen reference, for
# every stem the config regenerates (chapters + extra_files, honouring
# regen: false). Hand-curated files not in the config (e.g. dp1
# common_symbols.md) are excluded by construction. Signal A (unit + golden
# suites) is global — run `bash scripts/test.sh` separately.
#
# Usage:
#   scripts/validate_fixture.sh dp1                      # parity diff (default)
#   scripts/validate_fixture.sh all                      # all three, parity
#   scripts/validate_fixture.sh all --against snapshot   # refactor-safety check
#   scripts/validate_fixture.sh all --pin                # pin the safety snapshot
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="$PROJECT_DIR/fixtures"

AGAINST="baseline"   # baseline (worked-on mystmd/) | snapshot (_snapshot/)
PIN=0
BUILD=0             # --build: render-gate smoke test (build_smoke.py, signal D)

fixture_dir_for() {
  case "$1" in
    dp1)           echo "book-dp1" ;;
    dp2)           echo "book-dp2" ;;
    deep-learning) echo "book-dp-deep-learning" ;;
    *) echo "" ;;
  esac
}

# Echo the regenerating stems for a config (chapters + extra_files, skipping
# any with regen: False), one per line.
regen_stems() {
  local config="$1"
  python3 - "$SCRIPT_DIR/_config.py" "$config" <<'PY'
import subprocess, sys
cfgpy, config = sys.argv[1], sys.argv[2]
def col(key):
    out = subprocess.run([sys.executable, cfgpy, config, key],
                         capture_output=True, text=True).stdout.splitlines()
    return out
for group in ("chapters", "extra_files"):
    stems = col(f"{group}.stem")
    flags = col(f"{group}.regen")
    for i, stem in enumerate(stems):
        if not stem:
            continue
        if i < len(flags) and flags[i] == "False":
            continue
        print(stem)
PY
}

validate_one() {
  local book="$1"
  local dir; dir="$(fixture_dir_for "$book")"
  if [[ -z "$dir" ]]; then
    echo "ERROR: unknown book '$book' (use dp1 | dp2 | deep-learning)" >&2
    return 2
  fi

  local fixture="$FIXTURES_DIR/$dir"
  local config="$fixture/regen/config.yaml"
  if [[ ! -f "$config" ]]; then
    echo "ERROR: $config not found — run scripts/setup_fixtures.sh $book" >&2
    return 2
  fi

  # Reference dir for the (C) diff.
  local ref
  case "$AGAINST" in
    baseline) ref="$fixture/mystmd" ;;
    snapshot) ref="$fixture/_snapshot" ;;
  esac

  local mode_note="against: $AGAINST"
  [[ "$PIN" -eq 1 ]] && mode_note="pinning snapshot"
  echo "================================================================"
  echo "  $book  ($dir)   [$mode_note]"
  echo "================================================================"

  # --- regenerate ----------------------------------------------------------
  echo "-- regenerating (convert.sh) ..."
  if ! bash "$SCRIPT_DIR/convert.sh" --config "$config" >/dev/null 2>"$fixture/regen/convert.err"; then
    echo "  FAIL: convert.sh errored — see $fixture/regen/convert.err"
    return 1
  fi
  local config_dir output_dir
  config_dir="$(dirname "$config")"
  output_dir="$(cd "$config_dir/$(python3 "$SCRIPT_DIR/_config.py" "$config" output_dir)" && pwd)"

  local bfail=0 cfail=0

  # --- signal B: validate.py exits 0 --------------------------------------
  echo "-- (B) validate.py ..."
  if python3 "$SCRIPT_DIR/validate.py" --config "$config"; then
    echo "  (B) PASS"
  else
    echo "  (B) FAIL — validate.py exited non-zero"
    bfail=1
  fi

  # --- pin mode: snapshot the regen output and stop ------------------------
  if [[ "$PIN" -eq 1 ]]; then
    mkdir -p "$fixture/_snapshot"
    local pinned=0 pinfail=0 stem
    while IFS= read -r stem; do
      [[ -n "$stem" ]] || continue
      if [[ ! -f "$output_dir/$stem.md" ]]; then
        echo "  MISSING regen output, cannot pin: $stem.md"; pinfail=1; continue
      fi
      if cp "$output_dir/$stem.md" "$fixture/_snapshot/$stem.md"; then
        pinned=$((pinned + 1))
      else
        echo "  cp failed while pinning: $stem.md"; pinfail=1
      fi
    done < <(regen_stems "$config")
    if [[ "$pinfail" -eq 0 ]]; then
      echo "  PINNED $pinned stems -> $fixture/_snapshot/"
    else
      echo "  PIN INCOMPLETE — $pinned pinned but some stems missing/failed; snapshot is unreliable"
    fi
    echo ""
    return "$pinfail"
  fi

  # --- signal C: per-stem diff against the chosen reference ----------------
  if [[ ! -d "$ref" ]]; then
    if [[ "$AGAINST" == snapshot ]]; then
      # No snapshot to compare against ⇒ the safety gate has nothing to
      # prove. Fail (don't silently pass) — pin one first.
      echo "  (C) FAIL — no snapshot at $ref; run 'validate_fixture.sh $book --pin' first"
      echo ""
      return 1
    fi
    echo "  (C) SKIP — baseline $ref missing"
    echo ""
    return "$bfail"
  fi
  echo "-- (C) diff regen <-> $AGAINST ($ref) ..."
  local mismatch=0 compared=0 stem
  while IFS= read -r stem; do
    [[ -n "$stem" ]] || continue
    local ref_md="$ref/$stem.md" regen_md="$output_dir/$stem.md"
    if [[ ! -f "$regen_md" ]]; then
      echo "  MISSING regen output: $stem.md"; mismatch=$((mismatch + 1)); continue
    fi
    if [[ ! -f "$ref_md" ]]; then
      echo "  no reference for: $stem.md"; mismatch=$((mismatch + 1)); continue
    fi
    compared=$((compared + 1))
    diff -q "$ref_md" "$regen_md" >/dev/null || { echo "  DIFF: $stem.md"; mismatch=$((mismatch + 1)); }
  done < <(regen_stems "$config")

  if [[ "$mismatch" -eq 0 ]]; then
    echo "  (C) PASS — $compared stems identical to $AGAINST"
  else
    if [[ "$AGAINST" == snapshot ]]; then
      echo "  (C) FAIL — $mismatch stem(s) differ from snapshot (a behavior-preserving phase must not)"
      cfail=1
    else
      echo "  (C) PARITY GAP — $mismatch/$compared stem(s) differ from worked-on baseline"
      echo "      (objective to drive down; not a hard gate — inspect: diff -u $ref/<stem>.md $output_dir/<stem>.md)"
    fi
  fi

  # --- signal D (opt-in): render-gate build smoke test ---------------------
  # Lesson 046: structural parity is not render parity — five #103-series
  # bugs were invisible to B and C and only surfaced in a real myst build.
  local dfail=0
  if [[ "$BUILD" -eq 1 ]]; then
    echo "-- (D) build smoke test (myst build vs committed baseline) ..."
    if python3 "$SCRIPT_DIR/build_smoke.py" --fixture "$fixture" \
        --check "$PROJECT_DIR/tests/baselines/build-$book.txt"; then
      echo "  (D) PASS"
    else
      echo "  (D) FAIL — new build warnings/errors vs tests/baselines/build-$book.txt"
      dfail=1
    fi
  fi

  echo ""
  # Verdict: snapshot mode is gated on byte-identity (C) alone — identical
  # output implies identical validate.py, so B is informational there.
  # Baseline (parity) mode reports B + the parity gap; B is the status signal.
  if [[ "$AGAINST" == snapshot ]]; then
    [[ "$cfail" -eq 0 && "$dfail" -eq 0 ]] && echo "  RESULT: $book behavior-preserved" || echo "  RESULT: $book REGRESSED vs snapshot"
    return $(( cfail || dfail ))
  else
    echo "  RESULT: $book validate=$([[ "$bfail" -eq 0 ]] && echo ok || echo FAIL)$([[ "$BUILD" -eq 1 ]] && { [[ "$dfail" -eq 0 ]] && echo ", build=ok" || echo ", build=FAIL"; }), parity gap above"
    return $(( bfail || dfail ))
  fi
}

TARGETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    all) TARGETS=(dp1 dp2 deep-learning) ;;
    dp1|dp2|deep-learning) TARGETS+=("$1") ;;
    --against=*) AGAINST="${1#*=}" ;;
    --against)
      [[ $# -ge 2 ]] || { echo "ERROR: --against needs a value (baseline|snapshot)" >&2; exit 2; }
      AGAINST="$2"; shift ;;
    --pin) PIN=1 ;;
    --build) BUILD=1 ;;
    -h|--help) awk 'NR==1 && /^#!/ {next} /^#/ {sub(/^# ?/,""); print; next} {exit}' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
case "$AGAINST" in
  baseline|snapshot) ;;
  *) echo "ERROR: invalid --against '$AGAINST' (use baseline|snapshot)" >&2; exit 2 ;;
esac
[[ ${#TARGETS[@]} -eq 0 ]] && { echo "Usage: validate_fixture.sh <dp1|dp2|deep-learning|all> [--against baseline|snapshot] [--pin] [--build]" >&2; exit 2; }

overall=0
for t in "${TARGETS[@]}"; do
  validate_one "$t" || overall=1
done

if [[ "$AGAINST" == snapshot && "$PIN" -eq 0 ]]; then
  [[ "$overall" -eq 0 ]] && echo "ALL REQUESTED FIXTURES BEHAVIOR-PRESERVED (== snapshot)." \
                         || echo "ONE OR MORE FIXTURES REGRESSED vs snapshot (see above)."
fi
exit "$overall"
