#!/usr/bin/env python3

USER_ERROR = 1
INTERNAL_ERROR = 2
TN_BASE = 50
LN_BASE = 100
SCAIEV_BASE = 150
SIM_BASE = 200
AWESOME_BASE = 220
OPENLANE_BASE = 230
GCC_BASE = 240

def exit_error(msg, error_code = -1):
    print(f"ERROR: {msg}")
    exit(error_code)

def decode_exit_code(exit_code):
    if exit_code == 0:
        return "Success"

    # Check for predefined specific error codes
    if exit_code == USER_ERROR:
        return "User error"
    if exit_code == INTERNAL_ERROR:
        return "Internal error"

    # Check for error codes within the base ranges
    if TN_BASE <= exit_code < LN_BASE:
        return f"TN error ({exit_code})"
    if LN_BASE <= exit_code < SCAIEV_BASE:
        return f"LN error ({exit_code})"
    if SCAIEV_BASE <= exit_code < SIM_BASE:
        return f"SCAIE-V error ({exit_code})"
    if SIM_BASE <= exit_code < AWESOME_BASE:
        return f"SIM error ({exit_code})"
    if AWESOME_BASE <= exit_code < OPENLANE_BASE:
        return f"Awesome error ({exit_code})"
    if OPENLANE_BASE <= exit_code < GCC_BASE:
        return f"Openlane error ({exit_code})"
    if GCC_BASE <= exit_code:
        return f"GCC error ({exit_code})"

    # If the exit code doesn't fall into any of the above ranges, it's an unknown error
    return f"Unknown error ({exit_code})"
