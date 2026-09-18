import glob
import os

from cvxif import CVXIFCoreSupport
from scaiev import CoreExtensions

# CV32E40PX (x-heep/cv32e40px), attached over CV-X-IF instead of SCAIE-V.
#
# Which core this is matters, because three similarly-named ones are in play:
#
#   CV32E40P   -- the PULP-derived original. No X-interface at all;
#                 `cores/CV32E40_.py` registers it with has_isax_support() False.
#   CV32E40X   -- a *different* core (openhwgroup/cv32e40x), 4-stage compute
#                 core, exposes CV-X-IF as a SystemVerilog interface.
#   CV32E40PX  -- this one: the CV32E40P derivative that adds CV-X-IF (plus
#                 RVB/RVP/RVK), maintained in the x-heep org (transferred from
#                 esl-epfl, whose GitHub URL now redirects) and used by X-HEEP.
#                 It packages the *same* interface revision as CV32E40X into
#                 packed structs (`cv32e40px_core_v_xif_pkg`).
#
# `make ci` runs cvxif.run_cvxif(), which populates the output tree with the
# copied core, the generated glue + the struct-unpacking wrapper
# (`--e40px-wrapper`), the top and a filelist.f. Simulation is the regular
# cocotb flow, through `tools/cvxif_sim/cvxif_obi_tb_wrapper.sv`:
#
#   CORE=CV32E40PX ISAXES=SPARKLE SIM_ENABLE=y \
#     TB_PATH=custom_tbs/sparkle.cpp TB_EXPECTED_PATH=custom_tbs/sparkle_expected.txt make ci

CV32E40PX_DIR = os.path.join("deps", "cv32e40px")


class CV32E40PXSupport(CVXIFCoreSupport):
    def copy_blacklist(self) -> list[str]:
        return [os.path.join(CV32E40PX_DIR, p)
                for p in (".git", "ci", "docs", "example_tb", "util", "sva")]

    def get_srcs_folder_name(self) -> str:
        return "CV32E40PX"

    def get_extensions(self) -> CoreExtensions:
        return CoreExtensions(['I', 'M', 'C', 'Zicsr'], "ilp32", 32)

    def get_linker_file(self) -> str:
        return self._get_linker_file("CV32E40X")

    def get_specific_startup_file(self) -> str:
        return self._get_specific_startup_file("CV32E40X")

    # ---- CV-X-IF hooks ----------------------------------------------------

    def get_upstream_core_dir(self) -> str:
        return CV32E40PX_DIR

    def cvxif_glue_args(self) -> list[str]:
        # Same interface revision as CV32E40X, packaged as packed structs in
        # cv32e40px_core_v_xif_pkg: field-for-field unpack wrapper.
        return ["--e40px-wrapper", "--no-wrapper"]

    def get_core_patches(self) -> list[str]:
        # Two core-side XIF bugs in upstream x-heep/cv32e40px (both in the
        # result path; see the patch headers and docs/cvxif.md):
        #  - the coprocessor result overwrote the core's own ALU-port write in
        #    the same cycle (wb_contention only feeds a performance counter);
        #  - a result that was presented but refused was treated as handed over.
        return [os.path.join("core_patches", "cv32e40px_xif_wb_priority.patch"),
                os.path.join("core_patches", "cv32e40px_xif_result_handshake.patch")]

    def get_top_files(self) -> list[str]:
        return [os.path.join("tools", "cvxif_sim", "cvxif_e40px_top.sv")]

    def get_tb_wrapper_files(self) -> list[str]:
        # Same `testbench` ports as SCAIE-V's cv32e40x_tb_wrapper.v, whose
        # OBI->AXI4 adapter it reuses.
        return [os.path.join("tools", "cvxif_sim", "cvxif_obi_tb_wrapper.sv"),
                os.path.join("deps", "scaie-v", "util", "maketop", "obi_axi_adapter.sv")]

    def get_tb_env_vars(self, kconf_syms) -> list[str]:
        # The memory map sim/linker_scripts/CV32E40X_link.ld is written for
        # (cores/CV32E40_.py).
        return [
            "NUM_BUSSI=2",
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            "IMEM_BUSIDX=0",
            "IMEM_BASE=80000000",
            # cvxif_e40px_top ties mtvec_addr_i to 0.
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

    def get_cvxif_core_filelist(self, core_dir):
        """Both of the repo's manifests (Bender.yml, src_files.yml) are stale
        -- they still list the pre-rename cv32e40p_* files -- so glob the RTL,
        packages first."""
        pkgs = sorted(glob.glob(os.path.join(core_dir, "rtl", "include", "*.sv")))
        skip = (
            # Two register-file variants ship; take the flop one.
            "cv32e40px_register_file_latch.sv",
            # Instantiated only inside `generate if (FPU)`, and we build with
            # FPU = 0. It imports fpnew_pkg, so compiling it would drag in the
            # whole vendored pulp-platform FPU for a never-elaborated block.
            "cv32e40px_fp_wrapper.sv",
        )
        rtl = sorted(f for f in glob.glob(os.path.join(core_dir, "rtl", "*.sv"))
                     if not f.endswith(skip))
        # cv32e40px_top instantiates the clock gate; the behavioural one is
        # the only implementation shipped.
        bhv = [os.path.join(core_dir, "bhv", "cv32e40px_sim_clock_gate.sv")]
        srcs = [os.path.relpath(p, core_dir) for p in pkgs + rtl + bhv]
        return srcs, [os.path.join("rtl", "include")], []


def get_supported_cores():
    return [("CORE_CV32E40PX", "CV32E40PX", CV32E40PXSupport())]
