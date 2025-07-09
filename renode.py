import os
from tools.isax_yaml_tools import *

def gen_renode_confs(sim_dir, yaml_path, tb_path, march, IMEM_BASE, DMEM_BASE, DMEM_SIZE):
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

uart: UART.MiV_CoreUART @ sysbus 0x70001000
    clockFrequency: 50000000
""")

    custom_instruction_handlers = [ f'# sysbus.cpu InstallCustomInstructionHandlerFromFile "{mask.replace('-', 'x')}" "{renode_dir}/{i}.py"' for i, mask in isax_patterns.items() ]
    newline = "\n"

    script = os.path.join(renode_dir, "run.resc")
    with open(script, 'w') as f:
        f.write(f"""
mach create
machine LoadPlatformDescription @./riscv.repl
sysbus LogAllPeripheralsAccess true

# Custom instruction handlers
{newline.join(custom_instruction_handlers)}

# Logging
sysbus.cpu LogFunctionNames true
sysbus.cpu CreateExecutionTracing "cputracer" @{renode_dir}/trace.log Disassembly

sysbus LoadELF @{os.path.relpath(tb_path, renode_dir)}
# showAnalyzer sysbus.uart

machine StartGdbServer 3333
""")
