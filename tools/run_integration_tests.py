#!/usr/bin/env python3
import subprocess
import gzip
import os
import sys
import concurrent.futures
import threading
import shutil
import re
import datetime
import pandas as pd
from tabulate import tabulate
from enum import Flag, auto

MAX_SCALA_JOBS=8 #limit of parallel jobs on Scala/Spinal cores (try to avoid IOException on ionotify / open files limit)

# Add the parent directory to the sys.path
parent_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_folder)
import error
# Remove the parent directory from the sys.path again
sys.path.remove(parent_folder)

class CommandJob:
    def __init__(self, env_str: str, is_scala: bool):
        self.env_str = env_str
        self.is_scala = is_scala

init_commands = [
    CommandJob('make gen_config', False),
]

patch_compiler_commands = [
    # Prepare clang
    # Prepare gcc
]

# Lists of integration tests to run, tuples of (command_env: str, apply_scala_tasklimit: bool)
# Tests that must be executed sequentially without any other tests running simultaneously
sequential_commands: list[CommandJob] = [
]
# Tests that can be executed in parallel, once the compilers has been patched
parallelizable_commands: list[CommandJob] = [
]

SIM_CYCLE_TIMEOUT_DEFAULT=50000

# Flags indicating the advanced SCAIE-V features supported for a core.
class CoreFeature(Flag):
    # RdMem, WrMem
    Memory = auto()
    # Decoupled WrRD_spawn, (if Memory: RdMem_spawn,WrMem_spawn)
    Decoupled = auto()
    # WrPC, WrFlush (both in-pipeline and Fetch-stage always)
    Control = auto()
    # Read rd as third operand
    RdRD = auto()

    # Simulator supports tracing for ISS lockstep
    ISSLockstep = auto()

    # Only basic functionality required for arithmetic ISAXes (includes semi-coupled).
    # Includes RdInstr, RdPC, RdRS1/2, RdFlush, Rd/WrStall, WrRD, (custom registers via SCAL)
    NONE = 0
    # Advanced features present for all properly-supported cores
    STANDARD = Memory | Decoupled | Control

class CommandFlags(Flag):
    EnableISSLockstep = auto()
    NONE = 0

class CommandTemplate:
    def __init__(self, env_str: str, parallel: bool, required_features: CoreFeature, command_flags: CommandFlags):
        self.env_str = env_str
        self.parallel = parallel
        self.required_features = required_features
        self.command_flags = command_flags
        self.cycle_timeout = SIM_CYCLE_TIMEOUT_DEFAULT
    def set_cycle_timeout(self, cycle_timeout: int):
        self.cycle_timeout = cycle_timeout
        return self

# Integration tests that are run for EVERY available core
# (cmd:str, parallel:bool, required_features:CoreFeature, command_flags:CommandFlags)
command_templates = [
    CommandTemplate('ISAXES="AUTOINC" SIM_ENABLE="y" TB_PATH="custom_tbs/autoinc.cpp" TB_EXPECTED_PATH="custom_tbs/autoinc_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Memory, CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="AUTOINC" SIM_ENABLE="y" TB_PATH="custom_tbs/autoinc_multi_context.cpp" SCV_INTERNAL_CONTEXTS_AMOUNT="2" TB_EXPECTED_PATH="custom_tbs/autoinc_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Memory, CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="BRIMM" SIM_ENABLE="y" TB_PATH="custom_tbs/brimm.cpp" TB_EXPECTED_PATH="custom_tbs/brimm_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Control, CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="DOTPROD" SIM_ENABLE="y" TB_PATH="custom_tbs/dotprod.yaml" TB_EXPECTED_PATH="custom_tbs/dotprod_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.NONE, CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    CommandTemplate('SIM_TB_COMPILE_FLAGS="-mcmodel=medany" ISAXES="INDIRECTJMP" SIM_ENABLE="y" TB_PATH="custom_tbs/indirectjmp.cpp" TB_EXPECTED_PATH="custom_tbs/indirectjmp_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Memory | CoreFeature.Control, CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="TABLEJUMP" SIM_ENABLE="y" TB_PATH="custom_tbs/tablejump.cpp" TB_EXPECTED_PATH="custom_tbs/tablejump_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Memory | CoreFeature.Control, CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SBOX" SIM_ENABLE="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.NONE, CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SPARKLE" SIM_ENABLE="y" TB_PATH="custom_tbs/dummy.S" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"',
                    True, CoreFeature.NONE, CommandFlags.EnableISSLockstep),
    #TODO: Add CommandFlags.EnableISSLockstep to sqrt (disabled due to possible decoding bug in the generated ISAX model)
    CommandTemplate('ISAXES="SQRT" SIM_ENABLE="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Decoupled, CommandFlags.NONE).set_cycle_timeout(80000),
    CommandTemplate('SIM_TB_COMPILE_FLAGS="-DTB_USE_SQRT_STALL" ISAXES="SQRT_STALL" SIM_ENABLE="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.NONE, CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    CommandTemplate('ISAXES="ZOL" SIM_ENABLE="y" TB_PATH="custom_tbs/zol.cpp" TB_EXPECTED_PATH="custom_tbs/zol_expected.txt" SIM_TB_DISASSEMBLE_ELF="n" SIM_ISS_PREDEFINED_ISAXES="zol"',
                    True, CoreFeature.Control, CommandFlags.EnableISSLockstep),
    CommandTemplate('SIM_TB_COMPILE_FLAGS="-DTB_FORCE_USE_MERGED" ISAXES="AUTOINC,BRIMM,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT,TABLEJUMP" SIM_ENABLE="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Memory | CoreFeature.Control | CoreFeature.Decoupled, CommandFlags.EnableISSLockstep),
    CommandTemplate('SIM_TB_COMPILE_FLAGS="-DTB_FORCE_USE_MERGED" ISAXES="AUTOINC,BRIMM,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT,TABLEJUMP" SIM_ENABLE="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.Memory | CoreFeature.Control | CoreFeature.Decoupled, CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    # MLIR entrypoint tests
    # complex ISAX
    CommandTemplate('LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/complex/complex.mlir" LN_CELL_LIBRARY="deps/longnail/sim/complex/library.yaml" SIM_ENABLE="y" TB_PATH="custom_tbs/complex.S" TB_EXPECTED_PATH="custom_tbs/complex_expected.txt" LN_OPTY_OL2_MODEL="y" LN_CLOCK_PERIOD="150.0"',
                    False, CoreFeature.Decoupled, CommandFlags.EnableISSLockstep),
    # vector ISAX
    CommandTemplate('LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/vector/vector.mlir" LN_CELL_LIBRARY="deps/longnail/sim/vector/library.yaml" SIM_ENABLE="y" TB_PATH="custom_tbs/vector.S" TB_EXPECTED_PATH="custom_tbs/vector_expected.txt" LN_OPTY_OL2_MODEL="y"',
                    False, CoreFeature.Decoupled, CommandFlags.EnableISSLockstep),
    # Baseline tests gcc
    CommandTemplate('NO_ISAX="y" SIM_ENABLE="y" TB_PATH="custom_tbs/dummy.S" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"',
                    True, CoreFeature.NONE, CommandFlags.NONE),
    # Baseline tests clang
    CommandTemplate('NO_ISAX="y" SIM_ENABLE="y" TB_PATH="custom_tbs/dummy.cpp" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"',
                    True, CoreFeature.NONE, CommandFlags.NONE),
]

SIM_CYCLE_TIMEOUT_DEFAULT=50000

# (core:str, core_features:CoreFeature, is_scala: bool, timeout_scale:float)
cores = [
    ("CVA6",      CoreFeature.STANDARD | CoreFeature.ISSLockstep,                    False, 1.0),
    ("CVA6_DUAL", CoreFeature.STANDARD | CoreFeature.ISSLockstep,                    False, 1.0),
    ("CVA5",      CoreFeature.STANDARD | CoreFeature.RdRD | CoreFeature.ISSLockstep, False, 1.0),
    ("PICORV32",  CoreFeature.STANDARD,                                              False, 3.0),
    ("PICCOLO",   CoreFeature.STANDARD,                                              False, 1.5),
    ("ORCA",      CoreFeature.STANDARD,                                              False, 2.0),
    ("VEX_4S",    CoreFeature.STANDARD,                                              True,  2.5),
    ("VEX_5S",    CoreFeature.STANDARD,                                              True,  2.0),
    ("CV32E40X",  CoreFeature.NONE,                                                  False, 2.0),
]

for core, core_features, is_scala, timeout_scale in cores:
    for template in command_templates:
        if (core_features & template.required_features) != template.required_features:
            # Filter out unsupported tests for the core
            continue
        cmd = template.env_str
        # Set cycle timeout using per-core scaling factor
        timeout_val = int(template.cycle_timeout * timeout_scale)
        cmd = cmd + f' SIM_CYCLE_TIMEOUT="{timeout_val}"'

        # Set ISS flag if requested and supported
        if (template.command_flags & CommandFlags.EnableISSLockstep) and (core_features & CoreFeature.ISSLockstep):
            cmd = cmd + ' SIM_ENABLE_ISS_LOCKSTEP="y"'

        if template.parallel:
            # Run test in the parallel section once the all-ISAX compilers are built
            parallelizable_commands.append(CommandJob(f'CLANG_EXT_ISAX_NAME="merged" SIM_SKIP_AWESOME_LLVM="y" SCAIEV_DO_NOT_REBUILD="y" CORE="{core}" {cmd}', is_scala))
        else:
            # Run test sequentially, build compiler per run
            sequential_commands.append(CommandJob(f'CORE="{core}" {cmd}', False))

integration_test_working_dir = os.path.abspath("test_results")
if os.path.exists(integration_test_working_dir):
    shutil.rmtree(integration_test_working_dir)
logs_dir = os.path.join(integration_test_working_dir, "logs")
os.makedirs(logs_dir)

def run_test(command_env: str, id: int, run_make_ci: bool, print_lock):
    kconfig_out_file = os.path.join(
        integration_test_working_dir, f".config_test_{id:03}")
    output_folder = os.path.join(
        integration_test_working_dir, f"output_test_{id:03}")
    # create the output folder
    os.makedirs(output_folder)

    cmd_env_prefix = f"CONFIG_PATH={kconfig_out_file} OUTPUT_PATH={output_folder} "
    cmd_postfix_gen_conf = " make gen_ci_config" if run_make_ci else ""
    cmd_postfix_run = " python3 dispatch.py" if run_make_ci else ""
    output_file = os.path.join(logs_dir, f"integration_test_{id:03}.log.gz")

    commandLog = f"Starting test {id}, command: {cmd_env_prefix}{command_env} make ci"
    with print_lock:
        print(f" - {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')} {commandLog}", flush=True)

    with gzip.open(output_file, "w") as file:
        exit_code = None
        file.write((commandLog+"\n").encode("utf-8"))
        file.write(("="*80 + "\n\n\n").encode("utf-8"))
        with subprocess.Popen(
                cmd_env_prefix + command_env + cmd_postfix_gen_conf, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            shutil.copyfileobj(process.stdout, file)
            process.wait()
            exit_code = process.returncode
        if run_make_ci and exit_code in (0, None):
            with subprocess.Popen(
                    cmd_env_prefix + command_env + cmd_postfix_run, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                shutil.copyfileobj(process.stdout, file)
                process.wait()
                exit_code = process.returncode
    with print_lock:
        print(f" - {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')} Test {id} closed, exit code {exit_code}", flush=True)
    return exit_code, command_env, id

def run_tests(jobs: list[CommandJob], parallel: bool, id_offset: int = 0, run_make_ci: bool = True):
    if len(jobs) == 0:
        return []

    # Use the maximum number of threads available on the system
    if parallel:
        num_threads = min(len(jobs), os.cpu_count())
    else:
        num_threads = 1

    results = []
    print_lock = threading.Lock()
    scala_jobs_sem = threading.Semaphore(MAX_SCALA_JOBS)

    def run_test_sem(id, job_entry: CommandJob):
        """ Runs a job, acquiring scala_jobs_sem as required """
        if job_entry.is_scala:
            with scala_jobs_sem:
                return run_test(job_entry.env_str, id + id_offset, run_make_ci, print_lock)
        else:
            return run_test(job_entry.env_str, id + id_offset, run_make_ci, print_lock)

    # Create a ThreadPoolExecutor with the desired number of threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Submit tasks to the executor and store the Future objects
        futures = [executor.submit(run_test_sem, id + id_offset, job_entry) for id, job_entry in enumerate(jobs)]

        # Wait for all jobs to complete
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)

    results = sorted(results, key=lambda tpl:tpl[2]) #sort by id
    return results

print("Running commands to initialize integration tests", flush=True)
init_results = run_tests(init_commands, False, len(parallelizable_commands) + len(sequential_commands) + len(patch_compiler_commands), False)
for exit_code, cmd, id in init_results:
    if exit_code != 0:
        print(f"Initialization with exit code {exit_code}, cmd: '{cmd}'")
        exit(3)
# First run all tests that must be executed sequentially
print(f"Running {len(sequential_commands)} sequential tests", flush=True)
results = run_tests(sequential_commands, False)
# Then prepare the compilers, this can happen in parallel!
print(f"Prepare compilers for the parallel tests", flush=True)
prepare_compiler = run_tests(patch_compiler_commands, True, len(results) + len(parallelizable_commands))
# check results and abort on failure!
for exit_code, cmd, id in prepare_compiler:
    if exit_code != 0:
        print(f"Preparing parallel test execution failed with exit code {exit_code}, cmd: '{cmd} make ci'")
        exit(2)
print(f"Running {len(parallelizable_commands)} parallel tests", flush=True)
# Once the compilers are prepared, we can run ALL remaining tests in parallel
results += run_tests(parallelizable_commands, True, len(results))

# Sort results by test id
results.sort(key=lambda x: x[2])

print("Done.")
failed = 0
for exit_code, cmd, id in results:
    if exit_code != 0:
        failed += 1
        print(f"Test {id} failed with exit code {exit_code}, cmd: '{cmd} make ci'")
print(f"Summary: {len(results) - failed}/{len(results)} integration tests succeeded.")

# Regular expression to match the key-value pairs
pattern = r'(\w+)="([^"]+)"'

results_map = {}
for exit_code, cmd, id in results:
    # Use re.findall to find all make ci parameters
    matches = dict(re.findall(pattern, cmd))
    core = matches["CORE"]
    isaxes = matches["ISAXES"].split(",") if "ISAXES" in matches else []
    tb_path = matches["TB_PATH"]
    tb_name = os.path.splitext(os.path.basename(tb_path))[0]
    # Generate test case name
    test_case_name = ""
    if "MLIR_ENTRY_POINT_PATH" in matches:
        mlir_path =  matches["MLIR_ENTRY_POINT_PATH"]
        isax_name = os.path.splitext(os.path.basename(mlir_path))[0]
        test_case_name = f"MLIR {isax_name}"
    elif len(isaxes) == 0:
        if tb_path.endswith(".elf") or tb_path.endswith(".axf"):
            test_case_name = "NO ISAX / " + tb_name
        else:
            test_case_name = "NO ISAX / " + ("llvm" if tb_path.endswith(".cpp") else "gcc")
    elif len(isaxes) == 1:
        isax = isaxes[0]
        test_case_name = isax if tb_name.lower() == isax.lower() else f"{isax} / {tb_name}"
    else:
        test_case_name = f"MERGED / {tb_name}"

    if core not in results_map:
        results_map[core] = {}

    assert test_case_name not in results_map[core], f"Result for test case: '{test_case_name}' has already been registered for core = {core}, full cmd = {cmd}"
    results_map[core][test_case_name] = error.decode_exit_code(exit_code, id)

# Create DataFrame
df = pd.DataFrame(results_map)
# Replace None with a custom string like "N/A"
df = df.fillna("N/A")

# Convert the DataFrame to a formatted table with borders
table = tabulate(df, headers='keys', tablefmt='fancy_grid', showindex=True)
print(table)

# Exit with a non-zero code if any command failed
if failed != 0:
    exit(1)
