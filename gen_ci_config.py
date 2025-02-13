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

    ilp_solver = os.getenv("LN_ILP_SOLVER")
    if ilp_solver:
        kconf.syms["LN_SOLVER_USE_" + ilp_solver].set_value("y")

    llvm_ver = os.getenv("AWESOME_LLVM_VERSION")
    if llvm_ver:
        kconf.syms["SIM_AWESOME_LLVM_VERSION"].set_value(llvm_ver)

    skip_llvm_build = os.getenv("SKIP_AWESOME_LLVM")
    if skip_llvm_build:
        kconf.syms["SIM_SKIP_AWESOME_LLVM"].set_value(skip_llvm_build)

    ol2_optylib = os.getenv("USE_OL2_MODEL")
    if ol2_optylib:
        kconf.syms["LN_OPTY_OL2_MODEL"].set_value(ol2_optylib)

    clk_period = os.getenv("CLOCK_TIME")
    if clk_period:
        kconf.syms["LN_CLOCK_PERIOD"].set_value(clk_period)

    custom_opty_model_path = os.getenv("LN_OPTY_CUSTOM_MODEL_PATH")
    if custom_opty_model_path:
        kconf.syms["LN_OPTY_CUSTOM_MODEL"].set_value("y")
        kconf.syms["LN_OPTY_CUSTOM_MODEL_PATH"].set_value(custom_opty_model_path)

    mlir_path = os.getenv("MLIR_ENTRY_POINT_PATH")
    if mlir_path:
        kconf.syms["MLIR_ENTRY_POINT"].set_value("y")
        kconf.syms["MLIR_ENTRY_POINT_PATH"].set_value(mlir_path)

        mlir_scheduled = os.getenv("MLIR_ENTRY_POINT_IS_SCHEDULED")
        if mlir_scheduled:
            kconf.syms[f"MLIR_ENTRY_POINT_IS_SCHEDULED"].set_value("y")
    else:
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

    isax_name = os.getenv("CLANG_EXT_ISAX_NAME")
    if isax_name:
        kconf.syms["SIM_AWESOME_LLVM_OVERWRITE_ISAX_NAME"].set_value("y")
        kconf.syms["SIM_AWESOME_LLVM_ISAX_NAME"].set_value(isax_name)

    tb_flags = os.getenv("TB_CPP_FLAGS")
    if tb_flags:
        kconf.syms["SIM_TB_COMPILE_FLAGS"].set_value(tb_flags)

    ln_scheduling_config = os.getenv("LN_PREDEFINED_SOLUTION_SELECTION")
    if ln_scheduling_config:
        kconf.syms[f"LN_PREDEFINED_SOLUTION_SELECTION"].set_value(ln_scheduling_config)
    else:
        # The CI can not perform user interactions -> we must skip the solution selection process if no solution selection is given
        kconf.syms[f"LN_FORCE_MIN_II_SOLUTIONS"].set_value("y")


    # Write the generated .config file
    config_out_path = os.getenv("CONFIG_PATH")
    if config_out_path:
        kconf.write_config(config_out_path)
    else:
        kconf.write_config(".config")
