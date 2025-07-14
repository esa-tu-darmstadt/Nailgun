#!/usr/bin/env python3
import os
import functools
import glob
import shutil

import error
import run_cmd
import scaiev
import longnail
import yaml
import renode

from tools.elftohex import elf_to_hex

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
        return llvm_exists, None

    llvm_build_path = llvm_build_dir(llvm_repo)
    clang_path = os.path.join(llvm_build_path, "bin", "clang++")
    return os.path.exists(clang_path), clang_path

def prepare_llvm(kconf_syms, mlir_path, version, rebuild, do_not_patch):
    ccache_size = "25G"
    if os.getenv("AWESOME_CCACHE_SIZE"):
        ccache_size = os.getenv("AWESOME_CCACHE_SIZE")

    mlir_path = os.path.abspath(mlir_path) if (mlir_path is not None) else None
    awesome_path = get_awesome_path()
    awesome_ln_bin = longnail.get_longnail_bin(kconf_syms, "AWESOME", os.path.basename(get_awesome_path()))

    # Hard reset the llvm target repository
    llvm_exists, llvm_repo = llvm_repo_exists(version)

    # Ensure the llvm repo is setup
    if not llvm_exists:
        # Clone llvm
        run_cmd.run(".", f"git clone --depth=1 -b release/{version}.x https://github.com/llvm/llvm-project.git {llvm_repo}", f"Failed to clone LLVM {version}", error.AWESOME_BASE + 1, False)
        # Configure cmake
        ccache_path = os.path.abspath(f"{awesome_path}/compiler-patcher/build-tests/llvm-project/ccache")
        targets = [
            ("riscv32-unknown-elf", "-march=rv32i -mabi=ilp32"),
            ("riscv64-unknown-elf", "-march=rv64i -mabi=lp64"),
        ]
        compiler_rt_arg_templates = [
            # We need compiler-rt as a baremetal version!
            "COMPILER_RT_BAREMETAL_BUILD=ON",
            # We are only interested in the builtins for software mul / div support
            "COMPILER_RT_BUILD_BUILTINS=ON",
            "COMPILER_RT_BUILD_MEMPROF=OFF",
            "COMPILER_RT_BUILD_LIBFUZZER=OFF",
            "COMPILER_RT_BUILD_PROFILE=OFF",
            "COMPILER_RT_BUILD_SANITIZERS=OFF",
            "COMPILER_RT_BUILD_XRAY=OFF",
            # "LIBCXX_USE_COMPILER_RT=YES",
            # "LIBCXXABI_USE_COMPILER_RT=YES",
            # "CLANG_DEFAULT_RTLIB=compiler-rt",
        ]
        compiler_rt_args = []
        if len(targets) > 1:
            compiler_rt_args = [ f"-DRUNTIMES_{t}_{a}" for a in compiler_rt_arg_templates for t, _ in targets]
        else:
            compiler_rt_args = compiler_rt_args + [ f"-D{a}" for a in compiler_rt_arg_templates]
        compiler_rt_args = compiler_rt_args + [ f"-DRUNTIMES_{t}_CMAKE_C_FLAGS=\"{min_support_flags}\"" for t, min_support_flags in targets] \
                                            + [ f"-DRUNTIMES_{t}_CMAKE_CXX_FLAGS=\"{min_support_flags}\"" for t, min_support_flags in targets] \
                                            + [ f"-DRUNTIMES_{t}_CMAKE_ASM_FLAGS=\"{min_support_flags}\"" for t, min_support_flags in targets]

        cmake_config = [
            "-DLLVM_ENABLE_PROJECTS=clang",
            "-DLLVM_TARGETS_TO_BUILD=RISCV",
            # When using enable runtimes, a default target triple is required
            f"-DLLVM_DEFAULT_TARGET_TRIPLE={targets[0][0]}",
            f"-DLLVM_RUNTIME_TARGETS=\"{';'.join([t for t, _ in targets])}\"",
            # "-DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON",
            "-DLLVM_ENABLE_RUNTIMES=compiler-rt",
            # We need compiler-rt as a baremetal version!
            "-DCOMPILER_RT_BAREMETAL_BUILD=ON",
            "-DBUILD_SHARED_LIBS=ON",
            "-DLLVM_CCACHE_BUILD=ON",
            f"-DLLVM_CCACHE_DIR='{ccache_path}'",
            f"-DLLVM_CCACHE_MAXSIZE={ccache_size}",
            "-DCMAKE_BUILD_TYPE=Debug",
        ] + compiler_rt_args
        run_cmd.run(llvm_repo, f"cmake -S llvm -B build -G Ninja {functools.reduce(lambda a, b: a + ' ' + b, cmake_config)}", f"Failed to configure cmake for LLVM {version}", error.AWESOME_BASE + 2, False)
        rebuild = True # The desired version did not exists -> force rebuild

    build_dir = llvm_build_dir(llvm_repo)

    if rebuild:
        run_cmd.run(".", f"git -C {llvm_repo} reset --hard ", "Failed to reset the llvm work directory", error.AWESOME_BASE + 3, False)
        # Patch LLVM
        if not do_not_patch:
            llvm_patcher = os.path.abspath(f"{awesome_path}/compiler-patcher/compiler-patcher.sh")
            pass_opts = "disableISelGen=true" # No ISel patterns for now
            run_cmd.run(".", f"{llvm_patcher} --coredsl-input {mlir_path} --longail-bin {awesome_ln_bin} --llvm-project-dir {llvm_repo} --llvm-version {version} -pass-opts '{pass_opts}'", f"Failed to patch LLVM {version} to add support for the selected ISAXes", error.AWESOME_BASE + 4, False, 200)
        # Build LLVM
        run_cmd.run(".", f"cmake --build {build_dir} -- all", f"Failed to build the {'unpatched' if do_not_patch else 'patched'} LLVM {version}", error.AWESOME_BASE + 5, False, 200)

    return build_dir

def prepare_gcc(kconfig_syms, yaml_file):
    # Create GCC patches
    patched_files_dir = os.path.abspath("deps/scaie-v-testbenches/Scenario-HLS-DAC/opcodes")
    run_cmd.run(".", f"tools/shady_gcc_patch_creator.py {yaml_file} {patched_files_dir}", "Could not patch gcc", error.GCC_BASE + 1, False)
    build_args = ""
    if kconfig_syms['SIM_SKIP_GDB'].str_value == "y":
        build_args += "--disable-gdb"
    # Rebuild GCC
    run_cmd.run("deps/scaie-v-testbenches/dep", f"./riscv-gnu-build.sh {build_args} {patched_files_dir}", "Recompiling the patched gcc failed!", error.GCC_BASE + 2, False)

def get_target_elf_file_path(out_dir):
    # Create the output directory
    bin_dir = os.path.abspath(os.path.join(out_dir, "tb_bin"))
    os.makedirs(bin_dir, exist_ok=True)

    # elf file path
    return os.path.join(bin_dir, "tb.elf")

def disas_tb(objdump_path, elf_file, error_code):
    disas_path = elf_file + "_disasm.txt"
    disasm_flags = "-D"
    run_cmd.run(".", f"{objdump_path} {disasm_flags} {elf_file} > {disas_path}", f"Failed to disassemble TB elf file '{elf_file}'!", error_code, False)

def compile_tb(tb_paths, core_name, out_dir, cc_path, objdump_path, flags, additional_flags, error_code_base, run_disassembly, custom_linker_script=None):
    # Build elf file
    elf_file = get_target_elf_file_path(out_dir)
    linker_file = scaiev.select_linker_file(core_name) if custom_linker_script is None else custom_linker_script
    if tb_paths:
        src_files_str = " ".join(tb_paths)
        run_cmd.run(".", f"{cc_path} {flags} {additional_flags} -T {linker_file} {src_files_str} -o {elf_file}", "Compiling the test program failed!", error_code_base + 1, False)

    # Build disassembly file
    if run_disassembly:
        disas_tb(objdump_path, elf_file, error_code_base + 2)

    return elf_file

def core_specific_startup(core_name):
    core_specific_asm = os.path.abspath(os.path.join("sim", "startup_scripts", f"{core_name}_init.s"))
    if os.path.exists(core_specific_asm):
        return f"-DASM_PERCOREENTRY=\\\"{core_specific_asm}\\\""
    return ""

GNU_PREFIXES=["riscv64-unknown-elf-", "riscv32-unknown-elf-"]
def get_gnu_util_path(pathformat, prefixes):
    """Get the absolute path to a GNU utility using the first prefix that exists.
    :param pathformat: a string with '%s' in place of the tool prefix
    :param prefixes: a list of tool prefixes to try (e.g., "riscv32-unknown-elf-")
    """
    for cur_prefix in prefixes:
        cur_path = os.path.abspath(pathformat % cur_prefix)
        if os.path.exists(cur_path):
            return cur_path
    return os.path.abspath(pathformat)
def get_gcc_objcopy_path():
    return get_gnu_util_path("deps/scaie-v-testbenches/dep/riscv-prefix/bin/%sobjcopy", GNU_PREFIXES)
def get_gcc_objdump_path():
    return get_gnu_util_path("deps/scaie-v-testbenches/dep/riscv-prefix/bin/%sobjdump", GNU_PREFIXES)

def gcc_compile_tb(tb_paths, core_name, out_dir, additional_flags, run_disassembly, custom_linker_script=None, include_startup_files=False):
    supported_core_exts, abi, bit = scaiev.select_compiler_extensions(core_name)
    gcc_path = get_gnu_util_path("deps/scaie-v-testbenches/dep/riscv-prefix/bin/%sgcc", GNU_PREFIXES)
    objdump_path = get_gcc_objdump_path()
    arch_flags = f"-march=rv{bit}{supported_core_exts} -mabi={abi}"
    c_flags = "-nostdlib -nostartfiles"
    flags = f"{arch_flags} {c_flags} {core_specific_startup(core_name)}"
    # these sources should only be used when the input is not ASM but source compiled
    if include_startup_files:
        flags += " " + os.path.abspath(os.path.join("sim", "startup_scripts", "startup.S"))

    return compile_tb(tb_paths, core_name, out_dir, gcc_path, objdump_path, flags, additional_flags, error.GCC_BASE + 2, run_disassembly, custom_linker_script)

def llvm_compile_tb(tb_paths, core_name, out_dir, llvm_build_path, isax_name, additional_flags, llvm_version, run_disassembly, custom_linker_script=None):
    if isax_name:
        def legalize_isax_name(isax_name):
            return isax_name.lower().replace("_", "").replace(".", "")
        isax_name = legalize_isax_name(isax_name)

    supported_core_exts, abi, bit = scaiev.select_compiler_extensions(core_name)
    clang_exists, clang_path = check_clang_exists(llvm_version)
    assert clang_exists
    startup_asm = os.path.abspath(os.path.join("sim", "startup_scripts", "startup.S"))
    compiler_rt_flags = f"-lclang_rt.builtins -L {os.path.join(llvm_build_path, 'lib', 'clang', llvm_version, 'lib', f'riscv{bit}-unknown-elf')}"
    isax_ext_name = f"_x{isax_name}0p1" if isax_name else ""
    flags = f'--target="riscv{bit}-unknown-elf" -menable-experimental-extensions -mabi="{abi}" -march="rv{bit}{supported_core_exts}{isax_ext_name}" -nostdlib -O3 {startup_asm} {core_specific_startup(core_name)} {compiler_rt_flags}'
    objdump_path = os.path.join(llvm_build_path, "bin", "llvm-objdump")
    return compile_tb(tb_paths, core_name, out_dir, clang_path, objdump_path, flags, additional_flags, error.AWESOME_BASE + 5, run_disassembly, custom_linker_script)

def run_tb(kconfig_syms, out_dir, core_name, isax_yaml_path, elf_files, tb_expected_paths, memory_config=None, gls=None):
    # Create the output directory
    sim_dir = os.path.abspath(os.path.join(out_dir, "sim"))
    os.makedirs(sim_dir, exist_ok=False)

    external_tb_srcs, core_srcs, tb_top_module, core_top_module, include_dirs, defines, extra_makefile_opts = scaiev.select_tb_wrapper_srcs(core_name, out_dir)

    # Convert extra_makefile_opts dictionary into strings
    extra_makefile_opts_strs = []
    # Check if "default" exists and add it unconditionally
    if "default" in extra_makefile_opts:
        extra_makefile_opts_strs.append(extra_makefile_opts["default"])

    # Generate the ifeq statements for other entries
    for key, value in extra_makefile_opts.items():
        if key != "default":
            extra_makefile_opts_strs.append(f"ifeq ($(SIM), {key})")
            extra_makefile_opts_strs.append(value)
            extra_makefile_opts_strs.append(f"endif # SIM == {key}")

    # Add absolute paths to the tb wrapper srcs
    wrapper_base = os.path.abspath("deps/scaie-v/util/maketop")
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
    # Also copy additionally required tools
    py_files.append(os.path.join("tools", "isax_yaml_tools.py"))

    # Copy each file to the output simulation folder
    for file in py_files:
        shutil.copy(file, sim_dir)

    assert(len(tb_expected_paths) == len(elf_files))
    # Copy expected output file next to the elf file
    copied_expected_paths = [os.path.join(os.path.dirname(get_target_elf_file_path(out_dir)), os.path.basename(tb_expected_path)) for tb_expected_path in tb_expected_paths]
    for in_path, out_path in zip(tb_expected_paths, copied_expected_paths):
        shutil.copy(in_path, out_path)

    # Convert the absolute verilog_srcs paths to relative paths from the sim directory
    verilog_srcs = [os.path.relpath(p, sim_dir) for p in verilog_srcs]

    def gen_testprog_arg(elf_file):
        return f"TESTPROG=\"{os.path.relpath(elf_file[:-len('.elf')], sim_dir)}\""
    def gen_expected_res_arg(expected_path):
        return f'EXPECTED="{os.path.relpath(expected_path, sim_dir)}"'

    env_vars = [
        "TESTPROG=$(TESTPROG)",
        "EXPECTED=$(EXPECTED)",
        f"CORE_NAME={core_name}",
        f"ISAX_YAML={os.path.relpath(isax_yaml_path, sim_dir)}",
        f"CYCLE_TIMEOUT={kconfig_syms['SIM_CYCLE_TIMEOUT'].str_value}",
        f"PRINT_CLK={1 if kconfig_syms['SIM_PRINT_CLK'].str_value == 'y' else 0}",
        f"PRINT_IMEM={1 if kconfig_syms['SIM_PRINT_IMEM'].str_value == 'y' else 0}",
        f"PRINT_DMEM={1 if kconfig_syms['SIM_PRINT_DMEM'].str_value == 'y' else 0}",
        f"PRINT_BRAM={1 if kconfig_syms['SIM_PRINT_BRAM'].str_value == 'y' else 0}",
        f"PRINT_AXI={1 if kconfig_syms['SIM_PRINT_AXI'].str_value == 'y' else 0}",
    ] + scaiev.select_tb_env_vars(core_name)

    newline = "\n"

    defines_common = [f"EXTRA_ARGS += -D{d}" for d in defines]
    defines_questa = [f"EXTRA_ARGS += +define+{d}" for d in defines]
    include_dirs = [f"EXTRA_ARGS += -I{os.path.relpath(os.path.join(core_base, inc), sim_dir)}" for inc in include_dirs]

    # questa and GLS setup
    if memory_config is not None:
        memory_initializers = list(map(lambda hex_config: f"SIM_ARGS += -g{hex_config[1]['instance_parameter']}=\"../tb_bin/{hex_config[0]}\"", memory_config["convert_to_hex"].items()))
    else:
        memory_initializers = []
    
    memory_initializers = "\n".join(memory_initializers)
    standard_cell_sources = netlist_file = sdf = ""
    if gls is not None:
        netlist_file = gls["netlist"]
        sdf = gls.get("sdf", "")
        cell_paths = gls["cells"]
        standard_cell_sources = list(map(lambda cell_verilog: f"VERILOG_SOURCES += {cell_verilog}", cell_paths))
        standard_cell_sources = "\n".join(standard_cell_sources)

    # Create a makefile to run the simulation
    sim_mk = os.path.join(sim_dir, "Makefile")
    with open(sim_mk, 'w') as f:
        f.write(f"""
VERILOG_SOURCES = {functools.reduce(lambda a, b: a + " " + b, verilog_srcs)}
TOPLEVEL_LANG = verilog
TOPLEVEL = {tb_top_module}
MODULE ?= test_default
SIM ?= verilator
GLS ?= 0
GUI ?= 0
# dump waveforms for icarus, questa, ...
WAVES ?= 1

TESTPROG ?= {os.path.relpath(elf_files[0][:-len('.elf')], sim_dir)}
EXPECTED ?= {os.path.relpath(copied_expected_paths[0], sim_dir)}

# Verilator specific flags
ifeq ($(SIM), verilator)
ifeq ($(GLS), 1)
$(error GLS not implemented with verilator. Use SIM=questa to run GLS.)
endif # GLS == 1
# Do not treat warnings as fatal errors!
EXTRA_ARGS += -Wno-fatal
# Enable assertions
EXTRA_ARGS += --assert
# Tracing options
EXTRA_ARGS += --trace-fst --trace --trace-structs --trace-underscore
# Use more than one core to compile the simulation models
BUILD_ARGS += -j$(shell nproc)
EXTRA_ARGS += --no-timing
endif # SIM == verilator

# Questa specific flags
ifeq ($(SIM), questa)
ifeq ($(GLS), 1)
# It is recommended that you create a new testbench (e.g., test_gls.py) to change the testbench to your chip design and pass it with MODULE=test_gls to your make invocation.
NETLIST_FILE = {netlist_file}

ifeq ($(NETLIST_FILE),)
$(error NETLIST_FILE is undefined. Set to your netlist verilog file path.)
endif # NETLIST_FILE == ""
# Overwrite the verilog sources to use the synthesized netlist instead
VERILOG_SOURCES = $(NETLIST_FILE)
{standard_cell_sources}


SDF_FILE={sdf}
ifneq ($(SDF_FILE),)
SDFTYPE ?= -sdfmax
SIM_ARGS += $(SDFTYPE) $(SDF_FILE)
else
COMPILE_ARGS += +delay_mode_unit
EXTRA_ARGS += +define+IVCS_INIT_MEM
endif # SDF_FILE != ""
endif # GLS == 1
{memory_initializers}
endif # SIM == questa

# Include directories
{newline.join(include_dirs)}
# Defines
ifeq ($(SIM), questa)
{newline.join(defines_questa)}
else
{newline.join(defines_common)}
endif

# Extra Makefile options
{newline.join(extra_makefile_opts_strs)}

# test_default.py configuration settings
PLUSARGS = ""
{newline.join([f'PLUSARGS += "+{var}"' for var in env_vars])}

include $(shell cocotb-config --makefiles)/Makefile.sim
""")

    results_xml_path = os.path.join(sim_dir, "results.xml")
    for elf_file, expected_path in zip(elf_files, copied_expected_paths):
        # We ALWAYS want colors, lol
        run_cmd.run(sim_dir, f"{gen_testprog_arg(elf_file)} {gen_expected_res_arg(expected_path)} OBJCACHE=ccache COCOTB_ANSI_OUTPUT=1 make sim && ! grep -nri 'Test failed' {results_xml_path}", f"The simulation of '{elf_file}' failed!", error.SIM_BASE + 1)

def setup_renode(isax_name, tb_paths, core_name, out_dir, yaml_file):
    env_vars = scaiev.select_tb_env_vars(core_name)
    def get_env_value(key):
        prefix = f"{key}="
        for entry in env_vars:
            if entry.startswith(prefix):
                return entry[len(prefix):]
        error.exit_error(f"Setup renode: scaiev.select_tb_env_vars variable '{key}' not found", error.INTERNAL_ERROR)

    supported_core_exts, abi, bit = scaiev.select_compiler_extensions(core_name)
    march = f"rv{bit}{supported_core_exts}"
    renode_dir = renode.gen_renode_confs(isax_name, out_dir, yaml_file, tb_paths[0], march, get_env_value("IMEM_BASE"), get_env_value("DMEM_BASE"), get_env_value("DMEM_SIZE"))
    shutil.copy("deps/longnail/sim/ArbInt.py", renode_dir)
    shutil.copy(os.path.join(out_dir, f"{isax_name}.py"), renode_dir)

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
    isax_yaml_path = find_yaml_file(out_dir)
    tb_path = os.path.abspath(kconfig_syms['SIM_TB_PATH'].str_value)
    tb_expected_path = os.path.abspath(kconfig_syms['SIM_TB_EXPECTED_PATH'].str_value)
    tb_expected_paths = [tb_expected_path]
    additional_flags = kconfig_syms['SIM_TB_COMPILE_FLAGS'].str_value
    disassemble_tb = kconfig_syms['SIM_TB_DISASSEMBLE_ELF'].str_value == "y"

    def patch_and_compile_with_gcc(filepaths, custom_linker_script=None, include_startup_files=False):
        print(" - Adding ISAX assembly support to GCC")
        if kconfig_syms['SIM_SKIP_AWESOME_LLVM'].str_value != "y":
            prepare_gcc(kconfig_syms, isax_yaml_path)
        if not only_add_cc_support:
            print(" - Compiling assembly TB")
            return gcc_compile_tb(filepaths, core_name, out_dir, additional_flags, disassemble_tb, custom_linker_script, include_startup_files=include_startup_files)
    
    def patch_and_compile_with_llvm(filepaths, custom_linker_script=None):
        llvm_version = kconfig_syms['SIM_AWESOME_LLVM_VERSION'].str_value
        clang_exists, _ = check_clang_exists(llvm_version)
        skip_clang_build = kconfig_syms['SIM_SKIP_AWESOME_LLVM'].str_value == "y" and clang_exists
        unpatched_clang = (not skip_clang_build) and (not mlir_path)
        if unpatched_clang:
            print("WARNING: Patching clang requires a ISAX MLIR input file!")
            print("INFO: Using unpatched clang!")
        else:
            print(" - Adding ISAX support to clang")
        llvm_build_dir = prepare_llvm(kconfig_syms, mlir_path, llvm_version, not skip_clang_build, unpatched_clang)
        if not only_add_cc_support:
            print(" - Compiling C++ TB")
            if not unpatched_clang and not isax_name:
                error.exit_error("Compiling the TB with clang requires an ISAX name to select the correct extension! The ISAX name can manually be overwritten via the 'SIM_AWESOME_LLVM_OVERWRITE_ISAX_NAME' option", error.USER_ERROR)
            return llvm_compile_tb(filepaths, core_name, out_dir, llvm_build_dir, isax_name, additional_flags, llvm_version, disassemble_tb, custom_linker_script)

    def process_bin_file(bin_file, elf_file, first_run):
        # Convert axf to elf_file
        if bin_file.endswith(".axf"):
            if first_run and kconfig_syms['SIM_SKIP_AWESOME_LLVM'].str_value != "y":
                prepare_gcc(kconfig_syms, isax_yaml_path)
            objcopy_path = get_gcc_objcopy_path()
            run_cmd.run(".", f"{objcopy_path} {bin_file} {elf_file}", "Failed to convert axf file to an elf file!", error.GCC_BASE + 5, False)
        else:
            # copy the elf file to our target folder
            shutil.copy(bin_file, elf_file)

    memory_config = None
    gls = None
    if tb_path.endswith(".axf") or tb_path.endswith(".elf"):
        elf_file = get_target_elf_file_path(out_dir)
        process_bin_file(tb_path, elf_file, first_run=True)
        # If requested disassemble the elf file
        if disassemble_tb:
            objdump_path = get_gcc_objdump_path()
            disas_tb(objdump_path, elf_file, error.GCC_BASE + 4)
        elf_files = [elf_file]
    elif tb_path.endswith(".s") or tb_path.endswith(".S"):
        elf_files = [patch_and_compile_with_gcc([tb_path])]
    elif tb_path.endswith(".yml") or tb_path.endswith(".yaml"):
        shutil.copy(tb_path, out_dir)
        with open(tb_path, "r") as yamlfile:
            test_config = yaml.safe_load(yamlfile)

        gls = test_config.get("gls", None)
        compiler = test_config.get("compiler", None)
        if type(compiler) == str:
            error.exit_error(f"Specify the compiler via the `name` property", error.USER_ERROR)
        compiler_name = compiler.get("name", None)
        gcc_use_startup_files = compiler.get("gcc include startup asm", False)
        files = test_config.get("files", [])
        if len(files) == 0:
            error.exit_error(f"Field testbench `files` is missing or empty", error.USER_ERROR)

        multi_binary_test = all([f.endswith(".axf") or f.endswith(".elf") for f in files])

        tb_folder = os.path.dirname(tb_path)
        absolute_file_paths = [f if os.path.isabs(f) else os.path.join(tb_folder, f) for f in files]

        if multi_binary_test:
            first_run = True
            elf_files = []
            root, ext = os.path.splitext(get_target_elf_file_path(out_dir))
            for idx, f in enumerate(absolute_file_paths):
                target_elf_file = f"{root}_{idx}{ext}"
                elf_files.append(target_elf_file)
                process_bin_file(f, target_elf_file, first_run=first_run)
                first_run = False
            # For now just replicate the expected path... TODO add support for specifiying for each tb file a different expected file
            tb_expected_paths = tb_expected_paths * len(absolute_file_paths)
        else:
            custom_linker_script = None
            memory_config = test_config.get("memory", None)
            if memory_config is not None:
                custom_linker_script = memory_config.get("linker_script", None)
                if custom_linker_script is not None:
                    custom_linker_script = os.path.join(tb_folder, custom_linker_script)
                    print(f"Using custom linker script {custom_linker_script}")

            if compiler_name == "gcc":
                elf_file = patch_and_compile_with_gcc(absolute_file_paths, custom_linker_script, include_startup_files=gcc_use_startup_files)
            elif compiler_name == "clang":
                elf_file = patch_and_compile_with_llvm(absolute_file_paths, custom_linker_script)
            else:
                error.exit_error(f"Unknown compiler name '{compiler_name}'. Either use 'gcc' or 'clang'.", error.USER_ERROR)

            if memory_config is not None:
                for hex_name, hex_config in memory_config.get("convert_to_hex", {}).items():
                    section_names = hex_config["sections"]
                    print(f"Dumping sections {section_names} to file {hex_name}")
                    memory_size = int(hex_config["size"])
                    bytes_per_word = int(hex_config["word_width"])
                    elf_to_hex(elf_file, os.path.abspath(os.path.join(out_dir, "tb_bin", hex_name)), section_names, word_size=bytes_per_word, memory_size=memory_size)
            elf_files = [elf_file]
    else:
        elf_files = [patch_and_compile_with_llvm([tb_path])]

    if not only_add_cc_support:
        setup_renode(isax_name, elf_files, core_name, out_dir, isax_yaml_path)
        print(" - Start simulation")
        run_tb(kconfig_syms, out_dir, core_name, isax_yaml_path, elf_files, tb_expected_paths, memory_config, gls)
