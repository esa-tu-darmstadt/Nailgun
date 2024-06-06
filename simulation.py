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
    print(f"Running full core + ISAX simulation:")
    if not os.path.exists(kconfig_syms['SIM_TB_PATH'].str_value):
        error.exit_error("Simulation testbench path is missing!")
    if not os.path.exists(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value):
        error.exit_error("Simulation testbench expected output path is missing!")
    yaml_file_path = find_yaml_file(out_dir)
    tb_path = os.path.abspath(kconfig_syms['SIM_TB_PATH'].str_value)
    tb_expected_path = os.path.abspath(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value)
    print(f" - Adding ISAX assembly support to GCC")
    prepare_gcc(yaml_file_path)
    print(f" - Compiling assembly TB")
    instr_bin, data_bin = gcc_compile_tb(tb_path, core_name, out_dir)
    print(f" - Start simulation")
    run_tb(out_dir, core_name, instr_bin, tb_expected_path)
