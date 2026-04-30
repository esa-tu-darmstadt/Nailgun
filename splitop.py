#!/usr/bin/env python3
import glob
import os
import shutil
import sys

import error
import run_cmd

SPLITOP_GEN_PATH = "deps/splitop-gen"

def _rtl_primitives_dir():
    return os.path.abspath(os.path.join(SPLITOP_GEN_PATH, "splitop_gen", "rtl"))

def _append_filelist(out_dir, rel_files):
    filelist = os.path.join(out_dir, "filelist.f")
    with open(filelist, "a") as f:
        for rel in rel_files:
            f.write(rel + "\n")

def run_splitop_gen(splitops_yaml_dir, out_dir, kconf_syms, show_output=False):
    splitops_yaml_dir = os.path.abspath(splitops_yaml_dir)
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(splitops_yaml_dir):
        return

    yamls = sorted(glob.glob(os.path.join(splitops_yaml_dir, "*.yaml")))
    if not yamls:
        return

    print("Running splitop-gen:")
    generate_testbench = kconf_syms['LN_SPLITOP_GEN_TESTBENCH'].str_value == "y"
    rtl_dir = _rtl_primitives_dir()
    env_prefix = f"PYTHONPATH={os.path.abspath(SPLITOP_GEN_PATH)}"

    more_flags = "--register-inputs" if kconf_syms["LN_LATENCY_1_OPS_LATCH_INPUTS"].str_value == "y" else ""

    generated_sv = []
    for yaml_path in yamls:
        module_name = os.path.splitext(os.path.basename(yaml_path))[0]
        sv_out = os.path.join(out_dir, f"{module_name}.sv")
        if generate_testbench:
            tb_dir = os.path.join(out_dir, f"splitop_tb_{module_name}")
            tb_flag = f" --testbench --testbench-dir {tb_dir}"
        else:
            tb_flag = ""
        cmd = (
            f"{env_prefix} {sys.executable} -m splitop_gen.cli "
            f" {more_flags} "
            f"{yaml_path} -o {sv_out} --rtl-dir {rtl_dir}{tb_flag}"
        )
        run_cmd.run(".", cmd, f"splitop-gen failed for {yaml_path}",
                    error.LN_BASE + 12, show_output, 200)
        generated_sv.append(f"{module_name}.sv")

    # Copy all rtl primitives into out_dir so they end up in the filelist alongside
    # the generated split-op modules. Primitives are tiny and harmless if unused.
    copied_primitives = []
    for prim in sorted(os.listdir(rtl_dir)):
        if not prim.endswith(".sv"):
            continue
        shutil.copy(os.path.join(rtl_dir, prim), os.path.join(out_dir, prim))
        copied_primitives.append(prim)

    _append_filelist(out_dir, copied_primitives + generated_sv)
