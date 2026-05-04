import os

from scaiev import CoreSupport, CoreExtensions

import yaml

class CV32E40_Support(CoreSupport):
    def copy_blacklist(self) -> list[str]:
        return [
            # CV32E40P
            "deps/scaie-v/CoresSrc/CV32E40P/.git", # unnecessary
            # CV32E40X
            "deps/scaie-v/CoresSrc/CV32E40X/.git", # unnecessary
        ]
    def run_extra_build_steps(self, target_dir, kconf_syms) -> None:
        pass
    def get_extensions(self) -> CoreExtensions:
        return CoreExtensions(['I','M','Zicsr'], "ilp32", 32)

    def get_tb_env_vars(self, kconf_syms) -> list[str]:
        return [
            # Number of Bus slave interfaces the simulator should instantiate.
            "NUM_BUSSI=2",
            # Types and port names for each Bus SI.
            "BUSSI0_TYPE=AXI4",
            "BUSSI0_SIGNAME=m_axi_instr",
            "BUSSI1_TYPE=AXI4",
            "BUSSI1_SIGNAME=m_axi_data",
            # Bus SI index for IMEM.
            "IMEM_BUSIDX=0",
            # The base address of the instruction memory on the bus.
            "IMEM_BASE=80000000",
            # The address of the exception handler on the instruction bus, for error detection (optional).
            "EXCEPTION_BASE=00000020",
            # Bus SI index for DMEM.
            "DMEM_BUSIDX=1",
            # The base address of the data memory on the bus.
            "DMEM_BASE=80100000",
            # The physical size of the data memory.
            "DMEM_SIZE=00100000",
            # Bus SI index for CTRL.
            "CTRL_BUSIDX=1",
            # The base address of the MMIO control block on the bus (for completion IRQ).
            "CTRL_BASE=80200000",
        ]

    def get_linker_file(self) -> str:
        return self._get_linker_file("CV32E40X")
    def get_specific_startup_file(self) -> str:
        return self._get_specific_startup_file("CV32E40X")

class CV32E40XSupport(CV32E40_Support):
    def has_isax_support(self) -> bool:
        return True
    def get_longnail_datasheet_name(self) -> str:
        return "CV32E40X.yaml"
    def get_srcs_folder_name(self) -> str:
        return "CV32E40X"
    def get_maketop(self) -> str:
        return "cv32e40x_maketop.py"

    # -> tb srcs, core srcs, tb top module, core top module, include dirs, defines, extra sim makefile args
    def get_core_srcs(self, scal_sources, core_dir) -> tuple[list[str], list[str], str, str, list[str], list[str], dict[str, str]]:
        with open(os.path.join(core_dir, "cv32e40x_manifest.flist")) as prj_flist:
            prj_flist_lines = [line.strip().replace('${DESIGN_RTL_DIR}', "rtl") for line in prj_flist.readlines() if len(line.strip()) > 0 and not line.startswith("//")]
            include_dirs = [line[8:] for line in prj_flist_lines if line.startswith("+incdir+")]
            core_srcs = [line for line in prj_flist_lines if not line.startswith("+")]
        defines = [
            "COREV_ASSERT_OFF"
        ]
        extra_makefile_args = {
            "verilator": """
# Verilator throws lots of warnings on the core. Ignoring some of them.
EXTRA_ARGS+=-Wno-WIDTHEXPAND -Wno-LITENDIAN -Wno-WIDTHTRUNC -Wno-BLKANDNBLK
"""
        }
        return ["cv32e40x_tb_wrapper.v", "obi_axi_adapter.sv"], core_srcs + ["cv32e40x_top.sv"] + scal_sources, "testbench", "top", include_dirs, defines, extra_makefile_args

class CV32E40PSupport(CV32E40_Support):
    def has_isax_support(self) -> bool:
        return False
    def get_longnail_datasheet_name(self) -> str:
        return None
    def get_srcs_folder_name(self) -> str:
        return "CV32E40P"
    def get_maketop(self) -> str:
        return "cv32e40p_maketop.py"

    # -> tb srcs, core srcs, tb top module, core top module, include dirs, defines, extra sim makefile args
    def get_core_srcs(self, scal_sources, core_dir) -> tuple[list[str], list[str], str, str, list[str], list[str], dict[str, str]]:
        with open(os.path.join(core_dir, "src_files.yml")) as prj_yaml_desc:
            prj_desc = yaml.safe_load(prj_yaml_desc)
        core_srcs = prj_desc["cv32e40p"]["files"] + prj_desc["cv32e40p_regfile_verilator"]["files"] + ["bhv/cv32e40p_sim_clock_gate.sv"]
        defines = [
            # "COREV_ASSERT_OFF"
        ]
        include_dirs = prj_desc["cv32e40p"]["incdirs"]
        extra_makefile_args = {
            "verilator": """
# Verilator throws lots of warnings on the core. Ignoring some of them.
EXTRA_ARGS+=-Wno-WIDTHEXPAND -Wno-LITENDIAN -Wno-WIDTHTRUNC -Wno-BLKANDNBLK
"""
        }
        return ["cv32e40x_tb_wrapper.v", "obi_axi_adapter.sv"], core_srcs + ["cv32e40p_top.sv"] + scal_sources, "testbench", "top", include_dirs, defines, extra_makefile_args

def get_supported_cores():
    return [
        ("CORE_CV32E40P", "CV32E40P", CV32E40PSupport()),
        ("CORE_CV32E40X", "CV32E40X", CV32E40XSupport()),
    ]
