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
from pathlib import Path
import argparse
import json
import glob

parser = argparse.ArgumentParser(description="Run NailGun integration tests")
parser.add_argument("--output-dir", default="test_results",
                    help="Directory for test output (default: test_results)")
parser.add_argument("--show-results", metavar="FOLDER",
                    help="Display results table from a previous test run folder without re-running tests")
parser.add_argument("--core", "--cores", dest="cores", default=None,
                    help="Only run tests for the given core(s). Comma-separated list, "
                         "case-insensitive (e.g. 'CVA6' or 'CVA6,CVA5'). Default: all cores.")
parser.add_argument("-j", "--jobs", dest="jobs", type=int, default=os.cpu_count(),
                    help=f"Maximum number of parallel test jobs. Default: all available CPUs ({os.cpu_count()}).")
args = parser.parse_args()

if args.jobs < 1:
    print(f"--jobs must be >= 1 (got {args.jobs})", file=sys.stderr)
    exit(2)

MAX_SCALA_JOBS=8 #limit of parallel jobs on Scala/Spinal cores (try to avoid IOException on ionotify / open files limit)

# Add the parent directory to the sys.path (needed for error module)
parent_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_folder)
import error

def save_results_to_json(folder, results):
    """Save test results to a JSON file for later retrieval."""
    data = {
        "version": 1,
        "results": [{"id": id, "exit_code": exit_code, "command_env": cmd} for exit_code, cmd, id in results]
    }
    json_path = os.path.join(folder, "results.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)

def load_results_from_json(folder):
    """Load results from results.json."""
    json_path = os.path.join(folder, "results.json")
    with open(json_path, "r") as f:
        data = json.load(f)
    return [(r["exit_code"], r["command_env"], r["id"]) for r in data["results"]]

def infer_exit_code_from_log(log_content: str) -> int:
    """Heuristic to determine the exit code from log content."""
    lines = log_content.splitlines()
    tail = "\n".join(lines[-10:]) if len(lines) >= 10 else log_content

    if "Done!" in tail:
        return 0
    if "ERROR: The simulation of" in log_content:
        return error.SIM_BASE + 1
    if "ERROR: SCAIE-V failed" in log_content:
        return error.SCAIEV_BASE
    if "Could not build SCAIE-V" in log_content:
        return error.SCAIEV_BASE + 1
    if "Could not generate top module" in log_content:
        return error.SCAIEV_BASE + 3
    if "Could not compile" in log_content:
        return error.SCAIEV_BASE + 4
    if "Could not generate" in log_content:
        return error.SCAIEV_BASE + 5
    if "Could not build treenail" in log_content:
        return error.TN_BASE + 1
    if "ERROR:" in log_content:
        return error.INTERNAL_ERROR
    return -1

def reconstruct_results_from_logs(folder):
    """Reconstruct results from gzipped log files (backward compat)."""
    logs_dir = os.path.join(folder, "logs")
    if not os.path.isdir(logs_dir):
        print(f"Error: No logs/ directory found in {folder}")
        exit(1)

    log_files = sorted(glob.glob(os.path.join(logs_dir, "integration_test_*.log.gz")))
    results = []
    pattern = r'(\w+)="([^"]+)"'

    for log_file in log_files:
        # Extract test ID from filename
        basename = os.path.basename(log_file)
        id_str = basename.replace("integration_test_", "").replace(".log.gz", "")
        try:
            test_id = int(id_str)
        except ValueError:
            continue

        try:
            with gzip.open(log_file, "rt", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read {log_file}: {e}")
            continue

        lines = content.splitlines()
        if not lines:
            continue

        # Parse the command from the first line
        first_line = lines[0]
        # Format: "Starting test {id}, command: {full_command} make ci"
        cmd_marker = ", command: "
        if cmd_marker not in first_line:
            continue
        cmd = first_line[first_line.index(cmd_marker) + len(cmd_marker):]
        # Strip trailing " make ci" — the log includes it but the normal path doesn't
        if cmd.endswith(" make ci"):
            cmd = cmd[:-len(" make ci")]

        # Filter out non-test logs (init commands, compiler prep)
        matches = dict(re.findall(pattern, cmd))
        if "CORE" not in matches:
            continue
        if "TB_PATH" not in matches:
            continue
        if matches.get("ONLY_PATCH_CC") == "y":
            continue

        exit_code = infer_exit_code_from_log(content)
        results.append((exit_code, cmd, test_id))

    results.sort(key=lambda x: x[2])
    return results

def build_and_print_results_table(results):
    """Build and print the results summary table."""
    failed = 0
    for exit_code, cmd, id in results:
        if exit_code != 0:
            failed += 1
            print(f"Test {id} failed with exit code {exit_code}, cmd: '{cmd} make ci'")
    print(f"Summary: {len(results) - failed}/{len(results)} integration tests succeeded.")

    pattern = r'(\w+)="([^"]+)"'
    results_map = {}
    for exit_code, cmd, id in results:
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
            if tb_name.lower() != isax_name.lower():
                test_case_name = f"MLIR {isax_name} / {tb_name}"
            else:
                test_case_name = f"MLIR {isax_name}"
        elif len(isaxes) == 0:
            if tb_path.endswith(".elf") or tb_path.endswith(".axf"):
                test_case_name = "NO ISAX / " + tb_name
            else:
                test_case_name = "NO ISAX / " + ("llvm" if tb_path.endswith(".cpp") else "asm")
        elif len(isaxes) == 1:
            isax = isaxes[0]
            test_case_name = isax if tb_name.lower() == isax.lower() else f"{isax} / {tb_name}"
        else:
            test_case_name = f"MERGED / {tb_name}"

        if core not in results_map:
            results_map[core] = {}

        assert test_case_name not in results_map[core], f"Result for test case: '{test_case_name}' has already been registered for core = {core}, full cmd = {cmd}"
        results_map[core][test_case_name] = error.decode_exit_code(exit_code, id)

    df = pd.DataFrame(results_map)
    df = df.fillna("N/A")
    table = tabulate(df, headers='keys', tablefmt='fancy_grid', showindex=True)
    print(table)

    return failed

# Handle --show-results mode (no test execution)
if args.show_results is not None:
    folder = os.path.abspath(args.show_results)
    if not os.path.isdir(folder):
        print(f"Error: {folder} does not exist or is not a directory")
        exit(1)
    json_path = os.path.join(folder, "results.json")
    if os.path.exists(json_path):
        results = load_results_from_json(folder)
    else:
        print(f"No results.json found in {folder}, reconstructing from logs...")
        results = reconstruct_results_from_logs(folder)
    failed = build_and_print_results_table(results)
    exit(1 if failed > 0 else 0)

integration_test_working_dir = os.path.abspath(args.output_dir)
if os.path.exists(integration_test_working_dir):
    shutil.rmtree(integration_test_working_dir)
logs_dir = os.path.join(integration_test_working_dir, "logs")
os.makedirs(logs_dir)

import longnail
# Remove the parent directory from the sys.path again
sys.path.remove(parent_folder)

class CommandJob:
    def __init__(self, env_str: str, is_scala: bool):
        self.env_str = env_str
        self.is_scala = is_scala

isax_mlir_files = [
    os.path.join(parent_folder, "deps/longnail/sim/complex/complex.mlir"),
    os.path.join(parent_folder, "deps/longnail/sim/vector/vector.mlir"),
]
core_isaxes_merge_file = os.path.join(integration_test_working_dir, "ALL_ISAXES.mlir")

init_commands = [
    CommandJob('make gen_config', False),
    # Generate all core MLIR files
    CommandJob('CORE="CVA5" ISAXES="AUTOINC,BRIMM,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT,SQRT_STALL,TABLEJUMP,ZOL" make ci', False),
]

patch_compiler_commands = [
    # Prepare clang
    CommandJob(f'ONLY_PATCH_CC="y" CORE="CVA5" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="{core_isaxes_merge_file}" SIM_ENABLE="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt"', False),
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
    # Support for custom register banking to perform ctx switches
    MultiContext = auto()
    # Support for arbitrary many RF reads and writes per custom instruction
    MultiReadWrite = auto()
    # Support for arbitrary many MEM load and stores per custom instruction
    MultiLoadStore = auto()

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
    def __init__(self, env_str: str, required_features: list[CoreFeature], command_flags: CommandFlags):
        assert(isinstance(required_features, list))
        self.env_str = env_str
        self.required_features = required_features
        self.command_flags = command_flags
        self.cycle_timeout = SIM_CYCLE_TIMEOUT_DEFAULT
    def set_cycle_timeout(self, cycle_timeout: int):
        self.cycle_timeout = cycle_timeout
        return self

# Integration tests that are run for EVERY available core
# (cmd:str, required_features:CoreFeature, command_flags:CommandFlags)
command_templates = [
    CommandTemplate('ISAXES="MAC" SIM_ENABLE="y" TB_PATH="custom_tbs/mac.cpp" TB_EXPECTED_PATH="custom_tbs/mac_expected.txt"',
                    [CoreFeature.RdRD, CoreFeature.MultiReadWrite], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="AUTOINC" SIM_ENABLE="y" TB_PATH="custom_tbs/autoinc.cpp" TB_EXPECTED_PATH="custom_tbs/autoinc_expected.txt"',
                    [CoreFeature.Memory], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="AUTOINC" SIM_ENABLE="y" TB_PATH="custom_tbs/autoinc_multi_context.cpp" SCV_INTERNAL_CONTEXTS_AMOUNT="2" TB_EXPECTED_PATH="custom_tbs/autoinc_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.MultiContext], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="BRIMM" SIM_ENABLE="y" TB_PATH="custom_tbs/brimm.cpp" TB_EXPECTED_PATH="custom_tbs/brimm_expected.txt"',
                    [CoreFeature.Control], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="DOTPROD" SIM_ENABLE="y" TB_PATH="custom_tbs/dotprod.yaml" TB_EXPECTED_PATH="custom_tbs/dotprod_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    CommandTemplate('SIM_TB_COMPILE_FLAGS="-mcmodel=medany" ISAXES="INDIRECTJMP" SIM_ENABLE="y" TB_PATH="custom_tbs/indirectjmp.cpp" TB_EXPECTED_PATH="custom_tbs/indirectjmp_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.Control], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="TABLEJUMP" SIM_ENABLE="y" TB_PATH="custom_tbs/tablejump.cpp" TB_EXPECTED_PATH="custom_tbs/tablejump_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.Control], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SBOX" SIM_ENABLE="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SPARKLE" SIM_ENABLE="y" TB_PATH="custom_tbs/sparkle.cpp" TB_EXPECTED_PATH="custom_tbs/sparkle_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SQRT" SIM_ENABLE="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt"',
                    [CoreFeature.Decoupled], CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    CommandTemplate('SIM_TB_COMPILE_FLAGS="-DTB_USE_SQRT_STALL" ISAXES="SQRT_STALL" SIM_ENABLE="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    CommandTemplate('ISAXES="ZOL" SIM_ENABLE="y" TB_PATH="custom_tbs/zol.cpp" TB_EXPECTED_PATH="custom_tbs/zol_expected.txt" SIM_ISS_PREDEFINED_ISAXES="zol"',
                    [CoreFeature.Control], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="PUSHPOP" SIM_ENABLE="y" TB_PATH="custom_tbs/push_pop.cpp" TB_EXPECTED_PATH="custom_tbs/push_pop_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.MultiReadWrite | CoreFeature.MultiLoadStore], CommandFlags.EnableISSLockstep),
    CommandTemplate('LN_MAX_LOOP_UNROLL_FACTOR=32 ISAXES="INIT" SIM_ENABLE="y" TB_PATH="custom_tbs/init.cpp" TB_EXPECTED_PATH="custom_tbs/init_expected.txt"',
                    [CoreFeature.MultiReadWrite], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SWAP" SIM_ENABLE="y" TB_PATH="custom_tbs/swap.cpp" TB_EXPECTED_PATH="custom_tbs/swap_expected.txt"',
                    [CoreFeature.MultiReadWrite], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="SWITCHOP" SIM_ENABLE="y" TB_PATH="custom_tbs/switchop.cpp" TB_EXPECTED_PATH="custom_tbs/switchop_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.EnableISSLockstep),
    CommandTemplate('ISAXES="MULTIMEMREADWRITE" SIM_ENABLE="y" TB_PATH="custom_tbs/multi_mem_read_write.cpp" TB_EXPECTED_PATH="custom_tbs/multi_mem_read_write_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.MultiLoadStore], CommandFlags.EnableISSLockstep),
    CommandTemplate(f'SIM_TB_COMPILE_FLAGS="-DTB_FORCE_USE_MERGED" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="{core_isaxes_merge_file}" SIM_ENABLE="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.Control | CoreFeature.Decoupled], CommandFlags.EnableISSLockstep),
    CommandTemplate(f'SIM_TB_COMPILE_FLAGS="-DTB_FORCE_USE_MERGED" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="{core_isaxes_merge_file}" SIM_ENABLE="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt"',
                    [CoreFeature.Memory | CoreFeature.Control | CoreFeature.Decoupled], CommandFlags.EnableISSLockstep).set_cycle_timeout(80000),
    # MLIR entrypoint tests
    # complex ISAX
    CommandTemplate('LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/complex/complex.mlir" LN_CELL_LIBRARY="deps/longnail/sim/complex/library.yaml" SIM_ENABLE="y" TB_PATH="custom_tbs/complex.cpp" TB_EXPECTED_PATH="custom_tbs/complex_expected.txt" LN_OPTY_OL2_MODEL="y" LN_CLOCK_PERIOD="150.0"',
                    [CoreFeature.Decoupled], CommandFlags.EnableISSLockstep),
    # vector ISAX
    CommandTemplate('LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" COREDSL_MLIR_ENTRY_POINT="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/vector/vector.mlir" LN_CELL_LIBRARY="deps/longnail/sim/vector/library.yaml" SIM_ENABLE="y" TB_PATH="custom_tbs/vector.cpp" TB_EXPECTED_PATH="custom_tbs/vector_expected.txt" LN_OPTY_OL2_MODEL="y"',
                    [CoreFeature.Decoupled], CommandFlags.EnableISSLockstep),
    # Baseline tests asm
    CommandTemplate('NO_ISAX="y" SIM_ENABLE="y" TB_PATH="custom_tbs/dummy.S" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.NONE),
    # Baseline tests clang
    CommandTemplate('NO_ISAX="y" SIM_ENABLE="y" TB_PATH="custom_tbs/dummy.cpp" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"',
                    [CoreFeature.NONE], CommandFlags.NONE),
]

# (core:str, core_features:CoreFeature, is_scala: bool, timeout_scale:float)
cores = [
    ("CVA6",      CoreFeature.STANDARD | CoreFeature.ISSLockstep,                                                            False, 1.0),
    ("CVA6_DUAL", CoreFeature.STANDARD | CoreFeature.ISSLockstep,                                                            False, 1.0),
    ("CVA5",      CoreFeature.STANDARD | CoreFeature.RdRD | CoreFeature.ISSLockstep,                                         False, 1.0),
    ("PICORV32",  CoreFeature.STANDARD | CoreFeature.MultiContext,                                                           False, 3.0),
    ("PICCOLO",   CoreFeature.STANDARD | CoreFeature.MultiContext,                                                           False, 1.5),
    ("ORCA",      CoreFeature.STANDARD | CoreFeature.MultiContext,                                                           False, 2.0),
    ("VEX_4S",    CoreFeature.STANDARD | CoreFeature.MultiContext | CoreFeature.MultiReadWrite | CoreFeature.MultiLoadStore, True,  2.5),
    ("VEX_5S",    CoreFeature.STANDARD | CoreFeature.MultiContext | CoreFeature.MultiReadWrite | CoreFeature.MultiLoadStore, True,  2.0),
    ("CV32E40X",  CoreFeature.NONE,                                                                                          False, 2.0),
]

if args.cores is not None:
    requested = {c.strip().upper() for c in args.cores.split(",") if c.strip()}
    available = {entry[0].upper() for entry in cores}
    unknown = requested - available
    if unknown:
        print(f"Unknown core(s): {sorted(unknown)}. Available: {sorted(available)}", file=sys.stderr)
        exit(2)
    cores = [entry for entry in cores if entry[0].upper() in requested]
    print(f"Filtering to core(s): {[entry[0] for entry in cores]}", flush=True)

for core, core_features, is_scala, timeout_scale in cores:
    for template in command_templates:
        compatible = False
        for required_features in template.required_features:
            if (core_features & required_features) == required_features:
                compatible = True
                break
        # Filter out unsupported tests for the core
        if not compatible:
            continue
        cmd = template.env_str
        # Set cycle timeout using per-core scaling factor
        timeout_val = int(template.cycle_timeout * timeout_scale)
        cmd = cmd + f' SIM_CYCLE_TIMEOUT="{timeout_val}"'

        # Set ISS flag if requested and supported
        if (template.command_flags & CommandFlags.EnableISSLockstep) and (core_features & CoreFeature.ISSLockstep):
            cmd = cmd + ' SIM_ENABLE_ISS_LOCKSTEP="y"'

        # Run test in the parallel section once the all-ISAX compilers are built
        parallelizable_commands.append(CommandJob(f'SCAIEV_DO_NOT_REBUILD="y" CORE="{core}" {cmd}', is_scala))

def get_job_output_folder(id: int):
    return os.path.join(integration_test_working_dir, f"output_test_{id:03}")

def run_test(command_env: str, id: int, run_make_ci: bool, print_lock):
    kconfig_out_file = os.path.join(
        integration_test_working_dir, f".config_test_{id:03}")
    output_folder = get_job_output_folder(id)
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

    if parallel:
        num_threads = min(len(jobs), args.jobs)
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

# Collect all ISAX mlir files
_, _, gen_mlir_job_id = init_results[-1]
mlir_out_folder = os.path.join(get_job_output_folder(gen_mlir_job_id), "mlir")
isax_mlir_files.extend(
    str(p.resolve())
    for p in Path(mlir_out_folder).glob("*.mlir")
    if p.is_file()
)
# Merge all ISAXes into a single mlir file
premerge_file = core_isaxes_merge_file + ".tmp"
longnail.concat_mlir_files(isax_mlir_files, premerge_file)
longnail.merge_isaxes(integration_test_working_dir, longnail.get_default_longnail_bin(), premerge_file, core_isaxes_merge_file)
assert(os.path.exists(core_isaxes_merge_file))
os.remove(premerge_file)

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

# Save results to JSON for later retrieval via --show-results
save_results_to_json(integration_test_working_dir, results)

print("Done.")
failed = build_and_print_results_table(results)

# Exit with a non-zero code if any command failed
if failed != 0:
    exit(1)
