#!/usr/bin/env python3

USER_ERROR = 1
INTERNAL_ERROR = 2
TN_BASE = 50
LN_BASE = 100
SCAIEV_BASE = 150
PICOLIBC_BASE = 190
SIM_BASE = 200
LLVM_BASE = 220
LIBRELANE_BASE = 230

def exit_error(msg, error_code = -1):
    print(f"ERROR: {msg}")
    exit(error_code)

# Error-code ranges: (low, high, short_tag, display_label). `high=None` means open-ended.
# The short tag is used for log filenames; the label is used by decode_exit_code.
_RANGES = [
    (TN_BASE,        LN_BASE,         "tn",        "TN"),
    (LN_BASE,        SCAIEV_BASE,     "ln",        "LN"),
    (SCAIEV_BASE,    PICOLIBC_BASE,   "scaiev",    "SCAIE-V"),
    (PICOLIBC_BASE,  SIM_BASE,        "picolibc",  "Picolibc"),
    (SIM_BASE,       LLVM_BASE,       "sim",       "SIM"),
    (LLVM_BASE,      LIBRELANE_BASE,  "llvm",      "LLVM"),
    (LIBRELANE_BASE, None,            "librelane", "Openlane"),
]

def _classify(code):
    for lo, hi, tag, label in _RANGES:
        if code >= lo and (hi is None or code < hi):
            return tag, label
    return None

def step_tag(error_code):
    """Short lowercase tag for the pipeline step owning this error code (e.g. 'ln', 'llvm')."""
    c = _classify(error_code)
    return c[0] if c else "misc"

def decode_exit_code(exit_code, id):
    if exit_code == 0:
        return "Success"
    if exit_code == USER_ERROR:
        return f"User error ID={id}"
    if exit_code == INTERNAL_ERROR:
        return f"Internal error ID={id}"
    c = _classify(exit_code)
    if c is None:
        return f"Unknown error ({exit_code}) ID={id}"
    _, label = c
    # Openlane errors historically omit the ID suffix.
    if label == "Openlane":
        return f"Openlane error ({exit_code})"
    return f"{label} error ({exit_code}) ID={id}"
