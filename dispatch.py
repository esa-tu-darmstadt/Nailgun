#!/usr/bin/env python3
import os
import error
import kconfig
import treenail
import longnail
import scaiev

# generate mapping from ISAX config name to isax description file
def gen_isax_map():
    isax_map = {}
    for root, dirs, files in os.walk(".", topdown=False):
        for name in files:
            if name == "paths.csv":
                csvpath = os.path.join(root, name)
                try:
                    csvfile = open(csvpath)
                    current_map = { line.split(";")[0]:line.split(";")[1].replace("\n","") for line in csvfile}
                    isax_map = {**isax_map, **current_map}
                except:
                    error.exit_error(f"could not parse ISAX path.csv file found in: {root}")
    return isax_map


if __name__ == "__main__":
    # read kconfig file
    kconfig_dict = kconfig.read_kconfig()

    # get list of enabled ISAXes
    enabled_isaxes = kconfig.extract_kconfig_enabled(kconfig.extract_enabled_isax_from_config(kconfig_dict))

    # get mapping from config option to mlir files
    isax_file_mapping = gen_isax_map()

    # map enabled isaxes to LN mlir input files
    isax_input_files = None
    try:
        isax_input_files = list(map(lambda x: isax_file_mapping[x], enabled_isaxes))
    except KeyError as ke:
        error.exit_error(f"Could not find .mlir file for {str(ke)}. Check your paths.csv.")

    # print enabled ISAXes
    print("Building <core> with ISAXes:")
    for isax,mlir in zip(enabled_isaxes, isax_input_files):
        print(f" - {isax[12:-3]} (associated description: {mlir})")

    # TN coreDSL to mlir
    treenail.build_treenail()
    treenail.run_treenail_batch(enabled_isaxes, isax_input_files)

    # LN mlir to .v
    longnail.build_longnail()
    datasheet = longnail.select_core_datasheet(kconfig.extract_kconfig_enabled(kconfig.extract_core_from_config(kconfig_dict)))
    longnail.run_longnail(enabled_isaxes, datasheet, kconfig.extract_longnail_from_config(kconfig_dict))

    # SCAIE-V integrate into core
    scaiev.build_scaiev()
    scaiev_core_name = scaiev.select_core(kconfig.extract_kconfig_enabled(kconfig.extract_core_from_config(kconfig_dict)))
    scaiev.run_scaiev(scaiev_core_name, longnail.provide_isax_yaml())
