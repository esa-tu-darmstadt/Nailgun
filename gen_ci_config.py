#!/usr/bin/env python3
import os
import kconfiglib


if __name__ == "__main__":
    # Read in Kconfig & .config file
    kconf = kconfiglib.Kconfig("Kconfig")

    # Apply 1:1 mappings from env vars to kconf symbols:
    for k, v in os.environ.items():
        if k in kconf.syms:
            kconf.syms[k].set_value(v)

    core = os.getenv("CORE")
    if core:
        kconf.syms[f"CORE_{core}"].set_value("y")
    isaxes = os.getenv("ISAXES")
    if isaxes:
        isaxes = isaxes.split(',')
        for isax in isaxes:
            kconf.syms[f"ISAX_{isax}_EN"].set_value("y")

    tb_path = os.getenv("TB_PATH")
    tb_expected_path = os.getenv("TB_EXPECTED_PATH")
    if tb_path and tb_expected_path:
        tb_path = os.path.abspath(tb_path)
        tb_expected_path = os.path.abspath(tb_expected_path)
        kconf.syms["SIM_TB_PATH"].set_value(tb_path)
        kconf.syms["SIM_TB_EXPECTED_PATH"].set_value(tb_expected_path)
    iss_lockstep = os.getenv("SIM_ENABLE_ISS_LOCKSTEP")
    if iss_lockstep:
        kconf.syms["SIM_ENABLE"].set_value("y")

    ilp_solver = os.getenv("LN_ILP_SOLVER")
    if ilp_solver:
        kconf.syms["LN_SOLVER_USE_" + ilp_solver].set_value("y")

    # Activate the custom model option, the path will be automatically set
    if os.getenv("LN_OPTY_CUSTOM_MODEL_PATH"):
        kconf.syms["LN_OPTY_CUSTOM_MODEL"].set_value("y")

    sv_path = os.getenv("SV_ENTRY_POINT_PATH")
    yaml_path = os.getenv("SV_ENTRY_POINT_ISAX_YAML_PATH")
    if sv_path and yaml_path:
        kconf.syms["SV_ENTRY_POINT"].set_value("y")
        kconf.syms["SV_ENTRY_POINT_PATH"].set_value(sv_path)
        kconf.syms["SV_ENTRY_POINT_ISAX_YAML_PATH"].set_value(yaml_path)
    else:
        no_isax = os.getenv("NO_ISAX")
        if no_isax:
            kconf.syms["NO_ISAX_ENTRY_POINT"].set_value("y")

    ln_scheduling_config = os.getenv("LN_PREDEFINED_SOLUTION_SELECTION")
    if ln_scheduling_config:
        kconf.syms["LN_PREDEFINED_SOLUTION_SELECTION"].set_value(ln_scheduling_config)
    else:
        # The CI can not perform user interactions -> we must skip the solution selection process if no solution selection is given
        kconf.syms["LN_FORCE_MIN_II_SOLUTIONS"].set_value("y")

    # Write the generated .config file
    config_out_path = os.getenv("CONFIG_PATH")
    if config_out_path:
        kconf.write_config(config_out_path)
    else:
        kconf.write_config(".config")
