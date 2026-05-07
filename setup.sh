#!/usr/bin/env bash
# Prepare a standalone deps/ tree for nailgun.
#
# Use this when the repository is cloned outside of the
# isax-tools-integration meta-repo. Inside the meta-repo, deps/ is a
# symlink to ../deps/ (the meta-repo's own deps directory of pinned
# submodules); this script replaces that symlink with a real directory
# and clones the currently open-sourced tools.
#
# Note: longnail and splitop-gen are closed-source; the CoreDSL-driven
# HLS path therefore can't run from this repository alone. This script
# sets up everything that is publicly available so the SV-entrypoint,
# no-ISAX, and ONLY_PATCH_CC flows work standalone.
#
# Environment knobs:
#   BUILD=0                  Skip every heavy build (just clone + init submodules)
#   SKIP_YOSYS_SLANG=1       Skip yosys-slang entirely

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPS_DIR="$SCRIPT_DIR/deps"

: "${BUILD:=1}"

# 1. Replace the meta-repo symlink (deps -> ../deps/) with a real dir.
if [[ -L "$DEPS_DIR" ]]; then
    target=$(readlink "$DEPS_DIR")
    echo ">>> Removing deps symlink ($DEPS_DIR -> $target)"
    rm "$DEPS_DIR"
fi
mkdir -p "$DEPS_DIR"

# 2. git-lfs is harmless if no LFS files exist; skip silently if missing.
if command -v git-lfs >/dev/null 2>&1; then
    git lfs install >/dev/null
fi

clone_or_update() {
    local url=$1
    local dst=$2
    if [[ -d "$dst/.git" ]]; then
        echo ">>> Updating $dst"
        git -C "$dst" fetch --tags origin
        if git -C "$dst" symbolic-ref -q HEAD >/dev/null \
           && git -C "$dst" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
            git -C "$dst" pull --ff-only
        else
            echo "    (skipping pull: detached HEAD or no upstream)"
        fi
    elif [[ -e "$dst" ]]; then
        echo ">>> Skipping $dst (exists, not a git checkout)"
        return 1
    else
        echo ">>> Cloning $url -> $dst"
        git clone "$url" "$dst"
    fi
}

setup_treenail() {
    local d="$DEPS_DIR/treenail"
    clone_or_update https://github.com/esa-tu-darmstadt/Treenail.git "$d" || return 0
    git -C "$d" submodule update --init
    if [[ "$BUILD" != "0" ]]; then
        ( cd "$d" && gradle build && gradle test && gradle install )
    fi
}

setup_shortnail() {
    local d="$DEPS_DIR/shortnail"
    clone_or_update https://github.com/esa-tu-darmstadt/Shortnail.git "$d" || return 0
    git -C "$d" submodule update --init --recursive --depth 1
    if [[ "$BUILD" != "0" ]]; then
        (
            cd "$d"
            OR_TOOLS_VER="9.11" ./build_deps.sh
            # Strip INTERFACE_POSITION_INDEPENDENT_CODE from OR-Tools/HiGHS exports
            # so it doesn't propagate -fPIE into CIRCT executables and break PCH
            # reuse against LLVMSupport (built -fPIC, no PIE). See parent
            # build_shortnail.sh for the full rationale.
            sed -i '/INTERFACE_POSITION_INDEPENDENT_CODE/d' \
                circt/ext/lib64/cmake/ortools/ortoolsTargets.cmake \
                circt/ext/lib64/cmake/highs/highs-targets.cmake
            ./build_circt.sh
            ./build_shortnail.sh
        )
    fi
}

setup_scaiev() {
    local d="$DEPS_DIR/scaie-v"
    clone_or_update https://github.com/esa-tu-darmstadt/SCAIE-V-2.0.git "$d" || return 0
    # Six core submodules on the scalv2 branch: VexRiscv, Piccolo, PicoRV32,
    # ORCA, CVA5, CVA6. A single top-level init pulls them all.
    git -C "$d" submodule update --init
    # CVA6 has its own nested submodules; init only the ones the build needs.
    (
        cd "$d/CoresSrc/CVA6"
        git submodule update --init core/cache_subsystem/hpdcache
        git submodule update --init --recursive core/cvfpu
        git submodule update --init --recursive corev_apu/riscv-dbg
        git submodule update --init --recursive corev_apu/rv_plic
        git submodule update --init --recursive corev_apu/axi_mem_if
        git submodule update --init --recursive corev_apu/register_interface
    )
    # SCAIE-V's Java jar is built lazily by scaiev.py the first time the
    # pipeline runs (unless SCAIEV_DO_NOT_REBUILD=y), so no build step here.
}

setup_llvm_dynamic_isax() {
    # No submodules; toolchain.prepare_dynamic_isax_llvm() configures and
    # builds the fork on first use. Just clone.
    clone_or_update https://github.com/esa-tu-darmstadt/llvm_dynamic_isax.git \
        "$DEPS_DIR/llvm_dynamic_isax" || return 0
}

setup_yosys_slang() {
    if [[ -n "${SKIP_YOSYS_SLANG+x}" ]]; then
        echo ">>> Skipping yosys-slang (SKIP_YOSYS_SLANG set)"
        return 0
    fi
    local d="$DEPS_DIR/yosys-slang"
    clone_or_update https://github.com/povik/yosys-slang.git "$d" || return 0
    git -C "$d" submodule update --init --recursive third_party/slang
    if [[ "$BUILD" != "0" ]]; then
        ( cd "$d" && make -j"$(nproc)" )
    fi
}

setup_treenail
setup_shortnail
setup_scaiev
setup_llvm_dynamic_isax
setup_yosys_slang

cat <<EOF

setup.sh: deps/ is prepared with the currently open-sourced tools:
  - deps/treenail
  - deps/shortnail
  - deps/scaie-v
  - deps/llvm_dynamic_isax
  - deps/yosys-slang

Closed-source pieces (longnail, splitop-gen) are not distributed
publicly, so the CoreDSL-driven HLS path is not available here. The
SV-entrypoint, no-ISAX, and ONLY_PATCH_CC flows work without them.
To run nailgun from inside the isax-tools-integration meta-repo,
restore the deps symlink:

    rm -rf deps && ln -s ../deps deps

EOF
