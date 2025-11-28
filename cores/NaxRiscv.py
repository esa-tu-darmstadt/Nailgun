import os

import error
import run_cmd
from scaiev import CoreSupport

class NaxSupport(CoreSupport):
    def __init__(self):
        self.IMEM_BASE =  "80000000"
        self.IMEM_SIZE =  "100000"
        self.DMEM_BASE =  "80100000"
        self.DMEM_SIZE =  "100000"
        self.CTRL_BASE =  "80200000"
        self.CTRL_SIZE =  "100000"
        self.CLINT_BASE = "40000000"
        self.CLINT_SIZE = "010000"

    def copy_blacklist(self) -> list[str]:
        return [
            # NaxRiscv
            # "deps/scaie-v/CoresSrc/NaxRiscv/.git", # actually necessary, lol
        ]
    def has_isax_support(self) -> bool:
        return False
    def run_extra_build_steps(self, target_dir, kconf_syms) -> None:
        spinal_gen_args = kconf_syms['SPINAL_GEN_ARGS'].str_value if 'SPINAL_GEN_ARGS' in kconf_syms else ""

        # Patch the build system and config of NaxRiscv. Tested against commit 1c50e84d9a6f7ea93d7153f12906c25552267b9d
        patch_file = os.path.abspath("patches/Nax5.patch")
        run_cmd.run(target_dir, f"patch -p1 < {patch_file}", "Could not patch the NaxRiscv sources", error.SCAIEV_BASE + 4, False)
        # Build NaxRiscv
        # Custom available option:  --with-hw-ctx-switch --with-hw-scheduling --baseline-with-switch-tracing --with-dirty-bits
        run_cmd.run(target_dir, f'sbt "runMain naxriscv.platform.asic.NaxAsicGen {spinal_gen_args} --memory-region=0x{self.CLINT_BASE},0x{self.CLINT_SIZE},io,p --memory-region=0x{self.CTRL_BASE},0x{self.CTRL_SIZE},io,p --memory-region=0x{self.IMEM_BASE},0x{self.IMEM_SIZE},xc,m --memory-region=0x{self.DMEM_BASE},0x{self.DMEM_SIZE},rwc,m --reset-vector=0x{self.IMEM_BASE}"', "Could not generate nax.v", error.SCAIEV_BASE + 5, True, 100)

        # command_injection = kconf_syms['COMMAND_INJECTION'].str_value if 'COMMAND_INJECTION' in kconf_syms else ""
        # if len(command_injection) > 0:
        #     run_cmd.run(target_dir, command_injection, "Could not execute injected command", error.SCAIEV_BASE + 6, True, 100)

    def get_srcs_folder_name(self) -> str:
        return "NaxRiscv"
    def get_maketop(self) -> str:
        return "Nax_maketop.py"
    def get_compiler_extensions(self) -> tuple[str, str, int]:
        return "ima_zicsr", "ilp32", 32
    # -> tb srcs, core srcs, tb top module, core top module, include dirs, defines, extra sim makefile args
    def get_core_srcs(self, scal_sources, core_dir) -> tuple[list[str], list[str], str, str, list[str], list[str], dict[str, str]]:
        defines = [
            "FORMAL"
        ]

        return ["Nax_tb_wrapper.sv"], ["nax.v", "Nax_top.sv"] + scal_sources, "nax_wrapper", "top", [], defines, {}
        # return ["Nax_tb_wrapper.sv"], ["nax.v", "src/main/verilog/xilinx/RamXilinx.v", "Nax_top.sv"] + scal_sources, "nax_wrapper", "top", [], defines, {}
        # return ["Nax_tb_wrapper.sv"], ["nax.v", "src/main/verilog/xilinx/RamXilinx.v", "Nax_top.sv", "mkRTOSUnitSynth.v", "SizedFIFO.v", "FIFO2.v"] + scal_sources, "nax_wrapper", "top", [], defines, {}
    def get_tb_env_vars(self) -> list[str]:
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=3",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            "BUSSI2_TYPE=AXI4",
            "BUSSI2_SIGNAME=m_axi_ctrl",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            f"IMEM_BASE={self.IMEM_BASE}",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            #"EXCEPTION_BASE=00000020", # TODO honestly, I DONT KNOW
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            f"DMEM_BASE={self.DMEM_BASE}",
            # The physical size of the data memory.
            f"DMEM_SIZE={self.DMEM_SIZE}",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=2",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            f"CTRL_BASE={self.CTRL_BASE}",
            # Bus SI index for CLINT.
            "CLINT_BUSIDX=2",
            "ALLOW_SPECULATIVE_READS", # NaxRiscv sometimes wants to read at 0x0 which is not mapped.... NOTE that this might hide segmentation faults...
        ]

    def get_linker_file(self) -> str:
        return self._get_linker_file("NaxRiscv")
    def get_specific_startup_file(self) -> str:
        return self._get_specific_startup_file("NaxRiscv")
    def get_longnail_datasheet_name(self) -> str:
        return None

def get_supported_cores():
    return [
        ("CORE_NAX", "NaxRiscv", NaxSupport()),
    ]
