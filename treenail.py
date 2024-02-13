#!/bin/bash
import os
import stat
import error
import run_cmd
import shutil

def run_treenail(isax_tag, coredsl_file):
    # create build and tool directory
    if not os.path.isdir("build"):
        os.mkdir("build")
    if not os.path.isdir("build/mlir"):
        os.mkdir("build/mlir")

    print(f" - Mapping {coredsl_file} to build/mlir/{isax_tag}.mlir")
    run_cmd.run(".", f"./deps/treenail/app/build/install/app/bin/app {coredsl_file} build/mlir/{isax_tag}.mlir", f"Treenail failed on {coredsl_file}", False)

def run_treenail_batch(isax_tags, coredsl_files):
    print("Running Treenail:")
    for tag, file in zip(isax_tags, coredsl_files):
        run_treenail(tag, file)

def build_treenail():
    # create build and tool directory
    if not os.path.isdir("build"):
        os.mkdir("build")
    if not os.path.isdir("build/bin"):
        os.mkdir("build/bin")

    # check that gradlew exists
    if not os.path.isfile("deps/treenail/gradlew"):
        exit_error("Treenail is not cloned. Check out submodules in this repo!")

    # build treenail
    if not os.path.isfile("build/bin/treenail"):
        print("Building Treenail...")
        run_cmd.run("deps/treenail", "./gradlew build", "Could not build treenail")
        run_cmd.run("deps/treenail", "./gradlew test", "Treenail failed tests")
        run_cmd.run("deps/treenail", "./gradlew install", "Treenail could not be installed")
        #shutil.copyfile("deps/treenail/app/build/install/app/bin/app", "build/bin/treenail")
        #st = os.stat("build/bin/treenail")
        #os.chmod("build/bin/treenail", st.st_mode | stat.S_IEXEC)