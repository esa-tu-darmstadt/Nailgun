import os
from tools.isax_yaml_tools import *

def gen_renode_confs(isax_model_filename, sim_dir, yaml_path, tb_paths, tb_expected_paths, march, IMEM_BASE, DMEM_BASE, DMEM_SIZE, CTRL_BASE):
    isax_patterns = extract_encodings(yaml_path)
    renode_dir = os.path.abspath(os.path.join(sim_dir, "renode"))
    os.makedirs(renode_dir, exist_ok=True)
    core_desc = os.path.join(renode_dir, "riscv.repl")
    tb_selection_addr = int(CTRL_BASE, 16) + 0x20
    resdata_addr = int(CTRL_BASE, 16) + 0x20000

    script = os.path.join(renode_dir, "check_expected.py")
    with open(script, 'w') as f:
        f.write(f"""import struct

machine = self.GetMachine()

tb_selection_addr = 0x{tb_selection_addr:X}
tb_selection = machine.SystemBus.ReadWord(tb_selection_addr)
tb_expected_paths = {tb_expected_paths}

expected_file = tb_expected_paths[tb_selection]
resdata_addr = 0x{resdata_addr:X}


expected_data = bytearray()
with open(expected_file, "r") as f:
    for line in f:
        line_lstrip = line.lstrip()
        if len(line_lstrip) != 0 and line_lstrip[0] != '#':
            val = int(line_lstrip, 16)
            # pack as 4-byte little-endian
            expected_data += bytearray(struct.pack('<I', val))


# Initialize mismatch flag
mismatch_found = False

# Compare byte by byte
for i, expected_byte in enumerate(expected_data):
    addr = resdata_addr + i
    actual_byte = machine.SystemBus.ReadByte(addr)
    # actual_byte = self.ReadByte(addr)
    if actual_byte != expected_byte:
        machine.ErrorLog("Mismatch at 0x%08X: expected 0x%02X, got 0x%02X" % (addr, expected_byte, actual_byte))
        mismatch_found = True

# Raise error if any mismatch was found
if mismatch_found:
    raise RuntimeError("Memory content mismatch detected!")
else:
    machine.InfoLog("All bytes match expected data.")

machine.PauseAndRequestEmulationPause()
""")

    with open(core_desc, 'w') as f:
        f.write(f"""
cpu: CPU.RiscV32 @ sysbus
    cpuType: "{march}"
    timeProvider: clint

imem: Memory.MappedMemory @ sysbus 0x{IMEM_BASE}
    size: 0x{DMEM_SIZE}

dmem: Memory.MappedMemory @ sysbus 0x{DMEM_BASE}
    size: 0x{DMEM_SIZE}

// Power/Reset/Clock/Interrupt
clint: IRQControllers.MiV_CoreLevelInterruptor  @ sysbus 0x40000000
    frequency: 100000000
    prescaler: 100
    [0, 1] -> cpu@[3, 7]

stop_sim: Python.PythonPeripheral @ sysbus 0x{CTRL_BASE}
    size: 0x08
    initable: false
    filename: "{script}"

uart: UART.MiV_CoreUART @ sysbus 0x{int(CTRL_BASE, 16) + 8:X}
    clockFrequency: 50000000

tb_selection: Python.PythonPeripheral @ sysbus 0x{tb_selection_addr:X}
    size: 0x04
    initable: true
    filename: "scripts/pydev/repeater.py"

resdata: Memory.MappedMemory @ sysbus 0x{resdata_addr:X}
    size: 0x0E0000
""")

    custom_instruction_handlers = [ f'sysbus.cpu InstallCustomInstructionHandlerFromFile "{mask.replace('-', 'x')}" "{renode_dir}/{isax_model_filename}" # Custom instruction: {i}' for i, mask in isax_patterns.items() ]
    load_elfs = [
        f"""{"# " if i != 0 else ""}sysbus LoadELF @{os.path.abspath(tb_path)}
{"# " if i != 0 else ""}sysbus WriteWord 0x{tb_selection_addr:X} {i}
""" for i, tb_path in enumerate(tb_paths)
    ]
    newline = "\n"

    script = os.path.join(renode_dir, "run.resc")
    with open(script, 'w') as f:
        f.write(f"""
mach create
machine LoadPlatformDescription @{core_desc}
# sysbus LogAllPeripheralsAccess true

# Custom instruction handlers
{newline.join(custom_instruction_handlers)}

# Logging
sysbus.cpu LogFunctionNames true
# sysbus.cpu CreateExecutionTracing "cputracer" @{renode_dir}/trace.log Disassembly
# cputracer TrackMemoryAccesses

{newline.join(load_elfs)}
showAnalyzer sysbus.uart

# Do not auto start on gdb attach
# machine StartGdbServer 3333 false

# Note: this has to be disabled in order for ./run_robots.sh to work
# start
""")

    script = os.path.join(renode_dir, "run.sh")
    with open(script, 'w') as f:
        f.write(f"""#!/bin/sh
renode --console --disable-gui run.resc
""")
    # Make the script executable
    os.chmod(script, 0o755)

    robot_dir = os.path.join(renode_dir, "robots")
    os.makedirs(robot_dir)
    global_timeout = 600
    test_timeout = 60
    for idx, tb_path in enumerate(tb_paths):
        script = os.path.join(robot_dir, f"run_tb_{idx}.robot")
        with open(script, 'w') as f:
            f.write(f"""*** Variables ***
${{SCRIPT}}         ${{CURDIR}}/../run.resc

*** Test Cases ***
RUN TB {idx}
    [Timeout]                  {test_timeout} seconds
    Execute Script             ${{SCRIPT}}
    Execute Command            sysbus LoadELF @${{CURDIR}}/{os.path.relpath(tb_path, robot_dir)}
    Execute Command            sysbus WriteWord 0x{tb_selection_addr:X} {idx}
    Create Log Tester          {test_timeout}
    Start Emulation
    Wait For Log Entry         Machine paused
""")

    script = os.path.join(renode_dir, "run_robots.sh")
    with open(script, 'w') as f:
        f.write(f"""#!/bin/sh
cd robots
renode-test --keep-renode-output  --save-logs always --test-timeout {global_timeout} -j`nproc` {" ".join([f"run_tb_{i}.robot" for i in range(len(tb_paths))])}
""")
    # Make the script executable
    os.chmod(script, 0o755)


    return renode_dir
