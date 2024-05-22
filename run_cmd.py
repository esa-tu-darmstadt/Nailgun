#!/usr/bin/env python3
import subprocess

import error

def run(dir, cmd, err_msg, output=True):
    proc = subprocess.Popen(f"cd {dir} && {cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while proc.poll() is None:
        output_line = proc.stdout.readline()
        if (output):
            print(output_line.decode("utf-8"), end='') #give output from your execution/your own message
    if proc.wait() != 0:
        print(f"Running command: '{cmd}' failed")
        error.exit_error(err_msg)
