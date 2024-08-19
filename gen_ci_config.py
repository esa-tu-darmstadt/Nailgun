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

    commercial_solver_en = os.getenv("LN_USE_COMMERCIAL_SOLVER")
    if commercial_solver_en:
        kconf.syms["LN_USE_COMMERCIAL_SOLVER"].set_value(commercial_solver_en)

    llvm_ver = os.getenv("AWESOME_LLVM_VERSION")
    if llvm_ver:
        kconf.syms["SIM_AWESOME_LLVM_VERSION"].set_value(llvm_ver)

    skip_llvm_build = os.getenv("SKIP_AWESOME_LLVM")
    if skip_llvm_build:
        kconf.syms["SIM_SKIP_AWESOME_LLVM"].set_value(skip_llvm_build)

    cell_library = os.getenv("LN_CELL_LIBRARY")
    if cell_library:
        kconf.syms["LN_CELL_LIBRARY"].set_value(cell_library)

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

    
    ms = os.getenv("LN_SCHED_ALGO_MS")
    if ms and ms == "y":
        kconf.syms["LN_SCHED_ALGO_MS"].set_value(ms)
        pa = os.getenv("LN_SCHED_ALGO_PA")
        if pa and pa == "y":
            kconf.syms["LN_SCHED_ALGO_PA"].set_value(pa)
        ra = os.getenv("LN_SCHED_ALGO_RA")
        if ra and ra == "y":
            kconf.syms["LN_SCHED_ALGO_RA"].set_value(ra)
        mi = os.getenv("LN_SCHED_ALGO_MI")
        if mi and mi == "y":
            kconf.syms["LN_SCHED_ALGO_MI"].set_value(mi)

    mlir_path = os.getenv("MLIR_ENTRY_POINT_PATH")
    if mlir_path:
        kconf.syms["MLIR_ENTRY_POINT"].set_value("y")
        kconf.syms["MLIR_ENTRY_POINT_PATH"].set_value(mlir_path)

    only_add_cc_support = os.getenv("ONLY_PATCH_CC")
    if only_add_cc_support:
        kconf.syms["ONLY_PATCH_CC"].set_value(only_add_cc_support)

    isax_name = os.getenv("CLANG_EXT_ISAX_NAME")
    if isax_name:
        kconf.syms["SIM_AWESOME_LLVM_OVERWRITE_ISAX_NAME"].set_value("y")
        kconf.syms["SIM_AWESOME_LLVM_ISAX_NAME"].set_value(isax_name)

    tb_flags = os.getenv("TB_CPP_FLAGS")
    if tb_flags:
        kconf.syms["SIM_TB_COMPILE_FLAGS"].set_value(tb_flags)

    # The CI can not perform user interactions -> we must skip the solution selection process
    # TODO allow specifying a yaml file that contains the selections instead -> better automatization
    kconf.syms["LN_FORCE_MIN_II_SOLUTIONS"].set_value("y")

    # Write the generated .config file
    config_out_path = os.getenv("CONFIG_PATH")
    if config_out_path:
        kconf.write_config(config_out_path)
    else:
        kconf.write_config(".config")
