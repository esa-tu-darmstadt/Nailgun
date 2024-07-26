#!/usr/bin/env python3
import subprocess

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
    'ISAXES="ZOL" SIM_EN="y" TB_PATH="../custom_tbs/sqrt.cpp" TB_EXPECTED_PATH="../custom_tbs/sqrt_expected.txt" make ci',
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

# File to collect the outputs
output_file = "integration_test_outputs.txt"

# Run each command and store its exit code
failed = 0
with open(output_file, "w") as file:
    for command in commands:
        exit_code = None
        print(f"Command: '{command}' ", end="", flush=True)
        file.write(f"Running command: {command}\n")
        file.write("="*80 + "\n")
        try:
            completed_process = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
            exit_code = completed_process.returncode
            file.write("STDOUT:\n")
            file.write(completed_process.stdout + "\n")
            file.write("="*80 + "\n")
            file.write("STDERR:\n")
            file.write(completed_process.stderr + "\n")
        except subprocess.CalledProcessError as e:
            exit_code = e.returncode
            file.write(e.stdout + "\n")
            file.write(e.stderr + "\n")
        file.write("="*80 + "\n\n\n\n\n\n")

        if exit_code == 0:
            print(f"succeeded.", flush=True)
        else:
            print(f"failed with exit code {exit_code}.", flush=True)
            failed += 1

print(f"Summary: {len(commands) - failed}/{len(commands)} integration tests succeeded.")

# Exit with a non-zero code if any command failed
if failed != 0:
    exit(1)
