import os

from cvxif import CVXIFCoreSupport
from scaiev import CoreExtensions

# CV32E40X (openhwgroup/cv32e40x), attached over CV-X-IF instead of SCAIE-V.
#
# `cores/CV32E40_.py` already registers CORE_CV32E40X, but that entry is the
# SCAIE-V fork (`deps/scaie-v/CoresSrc/CV32E40X`) with its pipeline datasheet
# (CV32E40X.yaml): SCAIE-V splices the ISAX into the core. This entry is the
# alternative: **pristine upstream** `deps/cv32e40x` (master HEAD d952cd63, no
# scaiev_interface hooks) with the ISAX arriving as a coprocessor over the
# core's own eXtension interface, so its datasheet is CVXIF.yaml.
#
# `make ci` runs cvxif.run_cvxif(), which populates the output tree with the
# copied (and patched) core, the generated glue + `cv32e40x_if_xif` wrapper,
# the top and a filelist.f. Simulation is the regular cocotb flow, through
# `tools/cvxif_sim/cvxif_e40x_tb_wrapper.sv`:
#
#   CORE=CV32E40X_UPSTREAM ISAXES=SPARKLE SIM_ENABLE=y \
#     TB_PATH=custom_tbs/sparkle.cpp TB_EXPECTED_PATH=custom_tbs/sparkle_expected.txt make ci

CV32E40X_UPSTREAM_DIR = os.path.join("deps", "cv32e40x")


class CV32E40XUpstreamSupport(CVXIFCoreSupport):
    def copy_blacklist(self) -> list[str]:
        # sva/ stays: the manifest +incdir+'s it (harmless with
        # COREV_ASSERT_OFF, but the filelist should not dangle).
        return [os.path.join(CV32E40X_UPSTREAM_DIR, p)
                for p in (".git", ".github", "docs")]

    def get_srcs_folder_name(self) -> str:
        return "CV32E40X_upstream"

    def get_extensions(self) -> CoreExtensions:
        # Matches the SCAIE-V CV32E40X entry and the rv32im_zicsr march the
        # cvxif_sim test programs are built with.
        return CoreExtensions(['I', 'M', 'Zicsr'], "ilp32", 32)

    def get_linker_file(self) -> str:
        return self._get_linker_file("CV32E40X")

    def get_specific_startup_file(self) -> str:
        return self._get_specific_startup_file("CV32E40X")

    # ---- CV-X-IF hooks ----------------------------------------------------

    def get_upstream_core_dir(self) -> str:
        return CV32E40X_UPSTREAM_DIR

    def cvxif_glue_args(self) -> list[str]:
        # Default flavor: glue + the `cv32e40x_if_xif` interface wrapper.
        return []

    def get_core_patches(self) -> list[str]:
        # Upstream's unmerged XIF writeback fix (issue #941 / PR #891): the
        # issue_resp flags are not sticky, so an offloaded instruction
        # lingering in ID loses its register writeback.
        #
        # And the result handshake ignored wb_ready: with a memory slower than
        # one cycle, a load/store parked in EX behind an offloaded instruction
        # deadlocks the core (see the patch header).
        return [os.path.join("core_patches", "cv32e40x_xif_sticky_issue_resp.patch"),
                os.path.join("core_patches", "cv32e40x_xif_result_ready_wb.patch")]

    def get_top_files(self) -> list[str]:
        return [os.path.join("tools", "cvxif_sim", "cvxif_e40x_top.sv")]

    def get_null_coproc_file(self) -> str:
        return os.path.join("tools", "cvxif_sim", "cvxif_coproc_null.sv")

    def get_tb_wrapper_files(self) -> list[str]:
        # Same `testbench` ports as SCAIE-V's cv32e40x_tb_wrapper.v, whose
        # OBI->AXI4 adapter it reuses.
        return [os.path.join("tools", "cvxif_sim", "cvxif_e40x_tb_wrapper.sv"),
                os.path.join("deps", "scaie-v", "util", "maketop", "obi_axi_adapter.sv")]

    def get_tb_env_vars(self, kconf_syms) -> list[str]:
        # The memory map of the SCAIE-V CV32E40X (cores/CV32E40_.py), which
        # sim/linker_scripts/CV32E40X_link.ld is written for.
        return [
            "NUM_BUSSI=2",
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            "IMEM_BUSIDX=0",
            "IMEM_BASE=80000000",
            # cvxif_e40x_top ties mtvec_addr_i to 0.
            "EXCEPTION_BASE=00000000",
            "DMEM_BUSIDX=1",
            "DMEM_BASE=80100000",
            "DMEM_SIZE=00100000",
            "CTRL_BUSIDX=1",
            "CTRL_BASE=80200000",
        ]

    def get_sim_makefile_args(self) -> dict[str, str]:
        return {
            "verilator": """
# Verilator throws lots of warnings on the core. Ignoring some of them.
EXTRA_ARGS+=-Wno-WIDTHEXPAND -Wno-LITENDIAN -Wno-WIDTHTRUNC -Wno-BLKANDNBLK
"""
        }

    def filter_synthesis_core_srcs(self, core_srcs, core_dir) -> list[str]:
        # The upstream manifest lists the same simulation-only RVFI files as
        # the SCAIE-V fork's (unsynthesizable: `parameter string` in
        # cv32e40x_rvfi_sim_trace.sv). No maketop top / scaiev wrapper here,
        # so only the source filter applies (markers as in cores/CV32E40_.py;
        # duplicated because cores modules load by file path, not as a package).
        markers = ("cv32e40x_rvfi", "cv32e40x_wrapper.sv")
        kept = [s for s in core_srcs if not any(m in s for m in markers)]
        if len(kept) != len(core_srcs):
            print(f" - CV32E40X_upstream: dropped {len(core_srcs) - len(kept)} "
                  f"simulation-only core source(s) from the synthesis list")
        return kept

    def get_cvxif_core_filelist(self, core_dir):
        srcs, incs = [], []
        with open(os.path.join(core_dir, "cv32e40x_manifest.flist")) as manifest:
            for line in manifest:
                line = line.strip().replace("${DESIGN_RTL_DIR}", "rtl")
                if not line or line.startswith("//"):
                    continue
                if line.startswith("+incdir+"):
                    incs.append(line[len("+incdir+"):])
                elif line.startswith("+"):
                    continue
                else:
                    srcs.append(line)
        return srcs, incs, ["COREV_ASSERT_OFF"]


def get_supported_cores():
    return [("CORE_CV32E40X_UPSTREAM", "CV32E40X_upstream", CV32E40XUpstreamSupport())]
