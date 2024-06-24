#!/usr/bin/env python3
import os
import functools
import glob
import shutil

import error
import run_cmd
import scaiev


def prepare_llvm(mlir_path, version = "17"):
    mlir_path = os.path.abspath(mlir_path)
    awesome_path = "deps/awesome_llvm"
    awesome_ln_bin = os.path.abspath(f"{awesome_path}/build/bin/longnail-opt")

    # Hard reset the llvm target repository
    llvm_repo = os.path.abspath(f"{awesome_path}/compiler-patcher/build-tests/llvm-project/worktree/{version}")

    # Ensure the llvm repo is setup
    if not os.path.exists(llvm_repo):
        # Clone llvm
        run_cmd.run(".", f"git clone --depth=1 -b release/{version}.x https://github.com/llvm/llvm-project.git {llvm_repo}", f"Failed to clone LLVM {version}", False)
        # Configure cmake
        ccache_path = os.path.abspath(f"{awesome_path}/compiler-patcher/build-tests/llvm-project/ccache")
        cmake_config = [
			"-DLLVM_ENABLE_PROJECTS=clang",
			"-DLLVM_TARGETS_TO_BUILD=RISCV",
			"-DBUILD_SHARED_LIBS=ON",
			"-DLLVM_CCACHE_BUILD=ON",
			f"-DLLVM_CCACHE_DIR='{ccache_path}'",
			"-DLLVM_CCACHE_MAXSIZE=25G",
			"-DCMAKE_BUILD_TYPE=Debug",
        ]
        run_cmd.run(llvm_repo, f"cmake -S llvm -B build -G Ninja {functools.reduce(lambda a, b: a + ' ' + b, cmake_config)}", f"Failed to configure cmake for LLVM {version}", False)

    run_cmd.run(".", f"git -C {llvm_repo} reset --hard ", "Failed to reset the llvm work directory", False)
    # Patch LLVM
    llvm_patcher = os.path.abspath(f"{awesome_path}/compiler-patcher/compiler-patcher.sh")
    pass_opts = "disableISelGen=true" # No ISel patterns for now
    run_cmd.run(".", f"{llvm_patcher} --coredsl-input {mlir_path} --longail-bin {awesome_ln_bin} --llvm-project-dir {llvm_repo} --llvm-version {version} -pass-opts '{pass_opts}'", f"Failed to patch LLVM {version} to add support for the selected ISAXes", False, 200)
    # Build LLVM
    build_dir = os.path.join(llvm_repo, "build")
    run_cmd.run(".", f"cmake --build {build_dir} -- all", f"Failed to build the patched LLVM {version}", False, 200)
    return build_dir

def prepare_gcc(yaml_file):
    # Create GCC patches
    patched_files_dir = os.path.abspath("deps/scaie-v-testbenches/Scenario-HLS-DAC/opcodes")
    run_cmd.run(".", f"../tools/shady_gcc_patch_creator.py {yaml_file} {patched_files_dir}", "Could not patch gcc", False)
    # Rebuild GCC
    run_cmd.run("deps/scaie-v-testbenches/dep", f"./riscv-gnu-build.sh {patched_files_dir}", "Recompiling the patched gcc failed!", False)

def compile_tb(tb_path, core_name, out_dir, cc_path, objcopy_path, flags):
    # Create the output directory
    bin_dir = os.path.abspath(os.path.join(out_dir, "tb_bin"))
    os.makedirs(bin_dir, exist_ok=False)

    # Build elf file
    elf_file = os.path.join(bin_dir, "tb.elf")
    linker_file = os.path.abspath(f"deps/scaie-v-testbenches/cores/{scaiev.select_linker_file(core_name)}")
    run_cmd.run("deps/scaie-v-testbenches/dep", f"{cc_path} {flags} -T {linker_file} {tb_path} -o {elf_file}", "Compiling the test program failed!", False)
    # Build instr bin file
    instr_bin_path = os.path.join(bin_dir, "core_name_instr.bin")
    instr_dump_flags = "-O binary -j .text.init -j .text"
    run_cmd.run(".", f"{objcopy_path} {instr_dump_flags} {elf_file} {instr_bin_path}", "Failed to extract instruction section from elf file!", False)
    # Build data bin file
    data_bin_path = os.path.join(bin_dir, "core_name_data.bin")
    data_dump_flags = "-O binary -j .data -j .srodata -j .rodata -j .bss -j .sdata"
    run_cmd.run(".", f"{objcopy_path} {data_dump_flags} {elf_file} {data_bin_path}", "Failed to extract data section from elf file!", False)

    return instr_bin_path, data_bin_path

def gcc_compile_tb(tb_path, core_name, out_dir):
    gcc_path = os.path.abspath("deps/scaie-v-testbenches/dep/riscv-prefix/bin/riscv32-unknown-elf-gcc")
    objcopy_path = os.path.abspath("deps/scaie-v-testbenches/dep/riscv-prefix/bin/riscv32-unknown-elf-objcopy")
    arch_flags = "-march=rv32im_zicsr -mabi=ilp32"
    c_flags = "-nostdlib -nostartfiles"
    flags = f"{arch_flags} {c_flags}"

    return compile_tb(tb_path, core_name, out_dir, gcc_path, objcopy_path, flags)

def llvm_compile_tb(tb_path, core_name, out_dir, llvm_build_path, isax_name):
    clang_path = os.path.join(llvm_build_path, "bin", "clang")
    objcopy_path = os.path.join(llvm_build_path, "bin", "llvm-objcopy")
    startup_asm = os.path.abspath("startup.s")
    #TODO zicsr?
    flags = f'--target="riscv32-none-elf" -menable-experimental-extensions -mabi="ilp32" -march="rv32im_x{isax_name}0p1" -nostdlib -O3 {startup_asm}'
    return compile_tb(tb_path, core_name, out_dir, clang_path, objcopy_path, flags)

def run_tb(out_dir, core_name, instr_bin_path, tb_expected_path):
    tb_srcs, core_srcs, top_module, extra_makefile_opts = scaiev.select_tb_wrapper_srcs(core_name, out_dir)
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

{extra_makefile_opts}

include $(shell cocotb-config --makefiles)/Makefile.sim
""")

    env_vars = [
        f"TESTPROG={instr_bin_path[:-len('_instr.bin')]}",
        f"EXPECTED={tb_expected_path}",
    ] + scaiev.select_tb_env_vars(core_name)

    results_xml_path = os.path.join(sim_dir, "results.xml")
    # We ALWAYS want colors, lol
    run_cmd.run(sim_dir, f"COCOTB_ANSI_OUTPUT=1 {functools.reduce(lambda a, b: a + ' ' + b, env_vars)} make sim && ! grep -nri 'Test failed' {results_xml_path}", "The simulation failed!")

def find_yaml_file(out_dir):
    # Construct the search pattern
    search_pattern = os.path.join(out_dir, '*.yaml')
    # Use glob to find files matching the pattern
    yaml_files = glob.glob(search_pattern)
    if yaml_files:
        return os.path.abspath(yaml_files[0])
    else:
        return None

def run_simulation(out_dir, core_name, kconfig_syms, isax_name, mlir_path):
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
    if tb_path.endswith(".s") or tb_path.endswith(".S"):
        print(f" - Adding ISAX assembly support to GCC")
        prepare_gcc(yaml_file_path)
        print(f" - Compiling assembly TB")
        instr_bin, data_bin = gcc_compile_tb(tb_path, core_name, out_dir)
        print(f" - Start simulation")
    else:
        print(f" - Adding ISAX support to clang")
        llvm_build_dir = prepare_llvm(mlir_path)
        print(f" - Compiling assembly TB")
        instr_bin, data_bin = llvm_compile_tb(tb_path, core_name, out_dir, llvm_build_dir, isax_name)
        print(f" - Start simulation")

    run_tb(out_dir, core_name, instr_bin, tb_expected_path)
