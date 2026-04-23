#!/usr/bin/env python3
import gzip
import os
import subprocess
import threading
from collections import deque

import error

_log_dir = None
_cmd_counter = 0
_counter_lock = threading.Lock()

def set_log_dir(path):
    """Direct gzipped per-command log files into <path>/cmd_logs/.

    Must be called once the run's output folder is known. Before this is
    called (or if never called), run_cmd still works but does not persist
    output to disk.
    """
    global _log_dir
    _log_dir = os.path.join(path, "cmd_logs")
    os.makedirs(_log_dir, exist_ok=True)

def _next_log_path(error_code):
    global _cmd_counter
    with _counter_lock:
        idx = _cmd_counter
        _cmd_counter += 1
    return os.path.join(_log_dir, f"cmd_{idx:03}_{error.step_tag(error_code)}.log.gz")

def run(dir, cmd, err_msg, error_code, output=True, n_lines=100):
    log_path = _next_log_path(error_code) if _log_dir is not None else None
    log_file = gzip.open(log_path, "wb") if log_path else None
    if log_file:
        header = f"cd {dir} && {cmd}\n" + "=" * 80 + "\n\n"
        log_file.write(header.encode("utf-8"))

    proc = subprocess.Popen(f"cd {dir} && {cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output_lines = deque(maxlen=n_lines)  # Store the last N lines

    def proc_line(output_line):
        if not output_line:
            return
        if log_file:
            log_file.write(output_line)
        decoded_line = output_line.decode("utf-8")
        if output:
            print(decoded_line, end='')
        else:
            output_lines.append(decoded_line)

    try:
        while proc.poll() is None:
            output_line = proc.stdout.readline()
            proc_line(output_line)
        # Ensure any remaining lines are captured
        for output_line in proc.stdout:
            proc_line(output_line)
    finally:
        if log_file:
            log_file.close()

    if proc.wait() != 0:
        print(f"Running command: '{cmd}' failed")
        if not output:
            print(f"Last {n_lines} lines of the output:")
            for line in output_lines:
                print(line, end='')
        if log_path:
            print(f"Full log: {log_path}")
        error.exit_error(err_msg, error_code)
