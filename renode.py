import os
from tools.isax_yaml_tools import *

def gen_renode_confs(isax_name, sim_dir, yaml_path, tb_path, march, IMEM_BASE, DMEM_BASE, DMEM_SIZE, CTRL_BASE):
    isax_patterns = extract_encodings(yaml_path)
    renode_dir = os.path.abspath(os.path.join(sim_dir, "renode"))
    os.makedirs(renode_dir, exist_ok=True)
    core_desc = os.path.join(renode_dir, "riscv.repl")
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
    script: ""

uart: UART.MiV_CoreUART @ sysbus 0x{int(CTRL_BASE, 16) + 8:X}
    clockFrequency: 50000000
""")

    custom_instruction_handlers = [ f'sysbus.cpu InstallCustomInstructionHandlerFromFile "{mask.replace('-', 'x')}" "{renode_dir}/{isax_name}.py" # Custom instruction: {i}' for i, mask in isax_patterns.items() ]
    newline = "\n"

    script = os.path.join(renode_dir, "run.resc")
    with open(script, 'w') as f:
        f.write(f"""
mach create
machine LoadPlatformDescription @./riscv.repl
# sysbus LogAllPeripheralsAccess true

# Custom instruction handlers
{newline.join(custom_instruction_handlers)}

# Logging
sysbus.cpu LogFunctionNames true
sysbus.cpu CreateExecutionTracing "cputracer" @{renode_dir}/trace.log Disassembly

sysbus LoadELF @{os.path.relpath(tb_path, renode_dir)}
showAnalyzer sysbus.uart

machine StartGdbServer 3333

sysbus SetHookBeforePeripheralWrite stop_sim "machine.PauseAndRequestEmulationPause()"
""")

    script = os.path.join(renode_dir, "run.sh")
    with open(script, 'w') as f:
        f.write(f"""#!/bin/sh
renode --console --disable-gui run.resc
""")
    # Make the script executable
    os.chmod(script, 0o755)
    return renode_dir
