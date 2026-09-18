#!/usr/bin/env python3
import contextlib
import fcntl
import gzip
import os
import subprocess
import tempfile
import threading
import time
from collections import deque

import error

_log_dir = None
_cmd_counter = 0
_counter_lock = threading.Lock()

# One sbt run holds ~5 inotify instances for its whole lifetime (sbt builds a
# global FileTreeRepository at project load and there is no way to switch that
# off), while fs.inotify.max_user_instances is 128 per user and a desktop
# session already eats most of it. Past that ceiling sbt aborts with
# "User limit of inotify instances reached" instead of generating the core.
SBT_MAX_PARALLEL_DEFAULT = 8

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

@contextlib.contextmanager
def host_semaphore(name, capacity, poll_s=1.0):
    """Let at most `capacity` processes on this host hold the section at once.

    The eval drivers fan out as separate `python3 dispatch.py` / `make ci`
    processes, so a threading.Semaphore would not bound anything. Slots are
    flock'd files: the kernel drops the lock when the holder exits, so a killed
    job cannot leak a slot. capacity <= 0 disables the limit.
    """
    if capacity <= 0:
        yield
        return

    slot_dir = os.path.join(tempfile.gettempdir(), f"ng-sem-{name}-{os.getuid()}")
    os.makedirs(slot_dir, exist_ok=True)
    announced = False
    while True:
        for idx in range(capacity):
            fd = os.open(os.path.join(slot_dir, f"slot{idx}"), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                continue
            try:
                yield
            finally:
                os.close(fd)
            return
        if not announced:
            announced = True
            print(f"[{name}] all {capacity} slots busy, waiting for a free one...")
        time.sleep(poll_s)


def sbt_semaphore():
    """Bound concurrent sbt runs so they cannot exhaust the inotify limit.

    Override with NG_SBT_MAX_PARALLEL; 0 removes the limit.
    """
    capacity = int(os.environ.get("NG_SBT_MAX_PARALLEL", SBT_MAX_PARALLEL_DEFAULT))
    return host_semaphore("sbt", capacity)


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
