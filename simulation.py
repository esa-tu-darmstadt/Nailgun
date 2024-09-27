#!/usr/bin/env python3
import os
import functools
import glob
import shutil

import error
import run_cmd
import scaiev


def get_awesome_path():
    return "deps/awesome_llvm"

def llvm_repo_exists(version):
    llvm_repo = os.path.abspath(f"{get_awesome_path()}/compiler-patcher/build-tests/llvm-project/worktree/{version}")

    # Ensure the llvm repo is setup
    return os.path.exists(llvm_repo), llvm_repo

def llvm_build_dir(llvm_repo):
    return os.path.join(llvm_repo, "build")

def check_clang_exists(version):
    llvm_exists, llvm_repo = llvm_repo_exists(version)

    if not llvm_exists:
        return llvm_exists

    llvm_build_path = llvm_build_dir(llvm_repo)
    clang_path = os.path.join(llvm_build_path, "bin", "clang++")
    return os.path.exists(clang_path), clang_path

def prepare_llvm(mlir_path, version, rebuild):
    ccache_size = "25G"
    if os.getenv("AWESOME_CCACHE_SIZE"):
        ccache_size = os.getenv("AWESOME_CCACHE_SIZE")

    mlir_path = os.path.abspath(mlir_path)
    awesome_path = get_awesome_path()
    awesome_ln_bin = os.path.abspath(f"{awesome_path}/build/bin/longnail-opt")

    # Hard reset the llvm target repository
    llvm_exists, llvm_repo = llvm_repo_exists(version)

    # Ensure the llvm repo is setup
    if not llvm_exists:
        # Clone llvm
        run_cmd.run(".", f"git clone --depth=1 -b release/{version}.x https://github.com/llvm/llvm-project.git {llvm_repo}", f"Failed to clone LLVM {version}", error.AWESOME_BASE + 1, False)
        # Configure cmake
        ccache_path = os.path.abspath(f"{awesome_path}/compiler-patcher/build-tests/llvm-project/ccache")
        cmake_config = [
            "-DLLVM_ENABLE_PROJECTS=clang",
            "-DLLVM_TARGETS_TO_BUILD=RISCV",
            # When using enable runtimes, a default target triple is required
            "-DLLVM_DEFAULT_TARGET_TRIPLE=riscv32-unknown-elf",
            "-DLLVM_ENABLE_RUNTIMES=compiler-rt",
            # We need compiler-rt as a baremetal version!
            "-DCOMPILER_RT_BAREMETAL_BUILD=ON",
            # We are only interested in the builtins for software mul / div support
            "-DCOMPILER_RT_BUILD_BUILTINS=ON",
            "-DCOMPILER_RT_BUILD_MEMPROF=OFF",
            "-DCOMPILER_RT_BUILD_LIBFUZZER=OFF",
            "-DCOMPILER_RT_BUILD_PROFILE=OFF",
            "-DCOMPILER_RT_BUILD_SANITIZERS=OFF",
            "-DCOMPILER_RT_BUILD_XRAY=OFF",
            # "-DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON",
            # "-DLIBCXX_USE_COMPILER_RT=YES",
            # "-DLIBCXXABI_USE_COMPILER_RT=YES",
            # "-DCLANG_DEFAULT_RTLIB=compiler-rt",
            "-DBUILD_SHARED_LIBS=ON",
            "-DLLVM_CCACHE_BUILD=ON",
            f"-DLLVM_CCACHE_DIR='{ccache_path}'",
            f"-DLLVM_CCACHE_MAXSIZE={ccache_size}",
            "-DCMAKE_BUILD_TYPE=Debug",
        ]
        run_cmd.run(llvm_repo, f"cmake -S llvm -B build -G Ninja {functools.reduce(lambda a, b: a + ' ' + b, cmake_config)}", f"Failed to configure cmake for LLVM {version}", error.AWESOME_BASE + 2, False)
        rebuild = True # The desired version did not exists -> force rebuild

    build_dir = llvm_build_dir(llvm_repo)

    if rebuild:
        run_cmd.run(".", f"git -C {llvm_repo} reset --hard ", "Failed to reset the llvm work directory", error.AWESOME_BASE + 3, False)
        # Patch LLVM
        llvm_patcher = os.path.abspath(f"{awesome_path}/compiler-patcher/compiler-patcher.sh")
        pass_opts = "disableISelGen=true" # No ISel patterns for now
        run_cmd.run(".", f"{llvm_patcher} --coredsl-input {mlir_path} --longail-bin {awesome_ln_bin} --llvm-project-dir {llvm_repo} --llvm-version {version} -pass-opts '{pass_opts}'", f"Failed to patch LLVM {version} to add support for the selected ISAXes", error.AWESOME_BASE + 4, False, 200)
        # Build LLVM
        run_cmd.run(".", f"cmake --build {build_dir} -- all", f"Failed to build the patched LLVM {version}", error.AWESOME_BASE + 5, False, 200)

    return build_dir

def prepare_gcc(yaml_file):
    # Create GCC patches
    patched_files_dir = os.path.abspath("deps/scaie-v-testbenches/Scenario-HLS-DAC/opcodes")
    run_cmd.run(".", f"../tools/shady_gcc_patch_creator.py {yaml_file} {patched_files_dir}", "Could not patch gcc", error.GCC_BASE + 1, False)
    # Rebuild GCC
    run_cmd.run("deps/scaie-v-testbenches/dep", f"./riscv-gnu-build.sh {patched_files_dir}", "Recompiling the patched gcc failed!", error.GCC_BASE + 2, False)

def compile_tb(tb_path, core_name, out_dir, cc_path, objcopy_path, flags, additional_flags, error_code_base):
    # Create the output directory
    bin_dir = os.path.abspath(os.path.join(out_dir, "tb_bin"))
    os.makedirs(bin_dir, exist_ok=False)

    # Build elf file
    elf_file = os.path.join(bin_dir, "tb.elf")
    linker_file = scaiev.select_linker_file(core_name)
    run_cmd.run(".", f"{cc_path} {flags} {additional_flags} -T {linker_file} {tb_path} -o {elf_file}", "Compiling the test program failed!", error_code_base + 1, False)
    # Build instr bin file
    instr_bin_path = os.path.join(bin_dir, "core_name_instr.bin")
    instr_dump_flags = "-O binary -j .text.init -j .text"
    run_cmd.run(".", f"{objcopy_path} {instr_dump_flags} {elf_file} {instr_bin_path}", "Failed to extract instruction section from elf file!", error_code_base + 2, False)
    # Build data bin file
    data_bin_path = os.path.join(bin_dir, "core_name_data.bin")
    data_dump_flags = "-O binary -j .data -j .srodata -j .rodata -j .bss -j .sdata"
    run_cmd.run(".", f"{objcopy_path} {data_dump_flags} {elf_file} {data_bin_path}", "Failed to extract data section from elf file!", error_code_base + 3, False)

    return instr_bin_path, data_bin_path

def gcc_compile_tb(tb_path, core_name, out_dir, additional_flags):
    supported_core_exts = scaiev.select_compiler_extensions(core_name)
    gcc_path = os.path.abspath("deps/scaie-v-testbenches/dep/riscv-prefix/bin/riscv32-unknown-elf-gcc")
    objcopy_path = os.path.abspath("deps/scaie-v-testbenches/dep/riscv-prefix/bin/riscv32-unknown-elf-objcopy")
    arch_flags = f"-march=rv32{supported_core_exts} -mabi=ilp32"
    c_flags = "-nostdlib -nostartfiles"
    flags = f"{arch_flags} {c_flags}"

    return compile_tb(tb_path, core_name, out_dir, gcc_path, objcopy_path, flags, additional_flags, error.GCC_BASE + 2)

def llvm_compile_tb(tb_path, core_name, out_dir, llvm_build_path, isax_name, additional_flags, llvm_version):
    supported_core_exts = scaiev.select_compiler_extensions(core_name)
    clang_exists, clang_path = check_clang_exists(llvm_version)
    assert clang_exists
    objcopy_path = os.path.join(llvm_build_path, "bin", "llvm-objcopy")
    startup_asm = os.path.abspath(os.path.join("sim", "startup.s"))
    compiler_rt_flags = f"-lclang_rt.builtins -L {os.path.join(llvm_build_path, 'lib', 'clang', llvm_version, 'lib', 'riscv32-unknown-elf')}"
    flags = f'--target="riscv32-unknown-elf" -menable-experimental-extensions -mabi="ilp32" -march="rv32{supported_core_exts}_x{isax_name}0p1" -nostdlib -O3 {startup_asm} {compiler_rt_flags}'
    return compile_tb(tb_path, core_name, out_dir, clang_path, objcopy_path, flags, additional_flags, error.AWESOME_BASE + 5)

def run_tb(out_dir, core_name, instr_bin_path, tb_expected_path):
    # Create the output directory
    sim_dir = os.path.abspath(os.path.join(out_dir, "sim"))
    os.makedirs(sim_dir, exist_ok=False)

    external_tb_srcs, core_srcs, top_module, extra_makefile_opts = scaiev.select_tb_wrapper_srcs(core_name, out_dir)
    # Add absolute paths to the tb wrapper srcs
    wrapper_base = os.path.abspath("deps/scaie-v-testbenches/cores")
    external_tb_srcs = list(map(lambda s: os.path.join(wrapper_base, s), external_tb_srcs))
    # Copy the external tb_srcs to the sim folder, we do not want external dependencies!
    tb_srcs = []
    for s in external_tb_srcs:
        internal_tb_src = shutil.copy(s, sim_dir)
        tb_srcs.append(internal_tb_src)

    core_base = os.path.abspath(os.path.join(out_dir, core_name))
    core_srcs = list(map(lambda s: os.path.join(core_base, s), core_srcs))
    isax_src = list(map(lambda s: os.path.abspath(s), glob.glob(os.path.join(out_dir, '*.sv'))))
    isax_src = isax_src + list(map(lambda s: os.path.abspath(s), glob.glob(os.path.join(out_dir, '*.v'))))
    verilog_srcs = core_srcs + tb_srcs + isax_src

    # Find all .py files in the sim directory
    py_files = glob.glob(os.path.join("sim", '*.py'))

    # Copy each file to the output simulation folder
    for file in py_files:
        shutil.copy(file, sim_dir)

    # Convert the absolute verilog_srcs paths to relative paths from the sim directory
    verilog_srcs = [os.path.relpath(p, sim_dir) for p in verilog_srcs]

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
    run_cmd.run(sim_dir, f"OBJCACHE=ccache COCOTB_ANSI_OUTPUT=1 {functools.reduce(lambda a, b: a + ' ' + b, env_vars)} make sim && ! grep -nri 'Test failed' {results_xml_path}", "The simulation failed!", error.SIM_BASE + 1)

def find_yaml_file(out_dir):
    # Construct the search pattern
    search_pattern = os.path.join(out_dir, '*.yaml')
    # Use glob to find files matching the pattern
    yaml_files = glob.glob(search_pattern)
    if yaml_files:
        return os.path.abspath(yaml_files[0])
    else:
        return None

def run_simulation(out_dir, core_name, kconfig_syms, isax_name, mlir_path, only_add_cc_support):
    if not only_add_cc_support and kconfig_syms['SIM_ENABLE'].str_value != "y":
        return
    if not only_add_cc_support:
        print("Running full core + ISAX simulation:")
        if not os.path.exists(kconfig_syms['SIM_TB_PATH'].str_value):
            error.exit_error("Simulation testbench path is missing!", error.USER_ERROR)
        if not os.path.exists(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value):
            error.exit_error("Simulation testbench expected output path is missing!", error.USER_ERROR)
    else:
        print("Only adding ISAX compiler support")
    yaml_file_path = find_yaml_file(out_dir)
    tb_path = os.path.abspath(kconfig_syms['SIM_TB_PATH'].str_value)
    tb_expected_path = os.path.abspath(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value)
    additional_flags = kconfig_syms['SIM_TB_COMPILE_FLAGS'].str_value
    if tb_path.endswith(".s") or tb_path.endswith(".S"):
        print(" - Adding ISAX assembly support to GCC")
        if kconfig_syms['SIM_SKIP_AWESOME_LLVM'].str_value != "y":
            prepare_gcc(yaml_file_path)
        if not only_add_cc_support:
            print(" - Compiling assembly TB")
            instr_bin, data_bin = gcc_compile_tb(tb_path, core_name, out_dir, additional_flags)
    else:
        llvm_version = kconfig_syms['SIM_AWESOME_LLVM_VERSION'].str_value
        clang_exists, _ = check_clang_exists(llvm_version)
        skip_clang_build = kconfig_syms['SIM_SKIP_AWESOME_LLVM'].str_value == "y" and clang_exists
        if (not skip_clang_build) and (not mlir_path):
            error.exit_error("Patching clang requires a ISAX MLIR input file!", error.USER_ERROR)

        print(" - Adding ISAX support to clang")
        llvm_build_dir = prepare_llvm(mlir_path, llvm_version, not skip_clang_build)
        if not only_add_cc_support:
            print(" - Compiling C++ TB")
            if not isax_name:
                error.exit_error("Compiling the TB with clang requires an ISAX name to select the correct extension! The ISAX name can manually be overwritten via the 'SIM_AWESOME_LLVM_OVERWRITE_ISAX_NAME' option", error.USER_ERROR)
            instr_bin, data_bin = llvm_compile_tb(tb_path, core_name, out_dir, llvm_build_dir, isax_name, additional_flags, llvm_version)

    if not only_add_cc_support:
        print(" - Start simulation")
        run_tb(out_dir, core_name, instr_bin, tb_expected_path)
