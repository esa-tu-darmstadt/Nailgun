#!/usr/bin/env python3
import os
import shutil
import functools

import error
import run_cmd

def read_file_lines(filename):
    lines = []
    with open(filename, 'r') as file:
        for line in file:
            # Strip newline character and truncate whitespace from both ends
            line = line.strip()
            # Skip empty lines
            if line:
                lines.append(line)
    return lines

def copy_folder_contents(source_folder, target_folder):
    # Blacklist to workaround unnecessary files or simply broken symlinks due to non recursive clones
    blacklist = [
        # ORCA
        "deps/scaie-v/CoresSrc/ORCA/software", # broken symlinks
        # PicoRV32
        "deps/scaie-v/CoresSrc/PicoRV32/dhrystone", # unnecessary
        "deps/scaie-v/CoresSrc/PicoRV32/firmware", # unnecessary
        "deps/scaie-v/CoresSrc/PicoRV32/picosoc", # unnecessary
        "deps/scaie-v/CoresSrc/PicoRV32/scripts", # unnecessary
        "deps/scaie-v/CoresSrc/PicoRV32/tests", # unnecessary
        # CVA5
        "deps/scaie-v/CoresSrc/CVA5/debug_module", # unnecessary
        "deps/scaie-v/CoresSrc/CVA5/examples", # unnecessary
        "deps/scaie-v/CoresSrc/CVA5/formal", # unnecessary
        "deps/scaie-v/CoresSrc/CVA5/scripts", # unnecessary
        "deps/scaie-v/CoresSrc/CVA5/test_benches", # unnecessary
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
        # VexRiscv
        "deps/scaie-v/CoresSrc/VexRiscv/assets", # unnecessary
        "deps/scaie-v/CoresSrc/VexRiscv/doc", # unnecessary
        "deps/scaie-v/CoresSrc/VexRiscv/.github", # unnecessary
        "deps/scaie-v/CoresSrc/VexRiscv/scripts", # unnecessary
        # Piccolo
        "deps/scaie-v/CoresSrc/Piccolo/Tests", # unnecessary
    ]

    # Iterate over the contents of the source folder
    for item in os.listdir(source_folder):
        source_item = os.path.join(source_folder, item)
        target_item = os.path.join(target_folder, item)

        if source_item in blacklist:
            continue

        # Copy file or directory to the target folder
        if os.path.isfile(source_item):
            shutil.copy(source_item, target_folder)
        elif os.path.isdir(source_item):
            shutil.copytree(source_item, target_item, dirs_exist_ok=True)

def run_scaiev(core, isax_desc, out_dir):
    print(f"Invoking SCAIEV:")
    # create build and tool directory
    target_dir = os.path.abspath(f"{out_dir}/{core}")
    os.makedirs(target_dir, exist_ok=True)

    isax_desc = os.path.abspath(isax_desc)
    isax_dir = os.path.dirname(isax_desc)

    # Copy the unchanged core source file to our target directory
    copy_folder_contents(f"deps/scaie-v/CoresSrc/{select_coresrc_folder_name(core)}", target_dir)

    run_cmd.run("deps/scaie-v/", f"java -enableassertions -jar ./target/SCAIEV-0.0.1-SNAPSHOT-jar-with-dependencies.jar -c {core} -i {isax_desc} -o {os.path.abspath(out_dir)}", "SCAIEV failed", error.SCAIEV_BASE + 2)
    print(f" - Creating wrapper module")
    run_cmd.run("deps/scaie-v/util/maketop", f"python3 {select_wrapper_gen(core)} {target_dir} {isax_dir}", "Could not generate top module", error.SCAIEV_BASE + 3)
    print(f" - Building the extended core")
    # Perform extra build steps that are required for the target core!
    if (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        # Patch the build system of VexRiscv
        patch_file = os.path.abspath("patches/Vex5.patch")
        run_cmd.run(target_dir, f"patch -p1 < {patch_file}", "Could not patch the VexRiscv sources", error.SCAIEV_BASE + 4, False)
        # Build VexRiscv
        run_cmd.run(target_dir, 'sbt "runMain vexriscv.demo.VexRiscvAhbLite3"', "Could not generate VexRiscv.v", error.SCAIEV_BASE + 5, False, 100)
    elif (core == "PicoRV32"):
        # Patch in fence support for picorv32: https://github.com/YosysHQ/picorv32/pull/229
        # TODO remove once the coresrcs in scaie-v were updated
        patch_file = os.path.abspath("patches/picorv32.patch")
        run_cmd.run(target_dir, f"patch -p1 < {patch_file}", "Could not patch the PicoRV32 sources", error.SCAIEV_BASE + 6, False)
    elif (core == "Piccolo"):
        build_target_dir = os.path.join(target_dir, "builds/RV32ACIMU_Piccolo_verilator")
        run_cmd.run(build_target_dir, 'make clean', "Could not clean Piccolo build directory", error.SCAIEV_BASE + 7, False)
        run_cmd.run(build_target_dir, f'TOPFILE="{target_dir}/src_Core/Core/Core.bsv" TOPMODULE=mkCore make compile', "Could not compile Piccolo bluespec sources to verilog", error.SCAIEV_BASE + 8, False)
    elif (core == "ORCA"):
        # Things are getting wild
        patch_file = os.path.abspath("patches/ORCA_src_patch.diff")
        run_cmd.run(".", f'patch -u -p0 -N --directory="{target_dir}" < {patch_file}', "Could not apply patch to ORCA", error.SCAIEV_BASE + 9, False)
        vhd_files = [s for s in read_file_lines(os.path.join(target_dir, "ip/orca/hdl/Filelist")) if not s.startswith("#")]
        output_path = os.path.join(target_dir, "ORCA.v")
        ip_path = os.path.join(target_dir, "ip/orca/hdl")
        run_cmd.run(ip_path, f'yosys -m ghdl -p "ghdl -gAUX_MEMORY_REGIONS=0 -gUC_MEMORY_REGIONS=1 -gINTERRUPT_VECTOR=X\\"80000000\\" -gENABLE_EXCEPTIONS=1 -fsynopsys --std=08 {functools.reduce(lambda a, b: a + " " + b, vhd_files)} -e orca; write_verilog \\"{output_path}\\""', "Could not compile ORCA vhd files to verilog", error.SCAIEV_BASE + 10, False)

def select_coresrc_folder_name(core):
    if (core == "PicoRV32"):
        return core
    elif (core == "ORCA"):
        return core
    elif (core == "Piccolo"):
        return core
    elif (core == "CVA5"):
        return core
    elif (core == "CVA6"):
        return core
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return "VexRiscv"
    else:
        error.exit_error(f"No core source folder for selected core '{core}' found!", error.INTERNAL_ERROR)

def select_wrapper_gen(core):
    if (core == "PicoRV32"):
        return f"{core}_maketop.py"
    elif (core == "ORCA"):
        return f"{core}_maketop.py"
    elif (core == "Piccolo"):
        return f"{core}_maketop.py"
    elif (core == "CVA5"):
        return f"{core}_maketop.py"
    elif (core == "CVA6"):
        return f"{core}_maketop.py"
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return "Vex_maketop.py"
    else:
        error.exit_error(f"No wrapper for selected core '{core}' found!", error.INTERNAL_ERROR)

def select_linker_file(core):
    base_path = os.path.abspath(os.path.join("sim", "linker_scripts"))
    ld_file = os.path.join(base_path, f"{core}_link.ld")
    if not os.path.exists(ld_file):
        error.exit_error(f"No linker file found for '{core}'! Expected path: {ld_file}", error.INTERNAL_ERROR)

    return ld_file

def select_compiler_extensions(core):
    if (core == "PicoRV32"):
        # No multiply unit
        return "i", "ilp32", 32
    elif (core == "ORCA"):
        return "im", "ilp32", 32
    elif (core == "Piccolo"):
        return "imac", "ilp32", 32
    elif (core == "CVA5"):
        return "im", "ilp32", 32
    elif (core == "CVA6"):
        # TODO check for available extensions
        return "im", "lp64", 64
    elif core == "VexRiscv_4s":
        # No multiply unit
        return "i", "ilp32", 32
    elif core == "VexRiscv_5s":
        return "im", "ilp32", 32
    else:
        error.exit_error("No supported compiler extensions found for the selected core!", error.INTERNAL_ERROR)

def find_verilog_srcs(source_folder):
    # Blacklist unnecessary files, ones that might break the build
    blacklist = [
        # Piccolo
        os.path.join(source_folder, "mkSoC_Top.v"),
    ]

    v_sources = []
    # Iterate over the contents of the source folder
    for item in os.listdir(source_folder):
        source_item = os.path.join(source_folder, item)

        if source_item in blacklist or not os.path.isfile(source_item) or not source_item.endswith(".v"):
            continue

        v_sources.append(os.path.abspath(source_item))
    return v_sources

def select_tb_wrapper_srcs(core, out_dir):
    scal_sources = [ "CommonLogicModule.sv" ] #TODO can this also be CommonLogicModule.v?
    if (core == "PicoRV32"):
        return ["picorv32_tb_wrapper.sv"], ["picorv32.v", "picorv32_top.v"] + scal_sources, "testbench", ""
    elif (core == "ORCA"):
        return ["ORCA_tb_wrapper.sv"], ["ORCA.v", "ORCA_top.v"] + scal_sources, "testbench", ""
    elif (core == "Piccolo"):
        bsv_lib_sources = find_verilog_srcs(os.path.join(out_dir, core, "src_bsc_lib_RTL"))
        core_srcs = find_verilog_srcs(os.path.join(out_dir, core, "builds/RV32ACIMU_Piccolo_verilator/Verilog_RTL"))
        extra_makefile_args = """
EXTRA_ARGS+=-DBSV_NO_MAIN_V
EXTRA_ARGS+=--no-timing
# Verilator throws lots of warnings on the BlueSpec-compiled core. Ignoring some of them.
EXTRA_ARGS+=-Wno-STMTDLY -Wno-UNSIGNED -Wno-CMPCONST -Wno-CASEINCOMPLETE
"""
        return ["Piccolo_tb_wrapper.sv"], core_srcs + bsv_lib_sources + ["Piccolo_top.v"] + scal_sources, "testbench", extra_makefile_args
    elif (core == "CVA5"):
        compile_order = os.path.join("deps/scaie-v/CoresSrc", core, "tools/compile_order")
        return ["CVA5_tb_wrapper.v"], read_file_lines(compile_order) + ["core/cva5_wrapper.sv", "CVA5_top.v"] + scal_sources, "testbench", ""
    elif (core == "CVA6"):
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
            "core/include/config_pkg.sv",
            "core/include/cv64a6_imafdc_sv39_config_pkg.sv",
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

        extra_makefile_args = """
SRCDIR=../CVA6
# Include folders
EXTRA_ARGS+=-I$(SRCDIR)/core/
EXTRA_ARGS+=-I$(SRCDIR)/core/include/
EXTRA_ARGS+=+incdir+$(SRCDIR)/vendor/pulp-platform/common_cells/include/
EXTRA_ARGS+=-I$(SRCDIR)/vendor/pulp-platform/common_cells/src/
EXTRA_ARGS+=-I$(SRCDIR)/vendor/pulp-platform/axi/include/
EXTRA_ARGS+=-I$(SRCDIR)/common/local/util/
EXTRA_ARGS+=-I$(SRCDIR)/core/cache_subsystem/hpdcache/rtl/include
# Flags
EXTRA_ARGS+=-DENABLE_SIMULATION_ASSERTIONS
# SCAIE-V flags to enable specific code blocks
EXTRA_ARGS+=+define$(shell cat $(SRCDIR)/SCAIE-V_Flags.txt)
EXTRA_ARGS+=-Wno-BLKANDNBLK $(SRCDIR)/verilator_config.vlt -Wno-fatal
"""

        return ["CVA6_tb_wrapper.v"], core_srcs + scal_sources, "testbench", extra_makefile_args
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return ["Vex_tb_wrapper.sv"], ["VexRiscv.v", "Vex_top.sv"] + scal_sources, "vex_wrapper", ""
    else:
        error.exit_error("No testbench wrapper found for the selected core!", error.INTERNAL_ERROR)

def select_tb_env_vars(core):
    if (core == "PicoRV32"):
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=2",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=00000000",
            # The core has a 'trap' output pin that indicates prior exceptions (optional).
            "HAS_TRAP_PIN=1",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            "DMEM_BASE=00100000",
            # The offset to program results within the data memory.
            "DMEM_RESULTS_OFFS=00001000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=1",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=00200000",
        ]
    elif (core == "ORCA"):
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=2",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=00000000",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            "EXCEPTION_BASE=80000000",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            "DMEM_BASE=00100000",
            # The offset to program results within the data memory.
            "DMEM_RESULTS_OFFS=00001000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=1",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=00200000",
        ]
    elif (core == "Piccolo"):
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=2",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=00001000",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            "EXCEPTION_BASE=00000000",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            "DMEM_BASE=00100000",
            # The offset to program results within the data memory.
            "DMEM_RESULTS_OFFS=00001000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=1",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=00200000",
        ]
    elif (core == "CVA5"):
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=3",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=BRAM",
            "BUSSI0_SIGNAME=m_bram_instr",
            "BUSSI1_TYPE=BRAM",
            "BUSSI1_SIGNAME=m_bram_data",
            "BUSSI2_TYPE=AXI4",
            "BUSSI2_SIGNAME=m_axi_ctrl",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=80000000",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            "EXCEPTION_BASE=8F000000",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            "DMEM_BASE=80100000",
            # The offset to program results within the data memory.
            "DMEM_RESULTS_OFFS=00001000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=2",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=60000000",
        ]
    elif (core == "CVA6"):
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
            # The offset to program results within the data memory.
            "DMEM_RESULTS_OFFS=00001000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=0",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=60000000",
        ]
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=2",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=80000000",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            "EXCEPTION_BASE=00000020",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            "DMEM_BASE=80100000",
            # The offset to program results within the data memory.
            "DMEM_RESULTS_OFFS=00001000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=1",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=80200000",
        ]
    else:
        error.exit_error("No testbench env vars found for the selected core!", error.INTERNAL_ERROR)

def build_scaiev(kconf_syms):
    if kconf_syms["SCAIEV_DO_NOT_REBUILD"].str_value == "y" and os.path.isfile("./deps/scaie-v/target/SCAIEV-0.0.1-SNAPSHOT.jar"):
        return
    # build scaiev
    print("Building SCAIE-V...")
    run_cmd.run("deps/scaie-v/", "mvn package", "Could not build SCAIE-V", error.SCAIEV_BASE + 1)

# Selects the core
def select_core(kconfig_core):
    if len(kconfig_core) != 1:
        error.exit_error(f"No or more than one core selected in Kconfig: {kconfig_core}", error.USER_ERROR)
    kconfig_core = kconfig_core[0]

    if (kconfig_core == "CORE_PICORV32"):
        return "PicoRV32"
    elif (kconfig_core == "CORE_ORCA"):
        return "ORCA"
    elif (kconfig_core == "CORE_PICCOLO"):
        return "Piccolo"
    elif (kconfig_core == "CORE_CVA5"):
        return "CVA5"
    elif (kconfig_core == "CORE_CVA6"):
        return "CVA6"
    elif (kconfig_core == "CORE_VEX_4S"):
        return "VexRiscv_4s"
    elif (kconfig_core == "CORE_VEX_5S"):
        return "VexRiscv_5s"
    else:
        error.exit_error(f"No datasheet for selected core '{kconfig_core}' found!", error.INTERNAL_ERROR)
