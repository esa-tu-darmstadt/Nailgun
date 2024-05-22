#!/usr/bin/env python3
import os
import stat
import error
import run_cmd
import shutil
import functools
import error


def run_longnail(isax_tags, datasheet, longnail_configs):
    # create build and tool directory
    if not os.path.isdir("build"):
        os.mkdir("build")
    if not os.path.isdir("build/verilog"):
        os.mkdir("build/verilog")

    # gather src files
    print(f" - Invoking Longnail HLS")
    isax_tags = list(map(lambda a: f"build/mlir/{a}.mlir", isax_tags))
    mlir_str = functools.reduce(lambda a, b: a+" "+b, isax_tags)

    # check inputs
    if (longnail_configs['CONFIG_LN_CELL_LIBRARY'] == 0):
        error.exit_error("No cell library provided to longnail")

    # collect flags to LN
    longnail_flags = [
        "-lower-coredsl-to-lil",
        #TODO make schedulingTimeout, schedRefineTimeout, clockTime, schedulingAlgo, useCommercialSolver, opTyLibrary configurable
        f"-schedule-lil=\"datasheet={datasheet} library={longnail_configs['CONFIG_LN_CELL_LIBRARY']}\"",
        #TODO implement another step to select the solution
        "-lower-lil-to-hw=forceUseMinIISolution=true",
        "-simplify-structure", "-cse", "-canonicalize",
        "-lower-seq-to-sv", "-hw-cleanup", "-prettify-verilog",
        "-export-split-verilog=dir-name=build/verilog", "-o /dev/null"
    ]
    longnail_flags_str = functools.reduce(lambda a, b: a+" "+b, longnail_flags)

    # execute LN
    run_cmd.run(".", f"./deps/longnail/build/bin/longnail-opt {longnail_flags_str} {isax_tags[0]}", f"Longnail failed")


def build_longnail():
    # create build and tool directory
    if not os.path.isdir("build"):
        os.mkdir("build")

    # check that gradlew exists
    if not os.path.isfile("deps/longnail/circt/utils/get-or-tools.sh"):
        error.exit_error("Longnail or its submodules are not cloned. Check out submodules in this repo!")

    # build longnail
    if not os.path.isfile("deps/longnail/build/bin/longnail-opt"):
        print("Building Longnail...")
        run_cmd.run("deps/longnail", "./circt/utils/get-or-tools.sh", "Gathering or-tools for CIRCT failed")
        run_cmd.run("deps/longnail", "chmod +x ./circt/utils/get-iverilog.sh && ./circt/utils/get-iverilog.sh", "Building iVerilog failed")
        run_cmd.run("deps/longnail", "sed -i '/^VERILATOR_VER=/c\VERILATOR_VER=5.012' ./circt/utils/get-verilator.sh && chmod +x ./circt/utils/get-verilator.sh && ./circt/utils/get-verilator.sh", "Building dependencies failed")
        run_cmd.run("deps/longnail", "./build_circt.sh", "Building CIRCT failed")
        run_cmd.run("deps/longnail", "./build_longnail.sh", "Longnail build failed")


# Selects the core datasheet file based on selected core
# TODO: if we would make the files in LN all lowercase, we could simply generate the file name
def select_core_datasheet(kconfig_core):
    if len(kconfig_core) != 1:
        error.exit_error(
            f"No or more than one core selected in Kconfig: {kconfig_core}")
    kconfig_core = kconfig_core[0]

    if (kconfig_core == "CONFIG_CORE_PICORV32"):
        return "deps/longnail/datasheets/PicoRV32.yaml"
    elif (kconfig_core == "CONFIG_CORE_ORCA"):
        return "deps/longnail/datasheets/ORCA.yaml"
    elif (kconfig_core == "CONFIG_CORE_PICCOLO"):
        return "deps/longnail/datasheets/Piccolo.yaml"
    elif (kconfig_core == "CONFIG_CORE_VEX_4S"):
        return "deps/longnail/datasheets/VexRiscv_4s.yaml"
    elif (kconfig_core == "CONFIG_CORE_VEX_5S"):
        return "deps/longnail/datasheets/VexRiscv_5s.yaml"
    else:
        error.exit_error("No datasheet for selected core found!")


def provide_isax_yaml():
    filelist = open("build/verilog/filelist.f")
    yamls = [f[:-1] for f in filelist if f[-6:-1] == ".yaml"]
    return "build/verilog/"+yamls[0]
