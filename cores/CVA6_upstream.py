import os
import re

from cvxif import CVXIFCoreSupport
from scaiev import CoreExtensions

# Pristine upstream openhwgroup/cva6, attached over CV-X-IF instead of SCAIE-V.
#
# `cores/CVA6.py` registers the SCAIE-V fork (`deps/scaie-v/CoresSrc/CVA6`,
# branched off upstream bcb0f7de with 20-odd files modified and four added). This
# module registers the *unmodified* upstream tree at `deps/cva6_upstream` -- the
# same commit, no SCAIE-V patches -- which reaches an ISAX only through the
# standard CV-X-IF `cvxif_req_o`/`cvxif_resp_i` ports.
#
# `make ci` runs cvxif.run_cvxif(), which populates the output tree with the
# copied core, the generated glue + the CV-X-IF v1.0 translation wrapper
# (`--cva6-wrapper`; CVA6 speaks v1.0, not rev 458c8a73), the top and a
# filelist.f. The datasheet is CVXIF.yaml, the interface datasheet, not a
# pipeline model of CVA6 -- the ISAX schedules against the handshakes.
#
# CVA6 hardwires `commit.commit_kill = 0`, so ISAXes with custom registers
# double-execute on a flush; the glue generator refuses them unless
# CVXIF_ALLOW_CUSTOM_REGS=y. See docs/cvxif.md.
#
# Simulation is the regular cocotb flow, through
# `tools/cvxif_sim/cvxif_cva6_tb_wrapper.sv`:
#
#   CORE=CVA6_UPSTREAM ISAXES=SPARKLE SIM_ENABLE=y \
#     TB_PATH=custom_tbs/sparkle.cpp TB_EXPECTED_PATH=custom_tbs/sparkle_expected.txt make ci

CVA6_UPSTREAM_DIR = os.path.join("deps", "cva6_upstream")

# rv32, no MMU, and -- the reason this config is the one we build -- CvxifEn is
# already 1 upstream, so the core needs no edit at all to expose the interface.
TARGET_CFG = "cv32a60x"


class CVA6UpstreamSupport(CVXIFCoreSupport):
    def copy_blacklist(self) -> list[str]:
        return [
            os.path.join(CVA6_UPSTREAM_DIR, p)
            for p in ("ci", "docs", ".git", ".github", ".gitlab-ci", "pd",
                      "spyglass", "util", "verif")
        ]

    def get_srcs_folder_name(self) -> str:
        return "CVA6_upstream"

    def get_extensions(self) -> CoreExtensions:
        # cv32a60x: RV32 with M and C (RVA is 0, so no atomics).
        return CoreExtensions(['I', 'M', 'C', 'Zicsr'], "ilp32", 32)

    def get_linker_file(self) -> str:
        return self._get_linker_file("CVA6")

    def get_specific_startup_file(self) -> str:
        return self._get_specific_startup_file("CVA6")

    # ---- CV-X-IF hooks ----------------------------------------------------

    def get_upstream_core_dir(self) -> str:
        return CVA6_UPSTREAM_DIR

    def cvxif_glue_args(self) -> list[str]:
        # CVA6 speaks CV-X-IF v1.0: struct ports, operands on the register
        # channel. --no-wrapper drops the (useless here) cv32e40x_if_xif one.
        return ["--cva6-wrapper", "--no-wrapper"]

    def get_top_files(self) -> list[str]:
        return [os.path.join("tools", "cvxif_sim", "cvxif_cva6_top.sv")]

    def get_tb_wrapper_files(self) -> list[str]:
        # Same `testbench` AXI4 ports as SCAIE-V's CVA6_tb_wrapper.v.
        return [os.path.join("tools", "cvxif_sim", "cvxif_cva6_tb_wrapper.sv")]

    def get_tb_env_vars(self, kconf_syms) -> list[str]:
        # The memory map sim/linker_scripts/CVA6_link.ld is written for
        # (cores/CVA6.py).
        return [
            "NUM_BUSSI=1",
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_ctrl",
            "IMEM_BUSIDX=0",
            "IMEM_BASE=80000000",
            "EXCEPTION_BASE=808",
            "DMEM_BUSIDX=0",
            "DMEM_BASE=80100000",
            "DMEM_SIZE=00100000",
            "CTRL_BUSIDX=0",
            "CTRL_BASE=60000000",
            # The frontend fetches speculatively past the program.
            "ALLOW_SPECULATIVE_READS=1",
        ]

    def get_sim_makefile_args(self) -> dict[str, str]:
        return {
            "verilator": """
# Mute some verilator warnings
EXTRA_ARGS+=-Wno-BLKANDNBLK -Wno-fatal
"""
        }

    def get_cvxif_core_filelist(self, core_dir):
        """Expand CVA6's own manifest (`core/Flist.cva6`). It uses
        ${CVA6_REPO_DIR}/${HPDCACHE_DIR}/${TARGET_CFG} and nests further lists
        with -F, so expand it properly rather than guessing a source list."""
        env = {"CVA6_REPO_DIR": core_dir,
               "HPDCACHE_DIR": os.path.join(core_dir, "core", "cache_subsystem", "hpdcache"),
               "TARGET_CFG": TARGET_CFG}
        srcs, incs, defines = [], [], []

        def expand(s):
            return re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), s)

        def read(path):
            with open(path) as f:
                lines = f.read().splitlines()
            for raw in lines:
                l = expand(raw.strip())
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
                elif l not in srcs:
                    srcs.append(l)

        read(os.path.join(core_dir, "core", "Flist.cva6"))

        # The core manifest is core-only; the AXI struct types the top uses
        # live in the APU testbench package.
        srcs.insert(srcs.index(os.path.join(core_dir, "core/include/build_config_pkg.sv")) + 1,
                    os.path.join(core_dir, "corev_apu/tb/ariane_axi_pkg.sv"))

        rel = lambda paths: [os.path.relpath(p, core_dir) for p in paths]
        return rel(srcs), rel(incs), defines


def get_supported_cores():
    return [("CORE_CVA6_UPSTREAM", "CVA6_upstream", CVA6UpstreamSupport())]
