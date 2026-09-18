#!/usr/bin/env python3
"""Generate the XCoreVSimd CV-X-IF test program + golden values.

XCoreVSimd implements the CORE-V SIMD instructions (cv.add.h, cv.avg.b, ...)
that CV32E40X does *not* have in hardware -- it ships only RV32I/E + M + A + B,
with CV-X-IF in place of the PULP extensions CV32E40P bakes in. So this is the
flow's motivating case: a real CORE-V custom ISA running on an unmodified core
through the eXtension interface.

21 instructions in three encoding shapes -- vector-vector, vector-scalar (rs2
broadcast) and vector-scalar-immediate -- exercising the glue's decoder far
harder than sparkle or ANTDOTP. No custom registers, so the interlock is not
involved here; ANTDOTP covers that.

Encodings and golden values both come from the CoreDSL -> Python model emitted
by `-coredsl-to-python` (its `decoder_table` carries the exact mask/match pair
per instruction), so nothing is re-typed by hand from the ISAX description.

    gen_test_xcorevsimd.py <clang> <ld.lld> <llvm-objcopy> <dir-with-XCoreVSimd.py>
"""
import os
import random
import sys

from testgen_common import (MMIO_BASE, RESULT_BASE, STACK_TOP,
                            build_image, write_golden)

M = 0xFFFFFFFF

MODEL_DIR = sys.argv[4]
sys.path.insert(0, MODEL_DIR)
# The CoreDSL->Python model imports ArbInt, which ships with shortnail
# rather than being copied next to the model.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "deps", "longnail", "sim"))
import XCoreVSimd as model  # noqa: E402

model.state = {}
model.init_cust_regs()

regs = [0] * 32


def rd_reg(a):
    return regs[a]


def wr_reg(a, d):
    if a:
        regs[a] = int(d) & M


A0, A1, A2, A3, A4, A5, T0 = 10, 11, 12, 13, 14, 15, 5

body = []
golden = []


def emit(line):
    body.append("  " + line)


def li(reg, val):
    emit(f"li x{reg}, 0x{val & M:08x}")
    regs[reg] = val & M


def store(reg):
    # Distinct addresses, not a streaming MMIO port: CV32E40X re-issues the OBI
    # transaction of a store parked in EX while the coprocessor blocks WB.
    # Duplicate writes of the same value to the same address are harmless.
    emit(f"sw x{reg}, {4 * len(golden)}(x{T0})")
    golden.append(regs[reg])


# --- instruction table, straight out of the model's own decoder ------------
# Each entry: (name, match_value, has_imm). `has_imm` is derived from the mask:
# the vector-scalar-immediate forms leave bit 25 free for imm[5], the
# register-register forms pin it as part of funct7.
INSNS = []
for mask, match, handler in model.decoder_table:
    INSNS.append((handler.__name__, match, ((mask >> 25) & 1) == 0))
# The count depends on which XCoreVSimd variant was built (add_avg,
# add_sub_avg, full): the generator is agnostic, it drives whatever the model's
# decoder table contains, so report rather than assert.
assert INSNS, "the model's decoder table is empty"
print(f"gen_test_xcorevsimd: {len(INSNS)} instructions in the model")


def encode(name, match, has_imm, rd, rs1, f2):
    # rs2 index (5 bits at 24:20) or immediate (6 bits at 25:20)
    field = (f2 & 0x3F) << 20 if has_imm else (f2 & 0x1F) << 20
    return match | field | (rs1 << 15) | (rd << 7)


def isax(name, match, has_imm, rd, rs1, f2, note=""):
    word = encode(name, match, has_imm, rd, rs1, f2)
    kind = f"imm={f2}" if has_imm else f"x{f2}"
    emit(f".word 0x{word:08x}   # {name} x{rd}, x{rs1}, {kind}{note}")
    getattr(model, name)(word, read_reg=rd_reg, write_reg=wr_reg)


rnd = random.Random(0x5119D)

# --- 1. every instruction, twice, with independent random operands ---------
emit("# --- all 21 CORE-V SIMD instructions, two random cases each ---")
for name, match, has_imm in INSNS:
    for _ in range(2):
        li(A0, rnd.getrandbits(32))
        if has_imm:
            isax(name, match, has_imm, A2, A0, rnd.getrandbits(6))
        else:
            li(A1, rnd.getrandbits(32))
            isax(name, match, has_imm, A2, A0, A1)
        store(A2)

# --- 2. corner-case operands (saturation / sign boundaries per lane) -------
emit("# --- corner-case operands ---")
CORNERS = [0x00000000, 0xFFFFFFFF, 0x7FFF7FFF, 0x80008000,
           0x7F7F7F7F, 0x80808080, 0x0001FFFF, 0xFFFF0001]
for name, match, has_imm in INSNS:
    a = CORNERS[rnd.randrange(len(CORNERS))]
    b = CORNERS[rnd.randrange(len(CORNERS))]
    li(A0, a)
    if has_imm:
        isax(name, match, has_imm, A2, A0, rnd.getrandbits(6))
    else:
        li(A1, b)
        isax(name, match, has_imm, A2, A0, A1)
    store(A2)

# --- 3. back-to-back bursts: four offloads, no instructions in between ----
# Checks that the shadow pipeline keeps four instructions in flight in order
# and that each result lands in its own rd.
emit("# --- back-to-back bursts of four offloads ---")
for blk in range(6):
    name, match, has_imm = INSNS[rnd.randrange(len(INSNS))]
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    for rd in (A2, A3, A4, A5):
        isax(name, match, has_imm, rd, A0,
             rnd.getrandbits(6) if has_imm else A1)
    for rd in (A2, A3, A4, A5):
        store(rd)

# --- 4. RAW through the core: consume an ISAX result immediately ----------
emit("# --- RAW on the ISAX result ---")
for _ in range(3):
    name, match, has_imm = INSNS[rnd.randrange(len(INSNS))]
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    isax(name, match, has_imm, A2, A0, rnd.getrandbits(6) if has_imm else A1)
    emit("addi x13, x12, 1")
    regs[A3] = (regs[A2] + 1) & M
    store(A3)

# --- 5. rejected illegal instruction between offloads --------------------
emit("# --- rejected illegal instruction -> commit_kill + re-execution ---")
for _ in range(3):
    name, match, has_imm = INSNS[rnd.randrange(len(INSNS))]
    li(A0, rnd.getrandbits(32))
    li(A1, rnd.getrandbits(32))
    emit(".word 0x0000007f          # illegal, not ours -> rejected")
    isax(name, match, has_imm, A2, A0, rnd.getrandbits(6) if has_imm else A1,
         note="   # killed, then re-executed after the trap")
    store(A2)

# --- 6. a loop of offloads ------------------------------------------------
emit("# --- loop of offloads ---")
name, match, has_imm = INSNS[0]          # CV_ADD_H
li(A0, 0x00010001)
li(A1, 0x00020003)
LOOP = 10
emit(f"li x6, {LOOP}")
emit("3:")
word = encode(name, match, has_imm, A2, A0, A1)
emit(f".word 0x{word:08x}   # {name} a2, a0, a1")
emit("add x10, x12, x0")                 # a0 = a2, so the loop carries a chain
emit("addi x6, x6, -1")
emit("bnez x6, 3b")
for _ in range(LOOP):
    getattr(model, name)(word, read_reg=rd_reg, write_reg=wr_reg)
    regs[A0] = regs[A2]
store(A2)

asm = f"""\
# Generated by gen_test_xcorevsimd.py -- CORE-V SIMD over CV-X-IF on CV32E40X.
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
print(f"gen_test_xcorevsimd: {len(golden)} expected results, {len(body)} asm lines")
build_image(sys.argv[1], sys.argv[2], sys.argv[3], "gen_test_xcorevsimd")
