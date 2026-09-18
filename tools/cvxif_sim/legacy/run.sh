#!/usr/bin/env bash
# End-to-end CV-X-IF simulation: run a real RISC-V program on an unmodified
# CV32E40X with a Longnail-generated ISAX attached over the eXtension interface.
#
#   tools/cvxif_sim/run.sh <dir-with-ISAX_<name>.{yaml,sv}> [<name>]
#
# Uses gen_test_<name>.py if present, else gen_test.py (which targets `sparkle`).
# Pointing this at an ISAX with no program of its own needs one written; the
# protocol-only testbench emitted by `cvxif_glue_gen.py --testbench` covers any
# ISAX without one.
set -euo pipefail

NG="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="$NG/tools/cvxif_sim"          # tops + null coprocessors (still in use)
LEGACY="$HERE/legacy"               # this runner, its testbench and test generators
SRC_DIR="${1:?usage: run.sh <isax-output-dir> [isax-name]}"
SRC_DIR="$(cd "$SRC_DIR" && pwd)"        # everything below runs from $WORK
NAME="${2:-sparkle}"
CORE="${CORE:-$NG/deps/cv32e40x}"   # pristine upstream openhwgroup/cv32e40x
WORK="${WORK:-$SRC_DIR/cvxif_sim}"

CLANG="$NG/deps/llvm_dynamic_isax/build/bin/clang"
OBJCOPY="$NG/deps/llvm_dynamic_isax/build/bin/llvm-objcopy"
LLD="${LLD:-$(command -v ld.lld || ls /nix/store/*/bin/ld.lld 2>/dev/null | head -1)}"

# The core needs upstream's unmerged XIF writeback fix (openhwgroup/cv32e40x
# issue #941 / PR #891). Apply it if the checkout does not already have it.
PATCH="$NG/core_patches/cv32e40x_xif_sticky_issue_resp.patch"
if git -C "$CORE" apply --check --reverse "$PATCH" >/dev/null 2>&1; then
  echo "core: XIF sticky-issue_resp fix already applied"
elif git -C "$CORE" apply "$PATCH" >/dev/null 2>&1; then
  echo "core: applied $PATCH"
else
  echo "core: WARNING could not apply $PATCH -- offloaded instructions that" >&2
  echo "      stall in ID will lose their register writeback (upstream #941)" >&2
fi

mkdir -p "$WORK"
cd "$WORK"

# 1. glue + cv32e40x_if_xif wrapper for the generated ISAX.
#    SPECULATIVE=1 admits at the issue handshake instead of at the commit
#    (needs an ISAX with no custom registers).
# Speculative admission is the generator's default now; SPECULATIVE=0 forces the
# commit-gated build. GLUE_FLAGS passes anything else through (e.g. --ooo-result,
# --no-input-buffer) so the optimizations can be simulated without editing this script.
GLUE_FLAGS="${GLUE_FLAGS:-}"
[ "${SPECULATIVE:-1}" = "0" ] && GLUE_FLAGS="$GLUE_FLAGS --non-speculative"
python3 "$NG/tools/cvxif_glue_gen.py" $GLUE_FLAGS "$SRC_DIR/ISAX_$NAME.yaml" -o "$WORK"

# 2. test program + golden values. An ISAX-specific generator gets the ISAX's
#    CoreDSL -> Python model (emitted by -coredsl-to-python) as its reference.
#    CVXIF_TESTGEN=<file in this dir> overrides the by-name choice (the benchmark
#    harness runs gen_test_merged.py against a DOTP-only design too).
GEN="$LEGACY/${CVXIF_TESTGEN:-gen_test_$(echo "$NAME" | tr '[:upper:]' '[:lower:]').py}"
if [ -f "$GEN" ]; then
  # MODEL_DIR: where the CoreDSL->Python golden model (<NAME>.py) lives.
  # Defaults to the ISAX output dir; phase-B (SOLUTION_MLIR) eval runs skip
  # the transpile, so their caller points this at a baseline dir instead.
  python3 "$GEN" "$CLANG" "$LLD" "$OBJCOPY" "${MODEL_DIR:-$SRC_DIR}"
else
  python3 "$LEGACY/gen_test.py" "$CLANG" "$LLD" "$OBJCOPY"
fi

# 3. core file list from the vendored manifest
python3 - "$CORE" <<'EOF'
import sys, os
core = sys.argv[1]
inc, src = [], []
for l in open(os.path.join(core, "cv32e40x_manifest.flist")):
    l = l.strip().replace("${DESIGN_RTL_DIR}", os.path.join(core, "rtl"))
    if not l or l.startswith("//"):      continue
    if l.startswith("+incdir+"):         inc.append(l[8:])
    elif l.startswith("+"):              continue
    else:                                src.append(l)
open("core_srcs.txt", "w").write("\n".join(src) + "\n")
open("core_incs.txt", "w").write("\n".join("-I" + i for i in inc) + "\n")
EOF

ISAX_SV=$(ls "$SRC_DIR"/ISAX_$NAME.sv)
# `|| true`: with `set -o pipefail` a glob that matches nothing makes ls exit 2
# and takes the whole script down (ISAXes without split-datapath operators).
EXTRA=$(ls "$SRC_DIR"/split*.sv "$SRC_DIR"/splitop_*.sv 2>/dev/null | tr '\n' ' ' || true)

build_and_run () {          # $1 = coproc module, $2 = obj dir, $3 = binary
  rm -rf "$2"
  verilator --binary --timing -Wno-fatal -j 8 \
    $(tr '\n' ' ' < core_incs.txt) -DCOREV_ASSERT_OFF "-DCVXIF_COPROC=$1" \
    --top-module tb_e40x -o "$3" --Mdir "$2" \
    "$LEGACY/tb_e40x.sv" "$HERE/cvxif_e40x_top.sv" "$HERE/cvxif_coproc_null.sv" \
    "cvxif_coproc_$NAME.sv" "cvxif_glue_$NAME.sv" "$ISAX_SV" $EXTRA \
    $(tr '\n' ' ' < core_srcs.txt) > verilate_$3.log 2>&1
  # CVXIF_MAX_CYCLES=N lifts the testbench's 200k-cycle completion timeout.
  "./$2/$3" ${CVXIF_MAX_CYCLES:+"+max_cycles=$CVXIF_MAX_CYCLES"}
}

echo "=== CV32E40X + cvxif_coproc_$NAME ==="
build_and_run "cvxif_coproc_$NAME" obj_cvxif vsim

echo
echo "=== negative control: coprocessor claims nothing (must FAIL) ==="
if build_and_run cvxif_coproc_null obj_null vnull > /dev/null 2>&1; then
  echo "NEGATIVE CONTROL DID NOT FAIL -- the test is not actually exercising the ISAX"
  exit 1
fi
echo "negative control failed as expected"
