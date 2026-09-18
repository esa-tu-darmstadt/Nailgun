#!/usr/bin/env bash
# End-to-end CV-X-IF simulation on CV32E40PX: run a real RISC-V program on an
# unmodified upstream CV32E40PX with a Longnail-generated ISAX on the interface.
#
#   tools/cvxif_sim/run_e40px.sh <dir-with-ISAX_<name>.{yaml,sv}> [<name>]
#
# Which core this is: x-heep/cv32e40px, the CV32E40P derivative that adds
# CV-X-IF (plus RVB/RVP/RVK). Not CV32E40P, which has no X-interface, and not
# CV32E40X, which is a different core. It implements the *same* interface
# revision as CV32E40X but packages it as structs in cv32e40px_core_v_xif_pkg,
# so the only new piece is the wrapper (`--e40px-wrapper`); the memory map,
# testbench and test programs are CV32E40X's unchanged.
set -euo pipefail

NG="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="$NG/tools/cvxif_sim"          # tops + null coprocessors (still in use)
LEGACY="$HERE/legacy"               # this runner, its testbench and test generators
SRC_DIR="${1:?usage: run_e40px.sh <isax-output-dir> [isax-name]}"
SRC_DIR="$(cd "$SRC_DIR" && pwd)"        # everything below runs from $WORK
NAME="${2:-sparkle}"
CORE="${CORE:-$NG/deps/cv32e40px}"       # pristine upstream x-heep/cv32e40px
WORK="${WORK:-$SRC_DIR/cvxif_sim_e40px}"

CLANG="$NG/deps/llvm_dynamic_isax/build/bin/clang"
OBJCOPY="$NG/deps/llvm_dynamic_isax/build/bin/llvm-objcopy"
LLD="${LLD:-$(command -v ld.lld || ls /nix/store/*/bin/ld.lld 2>/dev/null | head -1)}"

[ -d "$CORE/rtl" ] || { echo "no CV32E40PX checkout at $CORE" >&2; exit 2; }

# The core hands the ALU write port to the coprocessor unconditionally and drops its
# OWN writeback when both want it in the same cycle (it notices -- `wb_contention` --
# but that drives only a performance counter). Applied in place, like run.sh does for
# CV32E40X's #941 fix, so the copy cvxif.py takes for synthesis inherits it and the
# simulated and synthesized cores stay identical.
PATCH="$NG/core_patches/cv32e40px_xif_wb_priority.patch"
if git -C "$CORE" apply --check --reverse "$PATCH" >/dev/null 2>&1; then
  echo "core: XIF writeback-priority fix already applied"
elif git -C "$CORE" apply "$PATCH" >/dev/null 2>&1; then
  echo "core: applied $PATCH"
else
  echo "core: WARNING could not apply $PATCH -- a coprocessor result landing on the" >&2
  echo "      same cycle as a core writeback will silently drop the core's write" >&2
fi

mkdir -p "$WORK"
cd "$WORK"

# 1. glue + CV32E40PX wrapper for the generated ISAX.
python3 "$NG/tools/cvxif_glue_gen.py" --e40px-wrapper --no-wrapper \
        "$SRC_DIR/ISAX_$NAME.yaml" -o "$WORK"

# 2. test program + golden values (CV32E40X's memory map: boot 0x80, 32-bit mem).
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

# 3. core sources. Both of the repo's manifests (Bender.yml, src_files.yml) are
#    stale -- they still list the pre-rename cv32e40p_* files -- so glob the RTL,
#    packages first. The register file has an ff and a latch variant; take ff.
python3 - "$CORE" <<'EOF'
import glob, os, sys
core = sys.argv[1]
inc  = [os.path.join(core, "rtl", "include")]
pkgs = sorted(glob.glob(os.path.join(core, "rtl", "include", "*.sv")))
skip = (
    # Two register-file variants ship; take the flop one.
    "cv32e40px_register_file_latch.sv",
    # Instantiated only inside `generate if (FPU)`, and we build with FPU = 0.
    # It imports fpnew_pkg, so compiling it would drag in the whole vendored
    # pulp-platform FPU for a block that is never elaborated.
    "cv32e40px_fp_wrapper.sv",
)
rtl  = sorted(f for f in glob.glob(os.path.join(core, "rtl", "*.sv"))
              if not f.endswith(skip))
# cv32e40px_top instantiates the clock gate; the behavioural one is the only
# implementation shipped.
bhv  = [os.path.join(core, "bhv", "cv32e40px_sim_clock_gate.sv")]
srcs = pkgs + rtl + bhv
missing = [s for s in srcs if not os.path.isfile(s)]
if missing:
    print("missing sources:\n  " + "\n  ".join(missing), file=sys.stderr)
    sys.exit(1)
open("core_srcs.txt", "w").write("\n".join(srcs) + "\n")
open("core_incs.txt", "w").write("\n".join("-I" + i for i in inc) + "\n")
print(f"cv32e40px file list: {len(srcs)} sources")
EOF

ISAX_SV=$(ls "$SRC_DIR"/ISAX_$NAME.sv)
# `|| true`: with `set -o pipefail` a glob that matches nothing makes ls exit 2.
EXTRA=$(ls "$SRC_DIR"/split*.sv "$SRC_DIR"/splitop_*.sv 2>/dev/null | tr '\n' ' ' || true)

build_and_run () {          # $1 = coproc module, $2 = obj dir, $3 = binary
  rm -rf "$2"
  verilator --binary --timing -Wno-fatal -j 8 \
    $(tr '\n' ' ' < core_incs.txt) "-DCVXIF_COPROC=$1" \
    --top-module tb_e40px -o "$3" --Mdir "$2" \
    $(tr '\n' ' ' < core_srcs.txt) \
    "$LEGACY/tb_e40px.sv" "$HERE/cvxif_e40px_top.sv" "$HERE/cvxif_coproc_e40px_null.sv" \
    "cvxif_coproc_e40px_$NAME.sv" "cvxif_glue_$NAME.sv" "$ISAX_SV" $EXTRA \
    > "verilate_$3.log" 2>&1
    # Core sources come first: the wrappers `import cv32e40px_core_v_xif_pkg::*`
    # in their headers, and Verilator resolves package types in file order.
  # CVXIF_MAX_CYCLES=N lifts the testbench's 200k-cycle completion timeout.
  "./$2/$3" ${CVXIF_MAX_CYCLES:+"+max_cycles=$CVXIF_MAX_CYCLES"}
}

echo "=== CV32E40PX + cvxif_coproc_e40px_$NAME ==="
build_and_run "cvxif_coproc_e40px_$NAME" obj_cvxif vsim

echo
echo "=== negative control: coprocessor claims nothing (must FAIL) ==="
if build_and_run cvxif_coproc_e40px_null obj_null vnull > /dev/null 2>&1; then
  echo "NEGATIVE CONTROL DID NOT FAIL -- the test is not actually exercising the ISAX"
  exit 1
fi
echo "negative control failed as expected"
