#!/usr/bin/env python3
"""Generate the sparkle CV-X-IF test program + golden values.

Emits test.S (RISC-V assembly, custom instructions as .word) and golden.svh
(the expected result stream for the testbench).
"""
import random
import sys

from testgen_common import MMIO_BASE, STACK_TOP, build_image, write_golden

M = 0xFFFFFFFF
RCON = [0xB7E15162, 0xBF715880, 0x38B4DA56, 0x324E7738,
        0xBB1185EB, 0x4F7C7B57, 0xCFBFA1C8, 0xC2B3293D]
ROT0 = [31, 17, 0, 24]
ROT1 = [24, 17, 31, 16]


def rotr(x, s):
    x &= M
    hi = 0 if s == 0 else (x << (32 - s)) & M
    return (x >> s) | hi


def ell(x):
    return rotr((x ^ ((x << 16) & M)) & M, 16)


def enci(a, b, imm, want_y):
    xi, yi, ci = a & M, b & M, RCON[imm]
    for k in range(4):
        xi = (xi + rotr(yi, ROT0[k])) & M
        yi = (yi ^ rotr(xi, ROT1[k])) & M
        xi = (xi ^ ci) & M
    return yi if want_y else xi


OPC = 0b1111011


def enc_ell(rd, rs1, rs2):
    return (0b0000010 << 25) | (rs2 << 20) | (rs1 << 15) | (0b111 << 12) \
        | (rd << 7) | OPC


def enc_f110(top4, imm, rd, rs1, rs2):
    return (top4 << 28) | (imm << 25) | (rs2 << 20) | (rs1 << 15) \
        | (0b110 << 12) | (rd << 7) | OPC


def enc_rcon(rd, rs1, rs2, imm):
    return enc_f110(0b0000, imm, rd, rs1, rs2)


def enc_encix(rd, rs1, rs2, imm):
    return enc_f110(0b1000, imm, rd, rs1, rs2)


def enc_enciy(rd, rs1, rs2, imm):
    return enc_f110(0b1001, imm, rd, rs1, rs2)


A0, A1, A2, A3, A4, T0, T1, T2 = 10, 11, 12, 13, 14, 5, 6, 7

body = []
golden = []


def emit(line):
    body.append("  " + line)


def li(reg, val):
    emit(f"li x{reg}, 0x{val & M:08x}")


def store_result(reg):
    emit(f"sw x{reg}, 0(x{T0})")


def case_ell(x, y):
    li(A0, x); li(A1, y)
    emit(f".word 0x{enc_ell(A2, A0, A1):08x}   # sparkle_ell a2, a0, a1")
    store_result(A2)
    golden.append(ell(x ^ y))


def case_rcon(x, imm):
    li(A0, x)
    emit(f".word 0x{enc_rcon(A2, A0, 0, imm):08x}   # sparkle_rcon a2, a0, imm={imm}")
    store_result(A2)
    golden.append((x ^ RCON[imm]) & M)


def case_enci(x, y, imm, want_y):
    li(A0, x); li(A1, y)
    e = enc_enciy(A2, A0, A1, imm) if want_y else enc_encix(A2, A0, A1, imm)
    emit(f".word 0x{e:08x}   # sparkle_whole_enci_{'y' if want_y else 'x'} a2, a0, a1")
    store_result(A2)
    golden.append(enci(x, y, imm, want_y))


rnd = random.Random(0xC0FFEE)

# --- 1. one of each, in isolation ---------------------------------------
emit("# --- basic: one of each ---")
case_ell(0x12345678, 0x9ABCDEF0)
case_rcon(0xDEADBEEF, 3)
case_enci(0x01234567, 0x89ABCDEF, 5, False)
case_enci(0x01234567, 0x89ABCDEF, 5, True)

# --- 2. back-to-back ISAX instructions (issue throughput) ----------------
emit("# --- back-to-back offloads ---")
for _ in range(8):
    case_ell(rnd.getrandbits(32), rnd.getrandbits(32))

# --- 3. RAW: the core must forward an ISAX result to the next instruction --
emit("# --- RAW on the ISAX result: add a2 (from XIF) into a3 ---")
x, y = rnd.getrandbits(32), rnd.getrandbits(32)
li(A0, x); li(A1, y)
emit(f".word 0x{enc_ell(A2, A0, A1):08x}   # sparkle_ell a2, a0, a1")
emit("addi x13, x12, 1")     # a3 = a2 + 1, consumes the XIF writeback
store_result(A3)
golden.append((ell(x ^ y) + 1) & M)

# --- 4. ISAX consuming a value produced by the immediately preceding insn --
emit("# --- RAW into the ISAX: operand produced one cycle earlier ---")
x, y = rnd.getrandbits(32), rnd.getrandbits(32)
li(A0, x)
li(A3, y)
emit("add x11, x13, x0")     # a1 = a3, so rs2 comes straight from the ALU
emit(f".word 0x{enc_ell(A2, A0, A1):08x}   # sparkle_ell a2, a0, a1")
store_result(A2)
golden.append(ell(x ^ y))

# --- 5. rd = x0 must be discarded ---------------------------------------
emit("# --- writeback to x0 is ignored ---")
li(A0, 0x11112222); li(A1, 0x33334444)
emit(f".word 0x{enc_ell(0, A0, A1):08x}   # sparkle_ell x0, a0, a1")
emit("addi x12, x0, 0x55")
store_result(A2)
golden.append(0x55)

# --- 6. offloads in the shadow of a taken branch (commit_kill) -----------
emit("# --- speculative offload killed by a taken branch ---")
for i in range(4):
    li(T1, 1)
    li(A0, 0xA5A50000 | i); li(A1, 0x5A5A0000 | i)
    emit(f"beq x{T1}, x{T1}, 1f          # always taken -> flushes what follows")
    emit(f".word 0x{enc_ell(A2, A0, A1):08x}   # must be killed, never retired")
    emit(f".word 0x{enc_rcon(A2, A0, 0, 1):08x}   # must be killed, never retired")
    emit("1:")
    # after the branch, the pipeline must still be sane
    case_ell(0xCAFE0000 | i, 0xBABE0000 | i)

# --- 6b. rejected illegal instruction -> commit_kill --------------------
# An illegal instruction the coprocessor does NOT claim is still offered on the
# issue interface. We reject it, the core takes an illegal-instruction trap and
# signals commit_kill for it -- which per spec also kills every *newer*
# offloaded instruction, i.e. the ISAX instruction right behind it that we may
# already have accepted speculatively. After the handler skips the faulting
# word, that ISAX instruction is re-fetched and must produce the correct result.
emit("# --- rejected illegal instruction: commit_kill + re-execution ---")
for i in range(3):
    x, y = 0xF00D0000 | i, 0x0BAD0000 | i
    li(A0, x)
    li(A1, y)
    emit(".word 0x0000007f          # illegal, not ours -> rejected -> commit_kill")
    emit(f".word 0x{enc_ell(A2, A0, A1):08x}   # killed, then re-executed after the trap")
    store_result(A2)
    golden.append(ell(x ^ y))

# --- 7. a loop: many offloads with control flow -------------------------
emit("# --- loop of offloads ---")
acc = 0
li(A4, 0)
li(T2, 16)
li(A0, 0x1)
emit("2:")
emit(f".word 0x{enc_ell(A2, A0, A0):08x}   # sparkle_ell a2, a0, a0")
emit(f".word 0x{enc_rcon(A3, A2, 0, 7):08x}   # sparkle_rcon a3, a2, imm=7")
emit("add x14, x14, x13")
emit("addi x10, x10, 1")
emit("addi x7, x7, -1")
emit("bnez x7, 2b")
store_result(A4)
v = 0x1
for _ in range(16):
    e = ell(v ^ v)
    r = (e ^ RCON[7]) & M
    acc = (acc + r) & M
    v = (v + 1) & M
golden.append(acc)

# --- 8. mixed random tail ------------------------------------------------
emit("# --- mixed tail ---")
for _ in range(12):
    k = rnd.randrange(4)
    if k == 0:
        case_ell(rnd.getrandbits(32), rnd.getrandbits(32))
    elif k == 1:
        case_rcon(rnd.getrandbits(32), rnd.randrange(8))
    else:
        case_enci(rnd.getrandbits(32), rnd.getrandbits(32),
                  rnd.randrange(8), k == 3)

asm = f"""\
# Generated by gen_test.py -- sparkle ISAX over CV-X-IF.
  .section .text
  .globl _start
_start:
  li x5, 0x{MMIO_BASE:08x}          # x5/t0 = MMIO result port
  li x2, 0x{STACK_TOP:08x}          # sp
  # trap handler: skip the faulting instruction and resume
  la x28, trap_handler
  csrw mtvec, x28            # direct mode (mode bits = 0)
  j past_handler
  .balign 128                # CV32E40X: mtvec.base is WARL, 128-byte aligned
trap_handler:
  csrr x28, mepc
  addi x28, x28, 4
  csrw mepc, x28
  mret
past_handler:
""" + "\n".join(body) + """
  # signal completion
  li x6, 1
  sw x6, 4(x5)
9:
  j 9b
"""

with open("test.S", "w") as f:
    f.write(asm)

write_golden(golden)
print(f"gen_test: {len(golden)} expected results, {len(body)} asm lines")
build_image(sys.argv[1], sys.argv[2], sys.argv[3], "gen_test")
