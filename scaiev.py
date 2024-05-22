#!/usr/bin/env python3
import os
import stat
import error
import run_cmd
import shutil

def run_scaiev(core, isax_desc):
    # create build and tool directory
    if not os.path.isdir("build"):
        os.mkdir("build")
    if not os.path.isdir("build/core"):
        os.mkdir("build/core")
    if not os.path.isdir(f"build/core/{core}"):
        os.mkdir(f"build/core/{core}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    run_cmd.run("deps/scaie-v/EclipseWork/SCAIEV", f"java -jar ./target/SCAIEV-0.0.1-SNAPSHOT-jar-with-dependencies.jar -c {core} -i {script_dir}/{isax_desc} -o {script_dir}/build/core", "SCAIEV failed")


def build_scaiev():
    # build scaiev
    if not os.path.isfile("./deps/scaie-v/EclipseWork/SCAIEV/target/SCAIEV-0.0.1-SNAPSHOT.jar"):
        print("Building SCAIE-V...")
        run_cmd.run("deps/scaie-v/EclipseWork/SCAIEV", "mvn package", "Could not build SCAIE-V")


# Selects the core
def select_core(kconfig_core):
    if len(kconfig_core) != 1:
        error.exit_error(f"No or more than one core selected in Kconfig: {kconfig_core}")
    kconfig_core = kconfig_core[0]

    if (kconfig_core == "CONFIG_CORE_PICORV32"):
        return "PicoRV32"
    elif (kconfig_core == "CONFIG_CORE_ORCA"):
        return "ORCA"
    elif (kconfig_core == "CONFIG_CORE_PICCOLO"):
        return "Piccolo"
    elif (kconfig_core == "CONFIG_CORE_CVA5"):
        return "CVA5"
    elif (kconfig_core == "CONFIG_CORE_VEX_4S"):
        return "VexRiscv_4s"
    elif (kconfig_core == "CONFIG_CORE_VEX_5S"):
        return "VexRiscv_5s"
    else:
        error.exit_error("No datasheet for selected core found!")
