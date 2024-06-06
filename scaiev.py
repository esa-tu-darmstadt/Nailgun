#!/usr/bin/env python3
import os
import shutil

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
    # Iterate over the contents of the source folder
    for item in os.listdir(source_folder):
        source_item = os.path.join(source_folder, item)
        target_item = os.path.join(target_folder, item)

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

    run_cmd.run("deps/scaie-v/EclipseWork/SCAIEV", f"java -jar ./target/SCAIEV-0.0.1-SNAPSHOT-jar-with-dependencies.jar -c {core} -i {isax_desc} -o {os.path.abspath(out_dir)}", "SCAIEV failed", False)
    print(f" - Creating wrapper module")
    run_cmd.run("deps/scaie-v-testbenches/cores", f"python3 {select_wrapper_gen(core)} {target_dir} {isax_dir}", "Could not generate top module")
    print(f" - Building the extended core")
    # The VexRiscv needs an extra build step!
    # TODO pretty much EVERY core needs extra build steps!
    if (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        # Patch the build system of VexRiscv
        patch_file = os.path.abspath("../patches/Vex5.patch")
        run_cmd.run(target_dir, f"patch -p1 < {patch_file} || true", "Could not patch the VexRiscv sources")
        # Build VexRiscv
        run_cmd.run(target_dir, 'sbt "runMain vexriscv.demo.VexRiscvAhbLite3"', "Could not generate VexRiscv.v")

def select_coresrc_folder_name(core):
    if (core == "PicoRV32"):
        return "picorv32"
    elif (core == "ORCA"):
        return "orca"
    elif (core == "Piccolo"):
        return core
    elif (core == "CVA5"):
        return core
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return "VexRiscv"
    else:
        error.exit_error("No datasheet for selected core found!")

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
        error.exit_error("No datasheet for selected core found!")

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
        error.exit_error("No linker file found for the selected core!")

def select_tb_wrapper_srcs(core):
    scal_sources = [ "CommonLogicModule.sv" ] #TODO can this also be CommonLogicModule.v?
    if (core == "PicoRV32"):
        return ["picorv32_tb_wrapper.sv"], ["picorv32.v", "picorv32_top.v"] + scal_sources, "testbench"
    elif (core == "ORCA"):
        return ["ORCA_tb_wrapper.sv"], ["ORCA.v", "ORCA_top.v"] + scal_sources, "testbench"
    elif (core == "Piccolo"):
        return ["Piccolo_tb_wrapper.sv"], ["Piccolo_top.v"] + scal_sources, "testbench"
    elif (core == "CVA5"):
        compile_order = os.path.join("deps/scaie-v/EclipseWork/SCAIEV/CoresSrc", core, "tools/compile_order")
        return ["CVA5_tb_wrapper.v"], read_file_lines(compile_order) + ["core/cva5_wrapper.sv", "CVA5_top.v"] + scal_sources, "testbench"
    elif (core == "VexRiscv_4s" or core == "VexRiscv_5s"):
        return ["Vex_tb_wrapper.sv"], ["VexRiscv.v", "Vex_top.sv"] + scal_sources, "vex_wrapper"
    else:
        error.exit_error("No testbench wrapper found for the selected core!")

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
        error.exit_error("No testbench env vars found for the selected core!")

def build_scaiev():
    # build scaiev
    if not os.path.isfile("./deps/scaie-v/EclipseWork/SCAIEV/target/SCAIEV-0.0.1-SNAPSHOT.jar"):
        print("Building SCAIE-V...")
        run_cmd.run("deps/scaie-v/EclipseWork/SCAIEV", "mvn package", "Could not build SCAIE-V")

# Selects the core
def select_core(kconfig_core):
    if len(kconfig_core) != 1:
        error.exit_error(f"No or more than one core selected in Kconfig: {kconfig_core}")
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
        error.exit_error("No datasheet for selected core found!")
