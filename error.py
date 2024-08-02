#!/usr/bin/env python3

USER_ERROR = 1
INTERNAL_ERROR = 1
TN_BASE = 50
LN_BASE = 100
SCAIEV_BASE = 150
SIM_BASE = 200
AWESOME_BASE = 220
GCC_BASE = 240

def exit_error(msg, error_code = -1):
    print(f"ERROR: {msg}")
    exit(error_code)
