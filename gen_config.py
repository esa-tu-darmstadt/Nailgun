#!/usr/bin/env python3
import os

def get_isaxes(directory):
    isaxes = []
    for root, _, files in os.walk(directory):
        for name in files:
            if name.endswith('.core_desc'):
                isaxes.append(os.path.join(root, name))
    return isaxes


if __name__ == "__main__":
    isaxes = get_isaxes("isaxes")

    # Extract the filename without the file extension
    isax_names = map(lambda isax: os.path.splitext(
        os.path.basename(isax))[0], isaxes)

    kconfig_outdir = "build/ISAX"
    os.makedirs(kconfig_outdir, exist_ok=True)

    with open(os.path.join(kconfig_outdir, "Kconfig"), 'w') as file:
        file.write(f"""
menu "Select ISAXes"

depends on DEFAULT_ENTRY_POINT

source "{kconfig_outdir}/*/Kconfig"

endmenu
""")

    # Generate KConfig files
    for name, path in zip(isax_names, isaxes):
        kconfig_dir = os.path.join(kconfig_outdir, name)
        os.makedirs(kconfig_dir, exist_ok=True)

        # Generate Kconfig file for the isax
        kconfig_file = os.path.join(kconfig_dir, "Kconfig")
        with open(kconfig_file, 'w') as file:
            file.write(f"""
config ISAX_{name.upper()}_EN
    bool "{name} ISAX"
    help
        enable {name} ISAX
""")
        # Generate paths.csv file for the isax
        path_csv_file = os.path.join(kconfig_dir, "paths.csv")
        with open(path_csv_file, 'w') as file:
            file.write(f"ISAX_{name.upper()}_EN;{path}\n")
