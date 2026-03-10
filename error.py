#!/usr/bin/env python3

USER_ERROR = 1
INTERNAL_ERROR = 2
TN_BASE = 50
LN_BASE = 100
SCAIEV_BASE = 150
PICOLIBC_BASE = 190
SIM_BASE = 200
LLVM_PATCHER_BASE = 220
LIBRELANE_BASE = 230

def exit_error(msg, error_code = -1):
    print(f"ERROR: {msg}")
    exit(error_code)

def decode_exit_code(exit_code, id):
    if exit_code == 0:
        return "Success"

    # Check for predefined specific error codes
    if exit_code == USER_ERROR:
        return f"User error ID={id}"
    if exit_code == INTERNAL_ERROR:
        return f"Internal error ID={id}"

    # Check for error codes within the base ranges
    if TN_BASE <= exit_code < LN_BASE:
        return f"TN error ({exit_code}) ID={id}"
    if LN_BASE <= exit_code < SCAIEV_BASE:
        return f"LN error ({exit_code}) ID={id}"
    if SCAIEV_BASE <= exit_code < SIM_BASE:
        return f"SCAIE-V error ({exit_code}) ID={id}"
    if SIM_BASE <= exit_code < LLVM_PATCHER_BASE:
        return f"SIM error ({exit_code}) ID={id}"
    if LLVM_PATCHER_BASE <= exit_code < LIBRELANE_BASE:
        return f"LLVM patcher error ({exit_code}) ID={id}"
    if LIBRELANE_BASE <= exit_code:
        return f"Openlane error ({exit_code})"

    # If the exit code doesn't fall into any of the above ranges, it's an unknown error
    return f"Unknown error ({exit_code}) ID={id}"
