#!/usr/bin/env python3
import subprocess
import gzip
import os
import concurrent.futures
import shutil

# List of integration tests to run
commands = [
    # RdRD is only supported on CVA5
]

# Integration tests that are run for EVERY available core
command_templates = [
    'ISAXES="AUTOINC" SIM_EN="y" TB_PATH="../custom_tbs/dummy.S" TB_EXPECTED_PATH="../custom_tbs/dummy_expected.txt" make ci',
    'ISAXES="BRIMM" SIM_EN="y" TB_PATH="../custom_tbs/dummy.S" TB_EXPECTED_PATH="../custom_tbs/dummy_expected.txt" make ci',
    'ISAXES="DOTPROD" SIM_EN="y" TB_PATH="../custom_tbs/dummy.S" TB_EXPECTED_PATH="../custom_tbs/dummy_expected.txt" make ci',
    'ISAXES="INDIRECTJMP" SIM_EN="y" TB_PATH="../custom_tbs/dummy.S" TB_EXPECTED_PATH="../custom_tbs/dummy_expected.txt" make ci',
    'ISAXES="SBOX" SIM_EN="y" TB_PATH="../custom_tbs/sbox.cpp" TB_EXPECTED_PATH="../custom_tbs/sbox_expected.txt" make ci',
    'ISAXES="SPARKLE" SIM_EN="y" TB_PATH="../custom_tbs/dummy.S" TB_EXPECTED_PATH="../custom_tbs/dummy_expected.txt" make ci',
    'ISAXES="SQRT" SIM_EN="y" TB_PATH="../custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="../custom_tbs/sqrt_expected.txt" make ci',
    'ISAXES="SQRT_STALL" SIM_EN="y" TB_PATH="../custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="../custom_tbs/sqrt_expected.txt" make ci',
    'ISAXES="ZOL" SIM_EN="y" TB_PATH="../custom_tbs/dummy.S" TB_EXPECTED_PATH="../custom_tbs/dummy_expected.txt" make ci',
    'ISAXES="AUTOINC,BRIMM,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT" SIM_EN="y" TB_PATH="../custom_tbs/sbox.cpp" TB_EXPECTED_PATH="../custom_tbs/sbox_expected.txt" make ci',
    'ISAXES="AUTOINC,BRIMM,DOTPROD,INDIRECTJMP,SBOX,SPARKLE,SQRT" SIM_EN="y" TB_PATH="../custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="../custom_tbs/sqrt_expected.txt" make ci',
    # MLIR entrypoint tests
    # complex ISAX
    'LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/complex/complex.mlir" LN_CELL_LIBRARY="deps/longnail/sim/complex/library.yaml" SIM_EN="y" TB_PATH="../custom_tbs/complex.S" TB_EXPECTED_PATH="../custom_tbs/complex_expected.txt" USE_OL2_MODEL="y" CLOCK_TIME="150.0" make ci',
    # vector ISAX
    'LN_SCHED_ALGO_MS="y" LN_SCHED_ALGO_PA="y" MLIR_ENTRY_POINT_PATH="deps/longnail/sim/vector/vector.mlir" LN_CELL_LIBRARY="deps/longnail/sim/vector/library.yaml" SIM_EN="y" TB_PATH="../custom_tbs/vector.S" TB_EXPECTED_PATH="../custom_tbs/vector_expected.txt" USE_OL2_MODEL="y" make ci',
]

cores = [
    "CVA5",
    "PICORV32",
    "PICCOLO",
    "ORCA",
    "VEX_4S",
    "VEX_5S",
]

for core in cores:
    for cmd in command_templates:
        commands.append(f'CORE="{core}" {cmd}')

integration_test_working_dir = os.path.abspath("test_results")
if os.path.exists(integration_test_working_dir):
    shutil.rmtree(integration_test_working_dir)
logs_dir = os.path.join(integration_test_working_dir, "logs")
os.makedirs(logs_dir)


def run_test(command, id):
    kconfig_out_file = os.path.join(
        integration_test_working_dir, f".config_test_{id:03}")
    output_folder = os.path.join(
        integration_test_working_dir, f"output_test_{id:03}")
    # create the output folder
    os.makedirs(output_folder)

    cmd_env_prefix = f"CONFIG_PATH={kconfig_out_file} OUTPUT_PATH={output_folder} "
    output_file = os.path.join(logs_dir, f"integration_test_{id:03}.log.gz")
    with gzip.open(output_file, "w") as file:
        exit_code = None
        file.write(f"Running command: {cmd_env_prefix}{command}\n".encode("utf-8"))
        file.write(("="*80 + "\n\n\n").encode("utf-8"))
        with subprocess.Popen(
                cmd_env_prefix + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            shutil.copyfileobj(process.stdout, file)
            process.wait()
            exit_code = process.returncode
        return exit_code, command, id


def run_tests(jobs):
    if len(jobs) == 0:
        return []

    # Use the maximum number of threads available on the system
    # num_threads = min(len(jobs), os.cpu_count())
    # TODO FIXME: awesome_llvm can not yet be used in parallel, until then we can only use one thread!
    num_threads = 1

    results = []
    # Create a ThreadPoolExecutor with the desired number of threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Submit tasks to the executor and store the Future objects
        futures = [executor.submit(run_test, job, id)
                   for id, job in enumerate(jobs)]

        # Wait for all jobs to complete
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
    return results


results = run_tests(commands)
failed = 0
for exit_code, cmd, id in results:
    if exit_code != 0:
        failed += 1
        print(f"Test {id} failed with exit code {exit_code}, cmd: '{cmd}'")
print(f"Summary: {len(commands) - failed}/{len(commands)} integration tests succeeded.")

# Exit with a non-zero code if any command failed
if failed != 0:
    exit(1)
