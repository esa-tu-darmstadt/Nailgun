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
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/ORCA/software", # broken symlinks
        # PicoRV32
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/PicoRV32/dhrystone", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/PicoRV32/scripts", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/PicoRV32/tests", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/PicoRV32/firmware", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/PicoRV32/picosoc", # unnecessary
        # CVA5
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/CVA5/formal", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/CVA5/scripts", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/CVA5/test_benches", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/CVA5/examples", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/CVA5/debug_module", # unnecessary
        # VexRiscv
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/VexRiscv/.github", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/VexRiscv/doc", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/VexRiscv/scripts", # unnecessary
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/VexRiscv/assets", # unnecessary
        # Piccolo
        "deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/Piccolo/Tests", # unnecessary
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
    copy_folder_contents(f"deps/scaie-v/EclipseWork/SCAIEV/CoresSrc/{select_coresrc_folder_name(core)}", target_dir)

    run_cmd.run("deps/scaie-v/EclipseWork/SCAIEV", f"java -enableassertions -jar ./target/SCAIEV-0.0.1-SNAPSHOT-jar-with-dependencies.jar -c {core} -i {isax_desc} -o {os.path.abspath(out_dir)}", "SCAIEV failed", error.SCAIEV_BASE + 2)
    print(f" - Creating wrapper module")
    run_cmd.run("deps/scaie-v-testbenches/cores", f"python3 {select_wrapper_gen(core)} {target_dir} {isax_dir}", "Could not generate top module", error.SCAIEV_BASE + 3)
    print(f" - Building the extended core")
    # Perform extra build steps that are required for the target core!
    if (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        # Patch the build system of VexRiscv
        patch_file = os.path.abspath("../patches/Vex5.patch")
        run_cmd.run(target_dir, f"patch -p1 < {patch_file} || true", "Could not patch the VexRiscv sources", error.SCAIEV_BASE + 4, False)
        # Build VexRiscv
        run_cmd.run(target_dir, 'sbt "runMain vexriscv.demo.VexRiscvAhbLite3"', "Could not generate VexRiscv.v", error.SCAIEV_BASE + 5, False, 100)
    elif (core == "Piccolo"):
        build_target_dir = os.path.join(target_dir, "builds/RV32ACIMU_Piccolo_verilator")
        run_cmd.run(build_target_dir, 'make clean', "Could not clean Piccolo build directory", error.SCAIEV_BASE + 6, False)
        run_cmd.run(build_target_dir, f'TOPFILE="{target_dir}/src_Core/Core/Core.bsv" TOPMODULE=mkCore make compile', "Could not compile Piccolo bluespec sources to verilog", error.SCAIEV_BASE + 7, False)
    elif (core == "ORCA"):
        # Things are getting wild
        patch_file = os.path.abspath("deps/scaie-v-testbenches/cores/ORCA_src_patch.diff")
        run_cmd.run(".", f'patch -u -p0 -N --directory="{target_dir}" < {patch_file}', "Could not apply patch to ORCA", error.SCAIEV_BASE + 8, False)
        vhd_files = [s for s in read_file_lines(os.path.join(target_dir, "ip/orca/hdl/Filelist")) if not s.startswith("#")]
        output_path = os.path.join(target_dir, "ORCA.v")
        ip_path = os.path.join(target_dir, "ip/orca/hdl")
        run_cmd.run(ip_path, f'yosys -m ghdl -p "ghdl -gAUX_MEMORY_REGIONS=0 -gUC_MEMORY_REGIONS=1 -gINTERRUPT_VECTOR=X\\"80000000\\" -gENABLE_EXCEPTIONS=1 -fsynopsys --std=08 {functools.reduce(lambda a, b: a + " " + b, vhd_files)} -e orca; write_verilog \\"{output_path}\\""', "Could not compile ORCA vhd files to verilog", error.SCAIEV_BASE + 9, False)

def select_coresrc_folder_name(core):
    if (core == "PicoRV32"):
        return core
    elif (core == "ORCA"):
        return core
    elif (core == "Piccolo"):
        return core
    elif (core == "CVA5"):
        return core
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return "VexRiscv"
    else:
        error.exit_error(f"No core source folder for selected core '{core}' found!", error.INTERNAL_ERROR)

def select_wrapper_gen(core):
    if (core == "PicoRV32"):
        return "picorv32_maketop.py"
    elif (core == "ORCA"):
        return "ORCA_maketop.py"
    elif (core == "Piccolo"):
        return "Piccolo_maketop.py"
    elif (core == "CVA5"):
        return "CVA5_maketop.py"
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return "Vex_maketop.py"
    else:
        error.exit_error(f"No wrapper for selected core '{core}' found!", error.INTERNAL_ERROR)

def select_linker_file(core):
    if (core == "PicoRV32"):
        return "picorv32_link.ld"
    elif (core == "ORCA"):
        return f"{core}_link.ld"
    elif (core == "Piccolo"):
        return f"{core}_link.ld"
    elif (core == "CVA5"):
        return f"{core}_link.ld"
    elif core == "VexRiscv_4s":
        return f"Vex4_link.ld"
    elif core == "VexRiscv_5s":
        return f"Vex5_link.ld"
    else:
        error.exit_error("No linker file found for the selected core!", error.INTERNAL_ERROR)

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
        compile_order = os.path.join("deps/scaie-v/EclipseWork/SCAIEV/CoresSrc", core, "tools/compile_order")
        return ["CVA5_tb_wrapper.v"], read_file_lines(compile_order) + ["core/cva5_wrapper.sv", "CVA5_top.v"] + scal_sources, "testbench", ""
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

def build_scaiev():
    # build scaiev
    if not os.path.isfile("./deps/scaie-v/EclipseWork/SCAIEV/target/SCAIEV-0.0.1-SNAPSHOT.jar"):
        print("Building SCAIE-V...")
        run_cmd.run("deps/scaie-v/EclipseWork/SCAIEV", "mvn package", "Could not build SCAIE-V", error.SCAIEV_BASE + 1)

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
    elif (kconfig_core == "CORE_VEX_4S"):
        return "VexRiscv_4s"
    elif (kconfig_core == "CORE_VEX_5S"):
        return "VexRiscv_5s"
    else:
        error.exit_error(f"No datasheet for selected core '{kconfig_core}' found!", error.INTERNAL_ERROR)
