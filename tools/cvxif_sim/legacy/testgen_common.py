"""Memory map and image emission shared by the CV-X-IF test generators.

The defaults describe CV32E40X's harness (tb_e40x.sv): a 32-bit unified memory
starting at 0, the program linked at 0x80 (= boot_addr), MMIO in the high region.
tools/cvxif_sim/run_cva6.sh overrides them through the environment for CVA6,
which boots at 0x8000_0000 -- where CV32E40X puts its MMIO -- and hangs off a
64-bit AXI memory, so both the link address and the hex word width change.

Every value is read from the environment so that one generator serves both
harnesses and the golden model stays in a single place.
"""
import os
import subprocess


def _env(name, default):
    return int(os.environ.get(name, default), 0)


TEXT_BASE   = _env("CVXIF_TEXT_BASE",   "0x80")         # link address
MEM_BASE    = _env("CVXIF_MEM_BASE",    "0")            # address of mem.hex word 0
MMIO_BASE   = _env("CVXIF_MMIO_BASE",   "0x80000000")   # result / done / trace
STACK_TOP   = _env("CVXIF_STACK_TOP",   "0x8000")
RESULT_BASE = _env("CVXIF_RESULT_BASE", "0x1000")       # for RESULT_IN_MEM tests
HEX_WIDTH   = _env("CVXIF_HEX_WIDTH",   "32")


def write_golden(golden, result_in_mem=False):
    """Emit golden.svh: the expected result stream for the testbench."""
    with open("golden.svh", "w") as f:
        f.write(f"localparam bit RESULT_IN_MEM = 1'b{int(result_in_mem)};\n")
        f.write(f"localparam logic [31:0] RESULT_BASE = 32'h{RESULT_BASE:08x};\n")
        f.write(f"localparam int N_GOLDEN = {len(golden)};\n")
        f.write(f"localparam logic [31:0] GOLDEN [0:{len(golden) - 1}] = '{{\n")
        for i in range(0, len(golden), 4):
            row = ", ".join(f"32'h{v:08x}" for v in golden[i:i + 4])
            f.write(f"  {row}" + ("," if i + 4 < len(golden) else "") + "\n")
        f.write("};\n")


def build_image(clang, lld, objcopy, tag, march="rv32im_zicsr"):
    """Assemble/link test.S and write mem.hex at the configured width."""
    subprocess.run([clang, "--target=riscv32-unknown-elf", f"-march={march}",
                    "-mabi=ilp32", "-nostdlib", "-c", "test.S", "-o", "test.o"],
                   check=True)
    subprocess.run([lld, "-m", "elf32lriscv", f"--Ttext=0x{TEXT_BASE:x}",
                    "-e", "_start", "test.o", "-o", "test.elf"], check=True)
    subprocess.run([objcopy, "-O", "binary", "test.elf", "test.bin"], check=True)

    data = open("test.bin", "rb").read()
    # Word i of mem.hex is the word at MEM_BASE + 4*i, so zero-fill the gap
    # between the memory base and the link address (empty when they coincide).
    pad_words = (TEXT_BASE - MEM_BASE) // 4
    assert pad_words >= 0, "CVXIF_MEM_BASE must not be above CVXIF_TEXT_BASE"
    words = [0] * pad_words
    for i in range(0, len(data), 4):
        words.append(int.from_bytes(data[i:i + 4].ljust(4, b"\0"), "little"))

    with open("mem.hex", "w") as f:
        if HEX_WIDTH == 64:
            # $readmemh into a 64-bit array: one line per doubleword, low word
            # last, so the byte order matches the 32-bit case.
            if len(words) % 2:
                words.append(0)
            for i in range(0, len(words), 2):
                f.write(f"{words[i + 1]:08x}{words[i]:08x}\n")
        else:
            for w in words:
                f.write(f"{w:08x}\n")
    print(f"{tag}: image {len(data)} bytes -> mem.hex ({HEX_WIDTH}-bit words)")
