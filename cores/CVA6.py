import os

from scaiev import CoreSupport
from cores.utils.helpers import read_file_lines

class CVA6Support(CoreSupport):
    def __init__(self, is_64_bit : bool):
        self.is_64_bit = is_64_bit
    def copy_blacklist(self) -> list[str]:
        return [
            # CVA6
            "deps/scaie-v/CoresSrc/cva6/ci", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/config", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/corev_apu", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/docs", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/.git", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/.github", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/.gitlab-ci", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/isaxes_test", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/pd", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/spyglass", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/util", # unnecessary
            "deps/scaie-v/CoresSrc/cva6/verif", # unnecessary
        ]
    def run_extra_build_steps(self, target_dir, kconf_syms) -> None:
        pass
    def get_compiler_extensions(self) -> tuple[str, str, int]:
        if self.is_64_bit:
            return "imac_zicsr", "lp64", 64
        return "imac_zicsr", "ilp32", 32

    def has_isax_support(self) -> bool:
        return True
    def get_srcs_folder_name(self) -> str:
        return "CVA6"
    def get_maketop(self) -> str:
        return "CVA6_maketop.py"

    # -> tb srcs, core srcs, tb top module, core top module, include dirs, defines, extra sim makefile args
    def get_core_srcs(self, scal_sources, core_dir) -> tuple[list[str], list[str], str, str, list[str], list[str], dict[str, str]]:
        core_srcs = [
            "vendor/pulp-platform/fpga-support/rtl/SyncDpRam.sv",
            "vendor/pulp-platform/fpga-support/rtl/AsyncDpRam.sv",
            "vendor/pulp-platform/fpga-support/rtl/AsyncThreePortRam.sv",
            "core/cvfpu/src/fpnew_pkg.sv",
            "core/cvfpu/src/fpnew_cast_multi.sv",
            "core/cvfpu/src/fpnew_classifier.sv",
            "core/cvfpu/src/fpnew_divsqrt_multi.sv",
            "core/cvfpu/src/fpnew_fma_multi.sv",
            "core/cvfpu/src/fpnew_fma.sv",
            "core/cvfpu/src/fpnew_noncomp.sv",
            "core/cvfpu/src/fpnew_opgroup_block.sv",
            "core/cvfpu/src/fpnew_opgroup_fmt_slice.sv",
            "core/cvfpu/src/fpnew_opgroup_multifmt_slice.sv",
            "core/cvfpu/src/fpnew_rounding.sv",
            "core/cvfpu/src/fpnew_top.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/control_mvp.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv",
            "core/cvfpu/src/fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv",
            "core/scaiev_config.sv",
            "core/include/config_pkg.sv",
            "core/include/%s_scaiev_config_pkg.sv" % ("cv64a6_imac_sv39" if self.is_64_bit else "cv32a6_imac_sv32"),
            "core/include/riscv_pkg.sv",
            "core/include/ariane_pkg.sv",
            "vendor/pulp-platform/axi/src/axi_pkg.sv",
            "core/include/wt_cache_pkg.sv",
            "core/include/std_cache_pkg.sv",
            "core/include/instr_tracer_pkg.sv",
            "core/include/build_config_pkg.sv",
            "core/include/cvxif_pkg.sv",
            "core/cvxif_example/include/cvxif_instr_pkg.sv",
            "core/cvxif_fu.sv",
            "core/cvxif_example/cvxif_example_coprocessor.sv",
            "core/cvxif_example/instr_decoder.sv",
            "vendor/pulp-platform/common_cells/src/cf_math_pkg.sv",
            "vendor/pulp-platform/common_cells/src/fifo_v3.sv",
            "vendor/pulp-platform/common_cells/src/lfsr.sv",
            "vendor/pulp-platform/common_cells/src/lfsr_8bit.sv",
            "vendor/pulp-platform/common_cells/src/stream_arbiter.sv",
            "vendor/pulp-platform/common_cells/src/stream_arbiter_flushable.sv",
            "vendor/pulp-platform/common_cells/src/stream_mux.sv",
            "vendor/pulp-platform/common_cells/src/stream_demux.sv",
            "vendor/pulp-platform/common_cells/src/lzc.sv",
            "vendor/pulp-platform/common_cells/src/rr_arb_tree.sv",
            "vendor/pulp-platform/common_cells/src/shift_reg.sv",
            "vendor/pulp-platform/common_cells/src/unread.sv",
            "vendor/pulp-platform/common_cells/src/popcount.sv",
            "vendor/pulp-platform/common_cells/src/exp_backoff.sv",
            "vendor/pulp-platform/common_cells/src/counter.sv",
            "vendor/pulp-platform/common_cells/src/delta_counter.sv",
            "core/cva6.sv",
            "cva6_ariane_wrapper.sv",
            "core/cva6_rvfi_probes.sv",
            "core/alu.sv",
            "core/fpu_wrap.sv",
            "core/branch_unit.sv",
            "core/compressed_decoder.sv",
            "core/macro_decoder.sv",
            "core/controller.sv",
            "core/csr_buffer.sv",
            "core/csr_regfile.sv",
            "core/decoder.sv",
            "core/ex_stage.sv",
            "core/instr_realign.sv",
            "core/id_stage.sv",
            "core/issue_read_operands.sv",
            "core/issue_stage.sv",
            "core/load_unit.sv",
            "core/load_store_unit.sv",
            "core/lsu_bypass.sv",
            "core/mult.sv",
            "core/multiplier.sv",
            "core/serdiv.sv",
            "core/perf_counters.sv",
            "core/ariane_regfile_ff.sv",
            "core/ariane_regfile_fpga.sv",
            "core/scaiev_glue.sv",
            "core/cva6_glue_wrapper.sv",
            "core/scaiev_fu.sv",
            "core/scoreboard.sv",
            "core/round_interval.sv",
            "core/store_buffer.sv",
            "core/amo_buffer.sv",
            "core/store_unit.sv",
            "core/commit_stage.sv",
            "core/axi_shim.sv",
            "core/cva6_accel_first_pass_decoder_stub.sv",
            "core/acc_dispatcher.sv",
            "core/cva6_fifo_v3.sv",
            "core/frontend/btb.sv",
            "core/frontend/bht.sv",
            "core/frontend/ras.sv",
            "core/frontend/instr_scan.sv",
            "core/frontend/instr_queue.sv",
            "core/frontend/frontend.sv",
            "core/cache_subsystem/wt_dcache_ctrl.sv",
            "core/cache_subsystem/wt_dcache_mem.sv",
            "core/cache_subsystem/wt_dcache_missunit.sv",
            "core/cache_subsystem/wt_dcache_wbuffer.sv",
            "core/cache_subsystem/wt_dcache.sv",
            "core/cache_subsystem/cva6_icache.sv",
            "core/cache_subsystem/wt_cache_subsystem.sv",
            "core/cache_subsystem/wt_axi_adapter.sv",
            "core/cache_subsystem/tag_cmp.sv",
            "core/cache_subsystem/axi_adapter.sv",
            "core/cache_subsystem/miss_handler.sv",
            "core/cache_subsystem/cache_ctrl.sv",
            "core/cache_subsystem/cva6_icache_axi_wrapper.sv",
            "core/cache_subsystem/std_cache_subsystem.sv",
            "core/cache_subsystem/std_nbdcache.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_pkg.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_demux.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_lfsr.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_sync_buffer.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_fifo_reg.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_fifo_reg_initialized.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_fxarb.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_rrarb.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_mux.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_1hot_to_binary.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_prio_1hot_encoder.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_regbank_wbyteenable_1rw.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_regbank_wmask_1rw.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_data_downsize.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/hpdcache_data_upsize.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hwpf_stride/hwpf_stride_pkg.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hwpf_stride/hwpf_stride.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hwpf_stride/hwpf_stride_arb.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hwpf_stride/hwpf_stride_wrapper.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_amo.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_cmo.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_core_arbiter.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_ctrl.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_ctrl_pe.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_memctrl.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_miss_handler.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_mshr.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_plru.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_rtab.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_uncached.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_victim_sel.sv",
            "core/cache_subsystem/hpdcache/rtl/src/hpdcache_wbuf.sv",
            "core/cache_subsystem/hpdcache/rtl/src/utils/hpdcache_mem_req_read_arbiter.sv",
            "core/cache_subsystem/hpdcache/rtl/src/utils/hpdcache_mem_req_write_arbiter.sv",
            "core/cache_subsystem/hpdcache/rtl/src/utils/hpdcache_mem_resp_demux.sv",
            "core/cache_subsystem/hpdcache/rtl/src/utils/hpdcache_mem_to_axi_read.sv",
            "core/cache_subsystem/hpdcache/rtl/src/utils/hpdcache_mem_to_axi_write.sv",
            "core/cache_subsystem/cva6_hpdcache_subsystem.sv",
            "core/cache_subsystem/cva6_hpdcache_subsystem_axi_arbiter.sv",
            "core/cache_subsystem/cva6_hpdcache_if_adapter.sv",
            "core/cache_subsystem/cva6_hpdcache_wrapper.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/macros/behav/hpdcache_sram_1rw.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/macros/behav/hpdcache_sram_wbyteenable_1rw.sv",
            "core/cache_subsystem/hpdcache/rtl/src/common/macros/behav/hpdcache_sram_wmask_1rw.sv",
            "core/pmp/src/pmp.sv",
            "core/pmp/src/pmp_entry.sv",
            "common/local/util/instr_tracer.sv",
            "common/local/util/tc_sram_wrapper.sv",
            "common/local/util/tc_sram_wrapper_cache_techno.sv",
            "vendor/pulp-platform/tech_cells_generic/src/rtl/tc_sram.sv",
            "common/local/util/sram.sv",
            "common/local/util/sram_cache.sv",
            "core/cva6_mmu/cva6_mmu.sv",
            "core/cva6_mmu/cva6_ptw.sv",
            "core/cva6_mmu/cva6_tlb.sv",
            "core/cva6_mmu/cva6_shared_tlb.sv",
        ]

        include_dirs = [
            "core",
            "core/include",
            "vendor/pulp-platform/common_cells/include",
            "vendor/pulp-platform/common_cells/src",
            "vendor/pulp-platform/axi/include",
            "common/local/util",
            "core/cache_subsystem/hpdcache/rtl/include",
        ]

        plus_defines = read_file_lines(os.path.join(core_dir, "SCAIE-V_Flags.txt"))
        assert len(plus_defines) == 1
        plus_defines = plus_defines[0]
        defines = [d for d in plus_defines.split("+") if d]
        defines.append("ENABLE_SIMULATION_ASSERTIONS")

        extra_makefile_args = {
            "verilator": """
SRCDIR=../CVA6
# Mute some verilator warnings
EXTRA_ARGS+=-Wno-BLKANDNBLK $(SRCDIR)/verilator_config.vlt -Wno-fatal
"""
        }

        return ["CVA6_tb_wrapper.v"], core_srcs + scal_sources, "testbench", "cva6_ariane_wrapper", include_dirs, defines, extra_makefile_args

    def get_tb_env_vars(self) -> list[str]:
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=1",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_ctrl",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=80000000",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            "EXCEPTION_BASE=808",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=0",
            # The base address of the data memory on the bus.
            "DMEM_BASE=80100000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=0",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=60000000",
        ]

    def get_linker_file(self) -> str:
        return self._get_linker_file("CVA6")
    def get_specific_startup_file(self) -> str:
        return self._get_specific_startup_file("CVA6")

def get_supported_cores():
    return [
        ("CORE_CVA6", "CVA6", CVA6Support(False)),
        ("CORE_CVA6_64", "CVA6_64", CVA6Support(True)),
    ]
