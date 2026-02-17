#!/usr/bin/env python3
import os
from concurrent.futures import ThreadPoolExecutor

import error
import run_cmd

def run_treenail_batch(isax_tags, coredsl_files, out_dir):
    # create build and tool directory
    mlir_dir = os.path.join(out_dir, "mlir")
    os.makedirs(mlir_dir, exist_ok=True)

    print("Running Treenail:")
    mlir_paths = []
    jobs = []
    for isax_tag, coredsl_file in zip(isax_tags, coredsl_files):
        out_path = os.path.abspath(os.path.join(mlir_dir, f"{isax_tag}.mlir"))
        mlir_paths.append(out_path)
        print(f" - Mapping {coredsl_file} to {out_path}")
        jobs.append((coredsl_file, out_path))

    def coredsl_to_mlir(job):
        coredsl_file, out_path = job
        run_cmd.run(".", f"./deps/treenail/app/build/install/app/bin/app {coredsl_file} -o {out_path}", f"Treenail failed on {coredsl_file}", error.TN_BASE + 4, False, 200)

    # Parallel translate the coredsl files to mlir
    num_threads = min(len(jobs), os.cpu_count())
    # Create a ThreadPoolExecutor with the desired number of threads
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        executor.map(coredsl_to_mlir, jobs)

    return mlir_paths

def build_treenail():
    # check that gradlew exists
    if not os.path.isfile("deps/treenail/gradlew"):
        error.exit_error("Treenail is not cloned. Check out submodules in this repo!", error.USER_ERROR)

    # build treenail
    if not os.path.isfile("./deps/treenail/app/build/install/app/bin/app"):
        print("Building Treenail...")
        run_cmd.run("deps/treenail", "./gradlew build", "Could not build treenail", error.TN_BASE + 1)
        run_cmd.run("deps/treenail", "./gradlew test", "Treenail failed tests", error.TN_BASE + 2)
        run_cmd.run("deps/treenail", "./gradlew install", "Treenail could not be installed", error.TN_BASE + 3)
