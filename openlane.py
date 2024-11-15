#!/usr/bin/env python3
import os
import glob

import scaiev
import error

from tools.hw_syn import dse
from tools.hw_syn import run_openlane

def run_synthesis(out_dir, core_name, kconfig_syms, isax_name):
    if kconfig_syms['OL2_ENABLE'].str_value != "y":
        return

    # Create the output directory
    syn_dir = os.path.abspath(os.path.join(out_dir, "hw_syn"))
    os.makedirs(syn_dir, exist_ok=False)

    _external_tb_srcs, core_srcs, _tb_top_module, core_top_module, _extra_makefile_opts = scaiev.select_tb_wrapper_srcs(core_name, out_dir)

    core_base = os.path.abspath(os.path.join(out_dir, core_name))
    core_srcs = list(map(lambda s: os.path.join(core_base, s), core_srcs))

    if core_name == "CVA5" or core_name == "CVA6":
        error.exit_error(f"{core_name} is not synthesizable with OL2")
        # CVA6 might actually work(with sv2v preprocessing), but I did not wanted to add all includes manually!

    isax_src = list(map(lambda s: os.path.abspath(s), glob.glob(os.path.join(out_dir, '*.sv'))))
    isax_src = isax_src + list(map(lambda s: os.path.abspath(s), glob.glob(os.path.join(out_dir, '*.v'))))
    verilog_srcs = core_srcs + isax_src

    #TODO get algorithm name from LN
    algo_name = "LEGACY"
    config_template = kconfig_syms["OL2_CONFIG_TEMPLATE"].str_value
    clock_period = 1000.0 / int(kconfig_syms["OL2_TARGET_FREQ"].str_value)
    fp_util = int(kconfig_syms["OL2_TARGET_UTIL"].str_value)
    top_module = core_top_module
    clk_name = "clk"
    if kconfig_syms["OL2_ONLY_SYN_ISAX"].str_value == "y":
        top_module = f"ISAX_{isax_name.upper()}"
        verilog_srcs = isax_src
        clk_name = "clk_i"
    
    if kconfig_syms["OL2_DSE"].str_value == "y":
        # Start DSE
        dse.run_dse(verilog_srcs, syn_dir, "dummyName", algo_name, clock_period, fp_util, top_module, clk_name, config_template)
    else:
        # Only perfom a single openlane run
        config_values = dse.get_config_values(top_module, clk_name, clock_period, fp_util)
        config_values['{{SRC_FILES}}'] = dse.get_ol_config_src_entries(verilog_srcs, syn_dir)
        run_openlane.run_openlane(syn_dir, config_template, config_values, None, None)
