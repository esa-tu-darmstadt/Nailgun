#!/usr/bin/env python3
import os
import kconfiglib
import functools
import re

import error
import kconfig
import treenail
import longnail
import scaiev
import simulation
import merge_core_descs


# generate mapping from ISAX config name to isax description file
def gen_isax_map():
    isax_map = {}
    for root, _, files in os.walk(".", topdown=False):
        for name in files:
            if name == "paths.csv":
                csvpath = os.path.join(root, name)
                try:
                    csvfile = open(csvpath)
                    current_map = { line.split(";")[0]:line.split(";")[1].replace("\n","") for line in csvfile}
                    isax_map = {**isax_map, **current_map}
                except:
                    error.exit_error(f"could not parse ISAX path.csv file found in: {root}", error.INTERNAL_ERROR)
    return isax_map

def create_output_folder(base_path):
    # Start with the base path
    path = base_path
    suffix = 1

    # Check if the directory exists, and if so, add a suffix
    while os.path.exists(path):
        path = f"{base_path}_{suffix}"
        suffix += 1

    # Create the directory
    os.makedirs(path)
    return path

if __name__ == "__main__":
    # Read in Kconfig & .config file
    kconf = kconfiglib.Kconfig("Kconfig")
    config_path = os.getenv("CONFIG_PATH")
    if config_path:
        kconf.load_config(config_path)
    else:
        kconf.load_config(".config")

    # get list of enabled ISAXes
    enabled_isaxes = kconfig.extract_kconfig_enabled(kconfig.extract_enabled_isax_from_config(kconf.syms))

    # get mapping from config option to mlir files
    isax_file_mapping = gen_isax_map()

    # map enabled isaxes to LN mlir input files
    isax_input_files = None
    try:
        isax_input_files = list(map(lambda x: isax_file_mapping[x], enabled_isaxes))
    except KeyError as ke:
        error.exit_error(f"Could not find .core_desc file for {str(ke)}. Check your paths.csv.", error.INTERNAL_ERROR)

    core_name = kconfig.extract_kconfig_enabled(kconfig.extract_core_from_config(kconf.syms))
    scaiev_core_name = scaiev.select_core(core_name)

    # print enabled ISAXes
    isax_name = None
    mlir_paths = None
    if kconf.syms["MLIR_ENTRY_POINT"].str_value != "y":
        print(f"Building {scaiev_core_name} with ISAXes:")
        for isax,mlir in zip(enabled_isaxes, isax_input_files):
            print(f" - {isax[len('ISAX_'):-len('_EN')]} (associated description: {mlir})")

        if len(enabled_isaxes) == 0:
            error.exit_error("No ISAXes were selected, nothing to do!", error.USER_ERROR)
        # TN coreDSL to mlir
        treenail.build_treenail()
        mlir_paths = treenail.run_treenail_batch(enabled_isaxes, isax_input_files)
    else:
        # use the MLIR entry point path
        path = kconf.syms["MLIR_ENTRY_POINT_PATH"].str_value
        if not os.path.exists(path):
            error.exit_error(f"Could not find mlir file '{mlir_paths[0]}'. Please check your MLIR entry point path settings!", error.USER_ERROR)
        mlir_paths = [ os.path.abspath(path) ]

    # Package all results in an output folder
    out_dir = os.getenv("OUTPUT_PATH")
    if out_dir:
        if not os.path.exists(out_dir):
            error.exit_error(f"Explicitly specified output path {out_dir} does not exist!", error.USER_ERROR)
        out_dir = os.path.abspath(out_dir)
    else:
        out_dir = create_output_folder("output")

    # LN mlir to .v
    longnail.build_longnail()
    datasheet = longnail.select_core_datasheet(core_name)
    mlir_path = longnail.run_longnail(mlir_paths, datasheet, kconf.syms, out_dir)

    # No coredsl files were merged, extract the isax name directly from the used mlir file
    if not isax_name:
        # Read the entire file into one string variable
        with open(mlir_path, 'r') as file:
            mlir_text = file.read()
        # Define the regex pattern
        pattern = r'module\s+@(\w+)\s*\{'
        # Search for the pattern
        match = re.search(pattern, mlir_text)
        # Extract the module name if found
        if match:
            isax_name = match.group(1)
        else:
            error.exit_error("Could not extract the module's ISAX name", error.INTERNAL_ERROR)

    # SCAIE-V integrate into core
    scaiev.build_scaiev()
    scaiev.run_scaiev(scaiev_core_name, longnail.provide_isax_yaml(out_dir), out_dir)

    # Optionally run the simulation
    simulation.run_simulation(out_dir, scaiev_core_name, kconf.syms, isax_name, mlir_path)
