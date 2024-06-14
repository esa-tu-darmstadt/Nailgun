#!/usr/bin/env python3
import os
import kconfiglib


if __name__ == "__main__":
    # Read in Kconfig & .config file
    kconf = kconfiglib.Kconfig("Kconfig")

    core = os.getenv("CORE")
    if core:
        kconf.syms[f"CORE_{core}"].set_value("y")
    isaxes = os.getenv("ISAXES")
    if isaxes:
        isaxes = isaxes.split(',')
        for isax in isaxes:
            kconf.syms[f"ISAX_{isax}_EN"].set_value("y")

    sim_en = os.getenv("SIM_EN")
    if sim_en:
        kconf.syms["SIM_ENABLE"].set_value(sim_en)
    tb_path = os.getenv("TB_PATH")
    tb_expected_path = os.getenv("TB_EXPECTED_PATH")
    if tb_path and tb_expected_path:
        tb_path = os.path.abspath(tb_path)
        tb_expected_path = os.path.abspath(tb_expected_path)
        kconf.syms["SIM_TB_PATH"].set_value(tb_path)
        kconf.syms["SIM_TB_EXPECTED_PATH"].set_value(tb_expected_path)

    #TODO add option to specify the scheduling algorithm
    
    kconf.syms["LN_USE_COMMERCIAL_SOLVER"].set_value("y")

    kconf.write_config(".config")

