#!/usr/bin/env bash
# End-to-end CV-X-IF simulation on CVA6: run a real RISC-V program on an
# unmodified upstream CVA6 with a Longnail-generated ISAX attached over the
# eXtension interface.
#
#   tools/cvxif_sim/run_cva6.sh <dir-with-ISAX_<name>.{yaml,sv}> [<name>]
#
# The CV32E40X twin of this script is run.sh. Differences, all of them coming
# from CVA6 speaking CV-X-IF v1.0 rather than rev 458c8a73:
#
#   * the coprocessor wrapper is cvxif_coproc_cva6_<name> (struct ports, source
#     operands on the register channel) -- see cvxif_glue_gen.py --cva6-wrapper
#   * CVA6 boots at 0x8000_0000 and hangs off 64-bit AXI, so the test program is
#     relinked there and the memory image is emitted as doublewords
#   * no core patch is needed: CVA6 needs nothing beyond its own upstream RTL
set -euo pipefail

NG="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="$NG/tools/cvxif_sim"          # tops + null coprocessors (still in use)
LEGACY="$HERE/legacy"               # this runner, its testbench and test generators
SRC_DIR="${1:?usage: run_cva6.sh <isax-output-dir> [isax-name]}"
SRC_DIR="$(cd "$SRC_DIR" && pwd)"        # everything below runs from $WORK
NAME="${2:-sparkle}"
CORE="${CORE:-$NG/deps/cva6_upstream}"   # pristine upstream openhwgroup/cva6
WORK="${WORK:-$SRC_DIR/cvxif_sim_cva6}"
TARGET_CFG="${TARGET_CFG:-cv32a60x}"     # rv32, no MMU, CvxifEn = 1 upstream

CLANG="$NG/deps/llvm_dynamic_isax/build/bin/clang"
OBJCOPY="$NG/deps/llvm_dynamic_isax/build/bin/llvm-objcopy"
LLD="${LLD:-$(command -v ld.lld || ls /nix/store/*/bin/ld.lld 2>/dev/null | head -1)}"

[ -d "$CORE/core" ] || { echo "no CVA6 checkout at $CORE" >&2; exit 2; }

mkdir -p "$WORK"
cd "$WORK"

# 1. glue + CVA6 (v1.0) wrapper for the generated ISAX.
#    ALLOW_CUSTOM_REGS=1 reproduces the double-execution finding on an ISAX with
#    custom registers (ANTDOTP); the generator refuses such ISAXes by default.
GLUE_FLAGS=""
[ "${ALLOW_CUSTOM_REGS:-0}" = "1" ] && GLUE_FLAGS="--allow-custom-regs"
python3 "$NG/tools/cvxif_glue_gen.py" --cva6-wrapper --no-wrapper $GLUE_FLAGS \
        "$SRC_DIR/ISAX_$NAME.yaml" -o "$WORK"

# 2. test program + golden values, relinked for CVA6's memory map.
export CVXIF_TEXT_BASE=0x80000000
export CVXIF_MEM_BASE=0x80000000
export CVXIF_MMIO_BASE=0x10000000
export CVXIF_STACK_TOP=0x80040000
export CVXIF_RESULT_BASE=0x80050000       # RESULT_IN_MEM tests: must be in RAM
export CVXIF_HEX_WIDTH=64
GEN="$LEGACY/gen_test_$(echo "$NAME" | tr '[:upper:]' '[:lower:]').py"
if [ -f "$GEN" ]; then
  # MODEL_DIR: where the CoreDSL->Python golden model (<NAME>.py) lives.
  # Defaults to the ISAX output dir; phase-B (SOLUTION_MLIR) eval runs skip
  # the transpile, so their caller points this at a baseline dir instead.
  python3 "$GEN" "$CLANG" "$LLD" "$OBJCOPY" "${MODEL_DIR:-$SRC_DIR}"
else
  python3 "$LEGACY/gen_test.py" "$CLANG" "$LLD" "$OBJCOPY"
fi

# 3. core file list, from CVA6's own manifest (core/Flist.cva6). It uses
#    ${CVA6_REPO_DIR}/${HPDCACHE_DIR}/${TARGET_CFG} and nests further lists with
#    -F, so expand it properly rather than guessing a source list.
CVA6_REPO_DIR="$CORE" HPDCACHE_DIR="$CORE/core/cache_subsystem/hpdcache" \
TARGET_CFG="$TARGET_CFG" python3 - <<'EOF'
import os, re, sys

env = {"CVA6_REPO_DIR": os.environ["CVA6_REPO_DIR"],
       "HPDCACHE_DIR":  os.environ["HPDCACHE_DIR"],
       "TARGET_CFG":    os.environ["TARGET_CFG"]}
srcs, incs, defines = [], [], []

def expand(s):
    return re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), s)

def read(path):
    with open(path) as f:
        lines = f.read().splitlines()
    i = 0
    while i < len(lines):
        l = expand(lines[i].strip())
        i += 1
        if not l or l.startswith("//") or l.startswith("#"):
            continue
        if l.startswith("+incdir+"):
            incs.append(l[len("+incdir+"):].rstrip("/"))
        elif l.startswith("+define+"):
            defines.extend(d for d in l[len("+define+"):].split("+") if d)
        elif l.startswith("-F ") or l.startswith("-f "):
            read(l[3:].strip())
        elif l.startswith("+") or l.startswith("-"):
            continue                      # other simulator options: ignore
        else:
            if l not in srcs:
                srcs.append(l)

read(os.path.join(env["CVA6_REPO_DIR"], "core", "Flist.cva6"))

# The core manifest is core-only; the AXI struct types the top uses live in the
# APU testbench package.
srcs.insert(srcs.index(os.path.join(env["CVA6_REPO_DIR"], "core/include/build_config_pkg.sv")) + 1,
            os.path.join(env["CVA6_REPO_DIR"], "corev_apu/tb/ariane_axi_pkg.sv"))

missing = [s for s in srcs if not os.path.isfile(s)]
if missing:
    print("missing sources:\n  " + "\n  ".join(missing), file=sys.stderr)
    sys.exit(1)

open("core_srcs.txt", "w").write("\n".join(srcs) + "\n")
open("core_incs.txt", "w").write("\n".join("-I" + i for i in incs) + "\n")
open("core_defs.txt", "w").write("\n".join("-D" + d for d in defines) + "\n")
print(f"cva6 file list: {len(srcs)} sources, {len(incs)} include dirs")
EOF

ISAX_SV=$(ls "$SRC_DIR"/ISAX_$NAME.sv)
# `|| true`: with `set -o pipefail` a glob that matches nothing makes ls exit 2
# and takes the whole script down. ISAXes without split-datapath operators (any
# ISAX with no shared multiplier, sparkle included) match nothing here.
EXTRA=$(ls "$SRC_DIR"/split*.sv "$SRC_DIR"/splitop_*.sv 2>/dev/null | tr '\n' ' ' || true)

build_and_run () {          # $1 = coproc module, $2 = obj dir, $3 = binary
  rm -rf "$2"
  verilator --binary --timing -Wno-fatal -j 8 \
    $(tr '\n' ' ' < core_incs.txt) $(tr '\n' ' ' < core_defs.txt) \
    "-DCVXIF_COPROC=$1" \
    --top-module tb_cva6 -o "$3" --Mdir "$2" \
    "$LEGACY/tb_cva6.sv" "$HERE/cvxif_cva6_top.sv" "$HERE/cvxif_coproc_cva6_null.sv" \
    "cvxif_coproc_cva6_$NAME.sv" "cvxif_glue_$NAME.sv" "$ISAX_SV" $EXTRA \
    $(tr '\n' ' ' < core_srcs.txt) > "verilate_$3.log" 2>&1
  "./$2/$3"
}

echo "=== CVA6 ($TARGET_CFG) + cvxif_coproc_cva6_$NAME ==="
build_and_run "cvxif_coproc_cva6_$NAME" obj_cvxif vsim

echo
echo "=== negative control: coprocessor claims nothing (must FAIL) ==="
if build_and_run cvxif_coproc_cva6_null obj_null vnull > /dev/null 2>&1; then
  echo "NEGATIVE CONTROL DID NOT FAIL -- the test is not actually exercising the ISAX"
  exit 1
fi
echo "negative control failed as expected"
