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

# Dictionary to store the exit codes of each command
results = {}

# File to collect the outputs
output_file = "integration_test_outputs.txt"

# Run each command and store its exit code
with open(output_file, "w") as file:
    for command in commands:
        file.write(f"Running command: {command}\n")
        file.write("="*80 + "\n")
        try:
            completed_process = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
            results[command] = completed_process.returncode
            file.write("STDOUT:\n")
            file.write(completed_process.stdout + "\n")
            file.write("="*80 + "\n")
            file.write("STDERR:\n")
            file.write(completed_process.stderr + "\n")
        except subprocess.CalledProcessError as e:
            results[command] = e.returncode
            file.write(e.stdout + "\n")
            file.write(e.stderr + "\n")
        file.write("="*80 + "\n\n\n\n\n\n")

# Print the summary
print("Summary of command execution:")
all_success = True
for command, exit_code in results.items():
    if exit_code == 0:
        print(f"Command: '{command}' succeeded.")
    else:
        print(f"Command: '{command}' failed with exit code {exit_code}.")
        all_success = False

# Exit with a non-zero code if any command failed
if not all_success:
    exit(1)
