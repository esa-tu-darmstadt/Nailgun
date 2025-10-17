#!/usr/bin/env python3
import subprocess
import gzip
import os
import sys
import concurrent.futures
import shutil
import re
import pandas as pd
from tabulate import tabulate


# Add the parent directory to the sys.path
parent_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_folder)
import error
# Remove the parent directory from the sys.path again
sys.path.remove(parent_folder)

init_commands = [
    'make gen_config',
]

patch_compiler_commands = [
    # Prepare clang
    # Prepare gcc
]

# List of integration tests to run
# Tests that must be executed sequentially without any other tests running simultaneously
sequential_commands = [
]
# Tests that can be executed in parallel, once the compilers has been patched
parallelizable_commands = [
    # RdRD is only supported on CVA5 & CVA6
]

# Integration tests that are run for EVERY available core
command_templates = [
    ('ISAXES="AUTOINC" SIM_EN="y" TB_PATH="custom_tbs/autoinc.cpp" TB_EXPECTED_PATH="custom_tbs/autoinc_expected.txt"', True),
    ('ISAXES="AUTOINC" SIM_EN="y" TB_PATH="custom_tbs/autoinc_multi_context.cpp" SCV_INTERNAL_CONTEXTS_AMOUNT="2" TB_EXPECTED_PATH="custom_tbs/autoinc_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"', True),
    ('ISAXES="BRIMM" SIM_EN="y" TB_PATH="custom_tbs/brimm.cpp" TB_EXPECTED_PATH="custom_tbs/brimm_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"', True),
    ('ISAXES="TABLEJUMP" SIM_EN="y" TB_PATH="custom_tbs/tablejump.cpp" TB_EXPECTED_PATH="custom_tbs/tablejump_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"', True),
    ('ISAXES="DOTPROD" SIM_EN="y" TB_PATH="custom_tbs/dotprod.yaml" TB_EXPECTED_PATH="custom_tbs/dotprod_expected.txt"', True),
    ('TB_CPP_FLAGS="-mcmodel=medany" ISAXES="INDIRECTJMP" SIM_EN="y" TB_PATH="custom_tbs/indirectjmp.cpp" TB_EXPECTED_PATH="custom_tbs/indirectjmp_expected.txt" SIM_TB_DISASSEMBLE_ELF="n"', True),
    ('ISAXES="SBOX" SIM_EN="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt"', True),
    ('ISAXES="SPARKLE" SIM_EN="y" TB_PATH="custom_tbs/dummy.S" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"', True),
    ('ISAXES="SQRT" SIM_EN="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt"', True),
    ('TB_CPP_FLAGS="-DTB_USE_SQRT_STALL" ISAXES="SQRT_STALL" SIM_EN="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt"', True),
    ('ISAXES="ZOL" SIM_EN="y" TB_PATH="custom_tbs/zol.cpp" TB_EXPECTED_PATH="custom_tbs/zol_expected.txt"', True),
    ('TB_CPP_FLAGS="-DTB_FORCE_USE_MERGED" ISAXES="AUTOINC,BRIMM,TABLEJUMP,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT" SIM_EN="y" TB_PATH="custom_tbs/sbox.cpp" TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt"', True),
    ('TB_CPP_FLAGS="-DTB_FORCE_USE_MERGED" ISAXES="AUTOINC,BRIMM,TABLEJUMP,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT" SIM_EN="y" TB_PATH="custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="custom_tbs/sqrt_expected.txt"', True),
    # MLIR entrypoint tests
    # complex ISAX
    ('LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/complex/complex.mlir" LN_CELL_LIBRARY="deps/longnail/sim/complex/library.yaml" SIM_EN="y" TB_PATH="custom_tbs/complex.S" TB_EXPECTED_PATH="custom_tbs/complex_expected.txt" USE_OL2_MODEL="y" CLOCK_TIME="150.0"', False),
    # vector ISAX
    ('LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/vector/vector.mlir" LN_CELL_LIBRARY="deps/longnail/sim/vector/library.yaml" SIM_EN="y" TB_PATH="custom_tbs/vector.S" TB_EXPECTED_PATH="custom_tbs/vector_expected.txt" USE_OL2_MODEL="y"', False),
    # Baseline tests gcc
    ('NO_ISAX="y" SIM_EN="y" TB_PATH="custom_tbs/dummy.S" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"', True),
    # Baseline tests clang
    ('NO_ISAX="y" SIM_EN="y" TB_PATH="custom_tbs/dummy.cpp" TB_EXPECTED_PATH="custom_tbs/dummy_expected.txt"', True),
]

cores = [
    "CVA6",
    "CVA5",
    "PICORV32",
    "PICCOLO",
    "ORCA",
    "VEX_4S",
    "VEX_5S",
]

for core in cores:
    for cmd, parallel in command_templates:
        if parallel:
            parallelizable_commands.append(f'CLANG_EXT_ISAX_NAME="merged" SKIP_AWESOME_LLVM="y" SCAIEV_DO_NOT_REBUILD="y" CORE="{core}" {cmd}')
        else:
            sequential_commands.append(f'CORE="{core}" {cmd}')

integration_test_working_dir = os.path.abspath("test_results")
if os.path.exists(integration_test_working_dir):
    shutil.rmtree(integration_test_working_dir)
logs_dir = os.path.join(integration_test_working_dir, "logs")
os.makedirs(logs_dir)


def run_test(command, id, run_make_ci):
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
    with gzip.open(output_file, "w") as file:
        exit_code = None
        file.write(f"Running command: {cmd_env_prefix}{command} make ci\n".encode("utf-8"))
        file.write(("="*80 + "\n\n\n").encode("utf-8"))
        with subprocess.Popen(
                cmd_env_prefix + command + cmd_postfix_gen_conf, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            shutil.copyfileobj(process.stdout, file)
            process.wait()
            exit_code = process.returncode
            if exit_code != 0:
                return exit_code, command, id
        if run_make_ci:
            with subprocess.Popen(
                    cmd_env_prefix + command + cmd_postfix_run, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                shutil.copyfileobj(process.stdout, file)
                process.wait()
                exit_code = process.returncode
        return exit_code, command, id


def run_tests(jobs, parallel, id_offset = 0, run_make_ci = True):
    if len(jobs) == 0:
        return []

    # Use the maximum number of threads available on the system
    if parallel:
        num_threads = min(len(jobs), os.cpu_count())
    else:
        num_threads = 1

    results = []
    # Create a ThreadPoolExecutor with the desired number of threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Submit tasks to the executor and store the Future objects
        futures = [executor.submit(run_test, job, id + id_offset, run_make_ci)
                   for id, job in enumerate(jobs)]

        # Wait for all jobs to complete
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
    return results

print("Running commands to initialize integration tests")
init_results = run_tests(init_commands, False, len(parallelizable_commands) + len(sequential_commands) + len(patch_compiler_commands), False)
for exit_code, cmd, id in init_results:
    if exit_code != 0:
        print(f"Initialization with exit code {exit_code}, cmd: '{cmd}'")
        exit(3)
# First run all tests that must be executed sequentially
print(f"Running {len(sequential_commands)} sequential tests")
results = run_tests(sequential_commands, False)
# Then prepare the compilers, this can happen in parallel!
print(f"Prepare compilers for the parallel tests")
prepare_compiler = run_tests(patch_compiler_commands, True, len(results) + len(parallelizable_commands))
# check results and abort on failure!
for exit_code, cmd, id in prepare_compiler:
    if exit_code != 0:
        print(f"Preparing parallel test execution failed with exit code {exit_code}, cmd: '{cmd} make ci'")
        exit(2)
print(f"Running {len(parallelizable_commands)} parallel tests")
# Once the compilers are prepared, we can run ALL remaining tests in parallel
results += run_tests(parallelizable_commands, True, len(results))

# Sort results by test id
results.sort(key=lambda x: x[2])

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
