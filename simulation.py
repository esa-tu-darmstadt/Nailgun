#!/usr/bin/env python3
import os
import functools
import glob
import shutil

import error
import run_cmd
import scaiev


def prepare_gcc(yaml_file):
    # Create GCC patches
    patched_files_dir = os.path.abspath("deps/scaie-v-testbenches/Scenario-HLS-DAC/opcodes")
    run_cmd.run(".", f"../tools/shady_gcc_patch_creator.py {yaml_file} {patched_files_dir}", "Could not patch gcc", False)
    # Rebuild GCC
    run_cmd.run("deps/scaie-v-testbenches/dep", f"./riscv-gnu-build.sh {patched_files_dir}", "Recompiling the patched gcc failed!", False)

def find_yaml_file(out_dir):
    # Construct the search pattern
    search_pattern = os.path.join(out_dir, '*.yaml')
    # Use glob to find files matching the pattern
    yaml_files = glob.glob(search_pattern)
    if yaml_files:
        return os.path.abspath(yaml_files[0])
    else:
        return None

def gcc_compile_tb(tb_path, core_name, out_dir):
    # Create the output directory
    bin_dir = os.path.abspath(os.path.join(out_dir, "tb_bin"))
    os.makedirs(bin_dir, exist_ok=False)

    gcc_path = os.path.abspath("deps/scaie-v-testbenches/dep/riscv-prefix/bin/riscv32-unknown-elf-gcc")
    objcopy_path = os.path.abspath("deps/scaie-v-testbenches/dep/riscv-prefix/bin/riscv32-unknown-elf-objcopy")
    # Build elf file
    elf_file = os.path.join(bin_dir, "tb.elf")
    linker_file = os.path.abspath(f"deps/scaie-v-testbenches/cores/{scaiev.select_linker_file(core_name)}")
    arch_flags = "-march=rv32im_zicsr -mabi=ilp32"
    c_flags = "-nostdlib -nostartfiles"
    run_cmd.run("deps/scaie-v-testbenches/dep", f"{gcc_path} {arch_flags} {c_flags} -T {linker_file} {tb_path} -o {elf_file}", "Compiling the test program failed!")
    # Build instr bin file
    instr_bin_path = os.path.join(bin_dir, "core_name_instr.bin")
    instr_dump_flags = "-O binary -j .text.init -j .text"
    run_cmd.run(".", f"{objcopy_path} {instr_dump_flags} {elf_file} {instr_bin_path}", "Failed to extract instruction section from elf file!")
    # Build data bin file
    data_bin_path = os.path.join(bin_dir, "core_name_data.bin")
    data_dump_flags = "-O binary -j .data -j .srodata -j .rodata -j .bss -j .sdata"
    run_cmd.run(".", f"{objcopy_path} {data_dump_flags} {elf_file} {data_bin_path}", "Failed to extract data section from elf file!")

    return instr_bin_path, data_bin_path

def run_tb(out_dir, core_name, instr_bin_path, tb_expected_path):
    tb_srcs, core_srcs, top_module = scaiev.select_tb_wrapper_srcs(core_name)
    # Add absolute paths to the tb wrapper srcs
    wrapper_base = os.path.abspath("deps/scaie-v-testbenches/cores")
    tb_srcs = list(map(lambda s: os.path.join(wrapper_base, s), tb_srcs))

    # Create the output directory
    sim_dir = os.path.abspath(os.path.join(out_dir, "sim"))
    os.makedirs(sim_dir, exist_ok=False)

    core_base = os.path.abspath(os.path.join(out_dir, core_name))
    core_srcs = list(map(lambda s: os.path.join(core_base, s), core_srcs))
    isax_src = list(map(lambda s: os.path.abspath(s), glob.glob(os.path.join(out_dir, '*.sv'))))
    verilog_srcs = core_srcs + tb_srcs + isax_src

    # Find all .py files in the sim directory
    py_files = glob.glob(os.path.join("sim", '*.py'))

    # Copy each file to the output simulation folder
    for file in py_files:
        shutil.copy(file, sim_dir)

    # Create a makefile to run the simulation
    sim_mk = os.path.join(sim_dir, "Makefile")
    with open(sim_mk, 'w') as f:
        f.write(f"""

VERILOG_SOURCES = {functools.reduce(lambda a, b: a + " " + b, verilog_srcs)} 
TOPLEVEL_LANG = verilog
TOPLEVEL = {top_module}
MODULE = test_default
SIM = verilator
# Do not treat warnings as fatal errors!
EXTRA_ARGS += -Wno-fatal
# Enable assertions
EXTRA_ARGS += --assert
# Tracing options
EXTRA_ARGS += --trace-fst --trace --trace-structs --trace-underscore
# Use more than one core to compile the simulation models
BUILD_ARGS += -j$(shell nproc)

include $(shell cocotb-config --makefiles)/Makefile.sim
""")
        
    env_vars = [
        f"TESTPROG={instr_bin_path[:-len('_instr.bin')]}",
        f"EXPECTED={tb_expected_path}",
    ] + scaiev.select_tb_env_vars(core_name)

    run_cmd.run(sim_dir, f"{functools.reduce(lambda a, b: a + ' ' + b, env_vars)} make sim", "Failed to run the simulation!")


def run_simulation(out_dir, core_name, kconfig_syms):
    if kconfig_syms['SIM_ENABLE'].str_value != "y":
        return
    if not os.path.exists(kconfig_syms['SIM_TB_PATH'].str_value):
        return
    if not os.path.exists(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value):
        return
    yaml_file_path = find_yaml_file(out_dir)
    tb_path = os.path.abspath(kconfig_syms['SIM_TB_PATH'].str_value)
    tb_expected_path = os.path.abspath(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value)
    prepare_gcc(yaml_file_path)
    instr_bin, data_bin = gcc_compile_tb(tb_path, core_name, out_dir)
    run_tb(out_dir, core_name, instr_bin, tb_expected_path)


def resolve_sched_algo(kconfig_syms):
    if kconfig_syms['LN_SCHED_ALGO_MS'].str_value == "y":
        sched_algo = ""
        if kconfig_syms['LN_SCHED_ALGO_MI'].str_value == "y":
            sched_algo = "MI_"
        if kconfig_syms['LN_SCHED_ALGO_PA'].str_value == "y":
            sched_algo += "PA"
        if kconfig_syms['LN_SCHED_ALGO_RA'].str_value == "y":
            sched_algo += "RA"

        sched_algo += "MS"
        return sched_algo
    return "LEGACY"

def resolve_opty_lib(kconfig_syms):
    #TODO these options could also be autogenerated!
    if kconfig_syms['LN_OPTY_NO_MODEL'].str_value == "y":
        return ""
    if kconfig_syms['LN_OPTY_OL2_MODEL'].str_value == "y":
        return "deps/longnail/opTyLibraries/OL2.yaml"
    assert kconfig_syms['LN_OPTY_CUSTOM_MODEL'].str_value == "y"
    return kconfig_syms['LN_OPTY_CUSTOM_MODEL_PATH'].str_value

def run_longnail(isax_tags, datasheet, kconfig_syms, out_dir):
    # gather src files
    print(f" - Invoking Longnail HLS")
    isax_tags = list(map(lambda a: f"build/mlir/{a}.mlir", isax_tags))
    # mlir_str = functools.reduce(lambda a, b: a+" "+b, isax_tags)

    # check inputs
    try:
        float(kconfig_syms['LN_CLOCK_PERIOD'].str_value)
    except ValueError:
        error.exit_error(f"Target clock period='{kconfig_syms['LN_CLOCK_PERIOD'].str_value}' could not be converted to a floating point value!")

    sched_algo = resolve_sched_algo(kconfig_syms)
    optylib = resolve_opty_lib(kconfig_syms)

    # collect flags to LN
    longnail_flags = [
        "-lower-coredsl-to-lil",
        f"-max-unroll-factor={kconfig_syms['LN_MAX_LOOP_UNROLL_FACTOR'].str_value}",
        f"-schedule-lil=\"datasheet={datasheet} library={kconfig_syms['LN_CELL_LIBRARY'].str_value} opTyLibrary={optylib} clockTime={kconfig_syms['LN_CLOCK_PERIOD'].str_value} schedulingAlgo={sched_algo} useCommercialSolver={'true' if kconfig_syms['LN_USE_COMMERCIAL_SOLVER'].str_value == 'y' else 'false'} schedulingTimeout={kconfig_syms['LN_SCHEDULE_TIMEOUT'].str_value} schedRefineTimeout={kconfig_syms['LN_REFINE_TIMEOUT'].str_value}\"",
        #TODO implement another step to select the solution
        "-lower-lil-to-hw=forceUseMinIISolution=true",
        "-simplify-structure", "-cse", "-canonicalize",
        "-lower-seq-to-sv", "-hw-cleanup", "-prettify-verilog",
        f"-export-split-verilog=dir-name={out_dir}", "-o /dev/null"
    ]
    longnail_flags_str = functools.reduce(lambda a, b: a+" "+b, longnail_flags)

    # execute LN
    run_cmd.run(".", f"./deps/longnail/build/bin/longnail-opt {longnail_flags_str} {isax_tags[0]}", "Longnail failed")


def build_longnail():
    # create build and tool directory
    os.makedirs("build", exist_ok=True)

    # check that gradlew exists
    if not os.path.isfile("deps/longnail/circt/utils/get-or-tools.sh"):
        error.exit_error("Longnail or its submodules are not cloned. Check out submodules in this repo!")

    # build longnail
    if not os.path.isfile("deps/longnail/build/bin/longnail-opt"):
        print("Building Longnail...")
        run_cmd.run("deps/longnail", "./circt/utils/get-or-tools.sh", "Gathering or-tools for CIRCT failed")
        run_cmd.run("deps/longnail", "chmod +x ./circt/utils/get-iverilog.sh && ./circt/utils/get-iverilog.sh", "Building iVerilog failed")
        run_cmd.run("deps/longnail", "sed -i '/^VERILATOR_VER=/c\VERILATOR_VER=5.012' ./circt/utils/get-verilator.sh && chmod +x ./circt/utils/get-verilator.sh && ./circt/utils/get-verilator.sh", "Building dependencies failed")
        run_cmd.run("deps/longnail", "./build_circt.sh", "Building CIRCT failed")
        run_cmd.run("deps/longnail", "./build_longnail.sh", "Longnail build failed")


# Selects the core datasheet file based on selected core
# TODO: if we would make the files in LN all lowercase, we could simply generate the file name
def select_core_datasheet(kconfig_core):
    if len(kconfig_core) != 1:
        error.exit_error(
            f"No or more than one core selected in Kconfig: {kconfig_core}")
    kconfig_core = kconfig_core[0]

    if (kconfig_core == "CORE_PICORV32"):
        return "deps/longnail/datasheets/PicoRV32.yaml"
    elif (kconfig_core == "CORE_ORCA"):
        return "deps/longnail/datasheets/ORCA.yaml"
    elif (kconfig_core == "CORE_PICCOLO"):
        return "deps/longnail/datasheets/Piccolo.yaml"
    elif (kconfig_core == "CORE_VEX_4S"):
        return "deps/longnail/datasheets/VexRiscv_4s.yaml"
    elif (kconfig_core == "CORE_VEX_5S"):
        return "deps/longnail/datasheets/VexRiscv_5s.yaml"
    elif (kconfig_core == "CORE_CVA5"):
        return "deps/benchmarks/CVA5.yaml"
    else:
        error.exit_error("No datasheet for selected core found!")


def provide_isax_yaml(out_dir):
    filelist = open(f"{out_dir}/filelist.f")
    yamls = [f[:-1] for f in filelist if f[-6:-1] == ".yaml"]
    return f"{out_dir}/"+yamls[0]
