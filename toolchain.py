import os
import functools
import shutil

import error
import longnail
import run_cmd
import scaiev
import picolibc

DYNAMIC_ISAX_PATH = "deps/llvm_dynamic_isax"
# llvm_dynamic_isax is a fork pinned to LLVM 21 — the compiler-rt install path
# (lib/clang/<major>/...) is derived from the fork's source tree.
DYNAMIC_ISAX_LLVM_MAJOR = "21"

def get_dynamic_isax_build_dir():
    return os.path.abspath(os.path.join(DYNAMIC_ISAX_PATH, "build"))

def check_dynamic_isax_clang_exists():
    build_dir = get_dynamic_isax_build_dir()
    clang_path = os.path.join(build_dir, "bin", "clang++")
    return os.path.exists(clang_path), clang_path

# ---------------------------------------------------------------------------
# Shared LLVM cmake configuration
# ---------------------------------------------------------------------------

def _configure_llvm_cmake(llvm_repo, ccache_path, ccache_size, error_code):
    """Run cmake configure for an LLVM build with RISC-V + compiler-rt support."""
    targets = [
        ("riscv32-unknown-elf", "-march=rv32i -mabi=ilp32"),
        ("riscv64-unknown-elf", "-march=rv64i -mabi=lp64"),
    ]
    build_type = "Debug"
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
        "COMPILER_RT_BUILD_CTX_PROFILE=OFF",
    ]
    if len(targets) > 1:
        compiler_rt_args = [f"-DRUNTIMES_{t}_{a}" for a in compiler_rt_arg_templates for t, _ in targets]
    else:
        compiler_rt_args = [f"-D{a}" for a in compiler_rt_arg_templates]
    compiler_rt_args += [f"-DRUNTIMES_{t}_CMAKE_C_FLAGS=\"{min_flags}\"" for t, min_flags in targets] \
                      + [f"-DRUNTIMES_{t}_CMAKE_CXX_FLAGS=\"{min_flags}\"" for t, min_flags in targets] \
                      + [f"-DRUNTIMES_{t}_CMAKE_ASM_FLAGS=\"{min_flags}\"" for t, min_flags in targets]

    cmake_config = [
        "-DLLVM_ENABLE_PROJECTS=clang",
        "-DLLVM_TARGETS_TO_BUILD=RISCV",
        f"-DLLVM_DEFAULT_TARGET_TRIPLE={targets[0][0]}",
        f"-DLLVM_RUNTIME_TARGETS=\"{';'.join([t for t, _ in targets])}\"",
        "-DLLVM_ENABLE_RUNTIMES=compiler-rt",
        "-DCOMPILER_RT_BAREMETAL_BUILD=ON",
        "-DBUILD_SHARED_LIBS=ON",
        "-DLLVM_CCACHE_BUILD=ON",
        f"-DLLVM_CCACHE_DIR='{ccache_path}'",
        f"-DLLVM_CCACHE_MAXSIZE={ccache_size}",
        f"-DCMAKE_BUILD_TYPE={build_type}",
        # Override the repo URL to add to header files: CI has credentials in the actual URL, so LLVM build errors out.
        f"-DLLVM_FORCE_VC_REPOSITORY=llvm_isax",
    ] + compiler_rt_args
    run_cmd.run(llvm_repo, f"cmake -S llvm -B build -G Ninja {functools.reduce(lambda a, b: a + ' ' + b, cmake_config)}", f"Failed to configure cmake for LLVM", error_code, False)

# ---------------------------------------------------------------------------
# LLVM prepare functions
# ---------------------------------------------------------------------------

def prepare_dynamic_isax_llvm():
    """Configure and build the dynamic ISAX LLVM if not already built.

    Returns the build directory path.
    """
    build_dir = get_dynamic_isax_build_dir()

    clang_exists, _ = check_dynamic_isax_clang_exists()
    if clang_exists:
        return build_dir

    ccache_size = os.getenv("LLVM_CCACHE_SIZE", "15G")
    llvm_repo = os.path.abspath(DYNAMIC_ISAX_PATH)
    ccache_path = os.path.abspath(os.path.join(DYNAMIC_ISAX_PATH, "ccache"))

    _configure_llvm_cmake(llvm_repo, ccache_path, ccache_size, error.LLVM_BASE + 9)
    run_cmd.run(".", f"cmake --build {build_dir} -- all", "Failed to build dynamic ISAX LLVM", error.LLVM_BASE + 10, False, 200)

    return build_dir

# ---------------------------------------------------------------------------
# ISAX analysis
# ---------------------------------------------------------------------------

def run_analyze_isax(mlir_path, out_dir):
    """Run the AnalyzeISAX pass on merged MLIR to produce a structured YAML.

    Returns the absolute path to the generated YAML file.
    """
    longnail_opt = longnail.get_default_longnail_bin()
    yaml_path = os.path.abspath(os.path.join(out_dir, "isax_analysis.yaml"))
    mlir_path = os.path.abspath(mlir_path)
    analysis_cmd = (
        f"{longnail_opt} "
        f"'--pass-pipeline=builtin.module(inline,analyze-isax{{output={yaml_path}}})' {mlir_path}"
    )
    run_cmd.run(".", analysis_cmd, "Failed to analyze ISAX MLIR", error.LLVM_BASE + 4, False, 200)
    return yaml_path

# ---------------------------------------------------------------------------
# Testbench compilation
# ---------------------------------------------------------------------------

def _find_tool(*names):
    """Find a tool binary by trying each name via shutil.which()."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    error.exit_error(f"Could not find any of: {', '.join(names)}", error.USER_ERROR)

def get_objcopy_path():
    return _find_tool("llvm-objcopy", "objcopy")

def get_objdump_path():
    return _find_tool("llvm-objdump", "objdump")

def disas_tb(objdump_path, elf_file, error_code, analysis_yaml_path=None):
    disas_path = elf_file + "_disasm.txt"
    disasm_flags = "-D"
    if analysis_yaml_path:
        disasm_flags += f" -mllvm=-isax-desc={os.path.abspath(analysis_yaml_path)}"
    run_cmd.run(".", f"{objdump_path} {disasm_flags} {elf_file} > {disas_path}", f"Failed to disassemble TB elf file '{elf_file}'!", error_code, False)

def compile_tb(tb_paths, core_support, elf_out_path, cc_path, objdump_path, flags, additional_flags, error_code_base, run_disassembly, custom_linker_script=None, analysis_yaml_path=None):
    # Build elf file
    linker_file = core_support.get_linker_file() if custom_linker_script is None else custom_linker_script
    if tb_paths:
        src_files_str = " ".join(tb_paths)
        run_cmd.run(".", f"{cc_path} {flags} {additional_flags} -T {linker_file} {src_files_str} -o {elf_out_path}", "Compiling the test program failed!", error_code_base + 1, False)

    # Build disassembly file
    if run_disassembly:
        disas_tb(objdump_path, elf_out_path, error_code_base + 2, analysis_yaml_path)

    return elf_out_path

def llvm_compile_tb(tb_paths, core_support, elf_out_path, additional_flags, run_disassembly, custom_linker_script=None, analysis_yaml_path=None, asm_only=False, include_startup_files=True):
    ext = core_support.get_extensions()
    march = f"rv{ext.xlen}{ext.get_compiler_extensions()}"

    build_dir = prepare_dynamic_isax_llvm()
    _, clang_path = check_dynamic_isax_clang_exists()
    isax_flags = f"-misax-desc={os.path.abspath(analysis_yaml_path)}" if analysis_yaml_path else ""

    bin_dir = os.path.join(build_dir, "bin")
    objdump_path = os.path.join(bin_dir, "llvm-objdump")

    if asm_only:
        # Minimal flags for assembly-only compilation (no picolibc/compiler-rt)
        flags = f'--target="riscv{ext.xlen}-unknown-elf" {isax_flags} -fuse-ld=lld -mabi="{ext.abi}" -march="{march}" -nostdlib -nostartfiles {core_support.get_specific_startup_file()}'
        if include_startup_files:
            startup_asm = os.path.abspath(os.path.join("sim", "startup_scripts", "startup.S"))
            flags += f" {startup_asm}"
    else:
        # Full C/C++ compilation with picolibc and compiler-rt
        ar_path = os.path.join(bin_dir, "llvm-ar")
        as_path = os.path.join(bin_dir, "llvm-as")
        nm_path = os.path.join(bin_dir, "llvm-nm")
        strip_path = os.path.join(bin_dir, "llvm-strip")

        pico_dir = picolibc.prepare_picolibc()
        env_vars = core_support.get_tb_env_vars()
        pico_inst_dir = picolibc.compile_picolibc(pico_dir, clang_path.removesuffix("++"), ar_path, as_path, nm_path, strip_path, march, ext.abi, scaiev.get_env_value(env_vars, "CTRL_BASE"))

        startup_asm = os.path.abspath(os.path.join("sim", "startup_scripts", "startup.S"))
        compiler_rt_flags = f"-lclang_rt.builtins -L {os.path.join(build_dir, 'lib', 'clang', DYNAMIC_ISAX_LLVM_MAJOR, 'lib', f'riscv{ext.xlen}-unknown-elf')}"
        picolibc_flags = f"-mcmodel=medany -L{pico_inst_dir}/lib -isystem {pico_inst_dir}/include -lc -Wl,--whole-archive -lsemihost -Wl,--no-whole-archive"
        flags = f'--target="riscv{ext.xlen}-unknown-elf" {isax_flags} -fuse-ld=lld -mabi="{ext.abi}" -march="{march}" -nostdlib -O3 {startup_asm} {core_support.get_specific_startup_file()} {compiler_rt_flags} {picolibc_flags}'

    return compile_tb(tb_paths, core_support, elf_out_path, clang_path, objdump_path, flags, additional_flags, error.LLVM_BASE + 5, run_disassembly, custom_linker_script, analysis_yaml_path)

def precompile_picolibc_for_all_cores():
    dyn_build_dir = prepare_dynamic_isax_llvm()
    clang_path = os.path.join(dyn_build_dir, "bin", "clang++")

    # Compile / prepare picolibc
    pico_dir = picolibc.prepare_picolibc()
    llvm_bin_dir = os.path.dirname(clang_path)
    ar_path = os.path.join(llvm_bin_dir, "llvm-ar")
    as_path = os.path.join(llvm_bin_dir, "llvm-as")
    nm_path = os.path.join(llvm_bin_dir, "llvm-nm")
    strip_path = os.path.join(llvm_bin_dir, "llvm-strip")

    for core_name in scaiev.get_known_cores():
        core_support = scaiev.get_core_support(core_name)
        env_vars = core_support.get_tb_env_vars()
        ext = core_support.get_extensions()
        march = f"rv{ext.xlen}{ext.get_compiler_extensions()}"
        pico_inst_dir = picolibc.compile_picolibc(pico_dir, clang_path.removesuffix("++"), ar_path, as_path, nm_path, strip_path, march, ext.abi, scaiev.get_env_value(env_vars, "CTRL_BASE"))
