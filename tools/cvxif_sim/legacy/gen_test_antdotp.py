#!/usr/bin/env python3
"""Generate the ANTDOTP CV-X-IF test program + golden values.

ANTDOTP has four ISAX-private custom registers (signInfo, primInfo, macAcc,
dotpAcc), so this program targets the parts of the glue that sparkle does not
reach: the custom-register files and the admission interlock that orders
accesses to them.

The golden values come from the CoreDSL -> Python model that Longnail's
`-coredsl-to-python` pass emits (ISAX_<name>.py, next to ArbInt.py). That model
is produced by the CoreDSL frontend, independently of the hardware-generation
path being tested, so it is a genuine reference rather than a restatement of
the RTL.

    gen_test_antdotp.py <clang> <ld.lld> <llvm-objcopy> <dir-with-ANTDOTP.py>
"""
import os
import random
import sys

from testgen_common import (MMIO_BASE, RESULT_BASE, STACK_TOP,
                            build_image, write_golden)

M = 0xFFFFFFFF
OPC = 0b0101011  # custom-1: illegal to CV32E40X, so it gets offered on the XIF

# funct7, funct3 per the ISAX encoding masks
ENC = {
    "SETUP":        (0b0000000, 0b000),
    "DECODE_FLINT": (0b0000000, 0b001),
    "ANTMUL":       (0b0000000, 0b010),
    "ANTMAC":       (0b0000000, 0b011),
    "ANTDOTP8ACC":  (0b0000000, 0b100),
    "ANTMACR":      (0b0000001, 0b011),
    "ANTDOTP8ACCR": (0b0000001, 0b100),
    "ANTDOTP8":     (0b0000010, 0b100),
}


def encode(name, rd=0, rs1=0, rs2=0):
    f7, f3 = ENC[name]
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | OPC


# --------------------------------------------------------------------------
# reference model
# --------------------------------------------------------------------------
MODEL_DIR = sys.argv[4]
sys.path.insert(0, MODEL_DIR)
# The CoreDSL->Python model imports ArbInt, which ships with shortnail
# rather than being copied next to the model.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "deps", "longnail", "sim"))
import ANTDOTP as model  # noqa: E402

model.state = {}
model.init_cust_regs()

regs = [0] * 32


def rd_reg(a):
    return regs[a]


def wr_reg(a, d):
    if a:                       # x0 stays 0
        regs[a] = int(d) & M


def run_model(name, word):
    getattr(model, name)(word, read_reg=rd_reg, write_reg=wr_reg)


# --------------------------------------------------------------------------
# program construction
# --------------------------------------------------------------------------
A0, A1, A2, A3, A4, A5, T0 = 10, 11, 12, 13, 14, 15, 5

body = []
golden = []


def emit(line):
    body.append("  " + line)


def li(reg, val):
    emit(f"li x{reg}, 0x{val & M:08x}")
    regs[reg] = val & M


def isax(name, rd=0, rs1=0, rs2=0, note=""):
    word = encode(name, rd, rs1, rs2)
    emit(f".word 0x{word:08x}   # {name} x{rd}, x{rs1}, x{rs2}{note}")
    run_model(name, word)


# Results go to distinct addresses in RAM rather than to a streaming MMIO port:
# CV32E40X re-issues the OBI transaction of a store parked in EX whenever the
# LSU's outstanding counter drains, which happens constantly here because the
# ISAX blocks WB. Duplicate writes of the same value to the same address are
# architecturally harmless; a streaming port would miscount them.
def store(reg):
    emit(f"sw x{reg}, {4 * len(golden)}(x{T0})")
    golden.append(regs[reg])


rnd = random.Random(0xA47D07)

# --- 1. configure, then reset both accumulators ---------------------------
emit("# --- configure signInfo / primInfo, reset the accumulators ---")
li(A0, 1)                       # signInfo = 1
li(A1, 0)                       # primInfo = 0 (FLINT)
isax("SETUP", rs1=A0, rs2=A1)
isax("ANTMACR", note="   # macAcc = 0")
isax("ANTDOTP8ACCR", note="   # dotpAcc = 0")

# --- 2. one of each value-producing instruction ---------------------------
emit("# --- one of each ---")
li(A0, 0x89ABCDEF)
isax("DECODE_FLINT", rd=A2, rs1=A0)
store(A2)

li(A0, 0x12345678)
li(A1, 0x9ABCDEF0)
isax("ANTMUL", rd=A2, rs1=A0, rs2=A1)
store(A2)

isax("ANTDOTP8", rd=A2, rs1=A0, rs2=A1)
store(A2)

# --- 3. accumulator chain: back-to-back ANTMAC ----------------------------
# Each ANTMAC reads macAcc at shadow-pipeline stage 0 and writes it at stage 3,
# so consecutive ones are exactly the read-after-write case the glue's
# admission interlock exists to order. No instructions in between.
emit("# --- back-to-back ANTMAC: macAcc RAW chain through the interlock ---")
for blk in range(4):
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    for rd in (A2, A3, A4, A5):
        isax("ANTMAC", rd=rd, rs1=A0, rs2=A1)
    for rd in (A2, A3, A4, A5):
        store(rd)

# --- 4. accumulator chain: back-to-back ANTDOTP8ACC -----------------------
emit("# --- back-to-back ANTDOTP8ACC: dotpAcc RAW chain ---")
for blk in range(3):
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    for rd in (A2, A3, A4, A5):
        isax("ANTDOTP8ACC", rd=rd, rs1=A0, rs2=A1)
    for rd in (A2, A3, A4, A5):
        store(rd)

# --- 5. reconfigure between accumulations ---------------------------------
# SETUP writes signInfo/primInfo, which every other instruction reads: the
# interlock has to order those too.
emit("# --- SETUP interleaved with accumulating instructions ---")
for sign, prim in ((0, 0), (1, 1), (0, 2), (1, 0)):
    li(A0, sign)
    li(A1, prim)
    isax("SETUP", rs1=A0, rs2=A1)
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    isax("ANTMAC", rd=A2, rs1=A0, rs2=A1)
    isax("ANTDOTP8ACC", rd=A3, rs1=A0, rs2=A1)
    isax("ANTMUL", rd=A4, rs1=A0, rs2=A1)
    store(A2)
    store(A3)
    store(A4)

# --- 6. accumulator resets interleaved with accumulation ------------------
emit("# --- resets interleaved with accumulation ---")
for i in range(3):
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    isax("ANTMAC", rd=A2, rs1=A0, rs2=A1)
    isax("ANTMACR")
    isax("ANTMAC", rd=A3, rs1=A0, rs2=A1)
    isax("ANTDOTP8ACCR")
    isax("ANTDOTP8ACC", rd=A4, rs1=A0, rs2=A1)
    store(A2)
    store(A3)
    store(A4)

# --- 7. a rejected illegal instruction in the middle ----------------------
# Exercises reject + commit_kill while custom-register state is live.
emit("# --- rejected illegal instruction between accumulations ---")
li(A0, rnd.getrandbits(32))
li(A1, rnd.getrandbits(32))
emit(".word 0x0000007f          # illegal, not ours -> rejected -> commit_kill")
isax("ANTMAC", rd=A2, rs1=A0, rs2=A1, note="   # killed, then re-executed")
store(A2)

# --- 8. a loop of accumulations ------------------------------------------
emit("# --- loop of accumulations ---")
isax("ANTMACR")
li(A0, 0x0F0F0F0F)
li(A1, 0x33333333)
LOOP = 12
emit(f"li x6, {LOOP}")
emit("3:")
emit(f".word 0x{encode('ANTMAC', A2, A0, A1):08x}   # ANTMAC a2, a0, a1")
emit("addi x6, x6, -1")
emit("bnez x6, 3b")
for _ in range(LOOP):
    run_model("ANTMAC", encode("ANTMAC", A2, A0, A1))
store(A2)

asm = f"""\
# Generated by gen_test_antdotp.py -- ANTDOTP ISAX over CV-X-IF on CV32E40X.
  .section .text
  .globl _start
_start:
  li x5, 0x{RESULT_BASE:08x}          # x5/t0 = result array base
  li x2, 0x{STACK_TOP:08x}          # sp
  la x28, trap_handler
  csrw mtvec, x28
  j past_handler
  .balign 128                # CV32E40X: mtvec.base is WARL, 128-byte aligned
trap_handler:
  csrr x28, mepc
  addi x28, x28, 4
  csrw mepc, x28
  mret
past_handler:
""" + "\n".join(body) + f"""
  li x6, 1
  li x7, 0x{MMIO_BASE + 4:08x}
  sw x6, 0(x7)             # signal completion
9:
  j 9b
"""

with open("test.S", "w") as f:
    f.write(asm)

write_golden(golden, result_in_mem=True)
print(f"gen_test_antdotp: {len(golden)} expected results, {len(body)} asm lines")
build_image(sys.argv[1], sys.argv[2], sys.argv[3], "gen_test_antdotp")
