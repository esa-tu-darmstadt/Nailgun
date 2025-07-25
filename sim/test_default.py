# Based on tapasco-pe-tb
import os
import struct
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, Event, with_timeout, First
from capstone import *
from amba import AXI4Slave
from bram import BRAMSlave
from memutil import MemView, HierarchicalMemView, BytearrayMemView
from TestLoader import TestLoader

import clint
import disas
from UARTPrinter import *

CLK_PERIOD = 1 # Length of a clock period in ns
TIMEOUT_PERIODS = int(cocotb.plusargs["CYCLE_TIMEOUT"]) # Number of clock periods until timeout
PRINT_CLK = int(cocotb.plusargs["PRINT_CLK"]) > 0
PRINT_IMEM = int(cocotb.plusargs["PRINT_IMEM"]) > 0
PRINT_DMEM = int(cocotb.plusargs["PRINT_DMEM"]) > 0
PRINT_BRAM = int(cocotb.plusargs["PRINT_BRAM"]) > 0
PRINT_AXI = int(cocotb.plusargs["PRINT_AXI"]) > 0
RESDATA_OFFSET = 0x1000

@cocotb.coroutine
def clock_print(clk):
    while True:
        yield RisingEdge(clk)
        print ("-", flush=True)

class ConfigException(Exception):
    pass
class InputBinaryException(Exception):
    pass
class CoreExceptionException(Exception):
    pass
class ResultMismatchException(Exception):
    pass

def dump_32bithex(f, data):
    if (len(data) & 3) != 0: #Is not 4-aligned
        fill_to_4align = ((len(data) + 3) & ~3) - len(data)
        data = bytearray(data) + bytearray([0] * fill_to_4align)
    for i in range(0, len(data), 4):
        word = data[i:i+4]
        f.write('%02x%02x%02x%02x\n' % (word[3], word[2], word[1], word[0]))

@cocotb.test()
async def run_test(dut):
    # GLS hacks
    try:
        dut.DFT_sdi_1.value = False
        # dut.top_INST.DFT_sen.value = False
        dut.test_mode.value = False
        dut.shift_enable.value = False
    except:
        pass

    # dut._discover_all()  would allow signals to be searched via the dut._sub_handles dict, but calling it causes issues with Verilator.
    # -> In short: some query methods of Verilator will return ports from inner modules rather than from the TOP pseudo-module, causing any values to be overwritten by the simulator.
    # -> https://github.com/verilator/verilator/issues/3919
    clk = dut.clk
    rst = dut.rst
    trap = dut.trap if ("HAS_TRAP_PIN" in cocotb.plusargs) else None

    CORE_NAME = cocotb.plusargs["CORE_NAME"]
    ISAX_YAML = cocotb.plusargs["ISAX_YAML"]

    # Register custom instructions to our disassembler
    disas.register_isax_yaml(ISAX_YAML)
    # Optionally you can manually add patterns like so:
    # disas.register_isax_patterns({
    #     'HW_CTX_LOAD':  "0000000----------000-----0001011",
    #     'HW_CTX_STORE_ONLY_SWITCH_BACK': "0000000----------101-----0001011",
    #     'HW_SCHED_SET_FIRST_CTX_ID': "0000000----------001-----0001011",
    #     'HW_SCHED_ADD_RDY_TASK': "0000000----------011-----0001011",
    #     'HW_SCHED_RM_RDY_TASK': "0000000----------100-----0001011",
    #     'HW_SCHED_NEXT_TASK': "0000000----------111-----0001011",
    # })

    cocotb.start_soon(Clock(clk, CLK_PERIOD, units='ns').start())
    if PRINT_CLK:
        cocotb.start_soon(clock_print(clk))

    NUM_BUSSI = int(cocotb.plusargs["NUM_BUSSI"])
    memsi = []
    for i_bussi in range(NUM_BUSSI):
        bussi_type = cocotb.plusargs["BUSSI%d_TYPE" % i_bussi]
        bussi_signame = cocotb.plusargs["BUSSI%d_SIGNAME" % i_bussi]
        match bussi_type:
            case "AXI4":
                memsi.append(AXI4Slave(dut, bussi_signame, clk, HierarchicalMemView([]), big_endian=False, enable_prints=PRINT_AXI))
            case "BRAM":
                memsi.append(BRAMSlave(dut, bussi_signame, clk, HierarchicalMemView([]), big_endian=False, enable_prints=PRINT_BRAM))
            case _:
                raise ConfigException("Unknown BusSI type " + bussi_type)

    #NOTE: Expects that IMEM and DMEM are not the same memories (i.e. on a different bus or with disjoint address ranges)

    IMEM_BUSIDX=int(cocotb.plusargs["IMEM_BUSIDX"])
    IMEM_BASE=int(cocotb.plusargs["IMEM_BASE"], 16)
    EXCEPTION_BASE = int(cocotb.plusargs["EXCEPTION_BASE"], 16) if ("EXCEPTION_BASE" in cocotb.plusargs) else None

    DMEM_BUSIDX=int(cocotb.plusargs["DMEM_BUSIDX"])
    DMEM_BASE=int(cocotb.plusargs["DMEM_BASE"], 16)
    DMEM_SIZE=int(cocotb.plusargs["DMEM_SIZE"], 16)

    CTRL_BUSIDX=int(cocotb.plusargs["CTRL_BUSIDX"])
    CTRL_BASE=int(cocotb.plusargs["CTRL_BASE"], 16)

    IMEM_SIZE = 0x10000000
    if DMEM_BASE > IMEM_BASE:
        IMEM_SIZE = DMEM_BASE - IMEM_BASE
    if CTRL_BASE > IMEM_BASE:
        IMEM_SIZE = min(IMEM_SIZE, CTRL_BASE - IMEM_BASE)

    TESTPROG = cocotb.plusargs["TESTPROG"]
    EXPECTED = cocotb.plusargs["EXPECTED"]

    uart_printer = UARTPrinter()
    instr_mem = bytearray()
    if EXPECTED.endswith(".bin"):
        with open(EXPECTED, "rb") as f:
            expected_data = bytearray(f.read())
            fill_to_4align = ((len(expected_data) + 3) & ~3) - len(expected_data)
            expected_data += bytearray([0] * fill_to_4align)
    else:
        with open(EXPECTED, "r") as f:
            expected_data = bytearray()
            for line in f:
                line_lstrip = line.lstrip()
                if len(line_lstrip) != 0 and line_lstrip[0] != '#':
                    expected_data += bytearray(int(line_lstrip, 16).to_bytes(4, byteorder='little'))

    event_irq = Event('core_irq')

    testStarted = False
    allowSpeculativeReads = True if ("ALLOW_SPECULATIVE_READS" in cocotb.plusargs) else False

    def check_instr_read(addr_begin, addr_end, big_endian):
        if PRINT_IMEM and testStarted and addr_begin >= IMEM_BASE and addr_end <= (IMEM_BASE + len(instr_mem)):
            print("instruction read %08x" % addr_begin)
            # Initialize the disassembler for RISC-V (32-bit)
            instr_data = instr_mem[addr_begin - IMEM_BASE:addr_end - IMEM_BASE]
            for i in range(0, len(instr_data), 4):
                assembly = disas.disassemble(instr_data[i:i+4])
                for idx, asm in enumerate(assembly):
                    print(f"Address: 0x{addr_begin + i + idx * int(4 / len(assembly)):08x}, Instruction: {asm}")

        if (EXCEPTION_BASE is not None) and addr_begin == EXCEPTION_BASE:
            raise CoreExceptionException("The core fetched the exception handler address 0x%08x" % addr_begin)
        return None

    past_speculative_reads = set()

    def check_data_read(addr_begin, addr_end, big_endian):
        if testStarted:
            if addr_begin >= DMEM_BASE and addr_end <= (DMEM_BASE + DMEM_SIZE):
                if PRINT_DMEM:
                    print("data read %08x" % addr_begin)
            elif allowSpeculativeReads:
                print("WARNING: unmapped (speculative?) read at: %08x" % addr_begin)
                past_speculative_reads.add(addr_begin)
                return bytes([0] * (addr_end-addr_begin))
        return None
    def check_data_write(addr_begin, addr_end, word, wstrb):
        if testStarted:
            if addr_begin >= DMEM_BASE and addr_end <= (DMEM_BASE + DMEM_SIZE):
                if PRINT_DMEM:
                    print("data write %08x: %s strb %s" % (addr_begin, ' '.join([('%02x' % _byte) for _byte in word]), str(wstrb)))
            elif addr_begin in past_speculative_reads:
                past_speculative_reads.remove(addr_begin)
                print("WARNING: allowing write-back of previously speculatively unmapped read: %08x - %08X" % (addr_begin, addr_end))
                return True
        return False

    def check_ctrl_write(addr_begin, addr_end, word, wstrb):
        if addr_begin == CTRL_BASE: # Assuming little endian
            if word[0] != 0 and wstrb[0] != 0:
                # Handle IRQ write
                event_irq.set()
                return True
            print("check_ctrl_write: Unexpected write to IRQ")
        elif addr_begin == CTRL_BASE + 4:
            try:
                # Set debug pin!
                dut.debugState.value = word
            except:
                pass
            return True
        elif addr_begin == CTRL_BASE + 8:
            if word[0] != 0 and wstrb[0] != 0:
                for i in range(len(wstrb.binstr)):  # For a 32-bit word (4 bytes)
                    if wstrb[i] != 0:
                        uart_printer.write_byte(word[i])
                return True

        return False
    def check_ctrl_read(addr_begin, addr_end, big_endian):
        # For now, always return 0 for read access on the CTRL memory space.
        if addr_begin >= CTRL_BASE and addr_end <= CTRL_BASE+8:
            return bytes([0] * (addr_end - addr_begin))
        return None

    instr_mem = bytearray()
    instr_memview = BytearrayMemView(instr_mem, 0, IMEM_SIZE, IMEM_BASE, read_cb=check_instr_read, auto_resize=True)
    memsi[IMEM_BUSIDX].memview.children.append(instr_memview)

    data_mem = bytearray(DMEM_SIZE)
    data_memview = BytearrayMemView(data_mem, 0, DMEM_SIZE, DMEM_BASE, read_cb=check_data_read, write_cb=check_data_write)
    memsi[DMEM_BUSIDX].memview.children.append(data_memview)

    resdata_mem = bytearray()
    ctrl_memview = BytearrayMemView(resdata_mem, 0, IMEM_SIZE, CTRL_BASE, read_cb=check_ctrl_read, write_cb=check_ctrl_write, auto_resize=True)
    memsi[CTRL_BUSIDX].memview.children.append(ctrl_memview)

    # Create and register a CLINT
    CLINT_BASE = int(cocotb.plusargs["CLINT_BASE"], 16) if ("CLINT_BASE" in cocotb.plusargs) else 0x40000000
    CLINT_BUSIDX = int(cocotb.plusargs["CLINT_BUSIDX"]) if ("CLINT_BUSIDX" in cocotb.plusargs) else DMEM_BUSIDX
    clint_memview = clint.start_clint(dut, clk, CLINT_BASE, CLINT_BUSIDX)
    if clint_memview:
        memsi[CLINT_BUSIDX].memview.children.append(clint_memview)

    if CORE_NAME == "NaxRiscv":
        from NaxWhiteBox import NaxWhiteBox
        naxWhiteBox = NaxWhiteBox(dut, CLK_PERIOD,
                                  disasm=disas.disassemble,
                                  defines_path=os.path.abspath(os.path.join("..", CORE_NAME, "nax.h")),
                                  gem5_output_path="gem5_output.log")
        cocotb.start_soon(naxWhiteBox.run(clk))

    elfLoader = TestLoader(dut._log, [instr_memview, data_memview], [(IMEM_BASE,IMEM_BASE+IMEM_SIZE),(DMEM_BASE,DMEM_BASE+DMEM_SIZE)])
    elfLoader.load_test_case(TESTPROG+".elf")

    testStarted = True

    dut._log.info("Setting rst")

    rst.value = 1
    await Timer(CLK_PERIOD * 10, units='ns')
    rst.value = 0

    dut._log.info("Reset done")

    # Make sure the trap output stabilizes before sampling it.
    await Timer(CLK_PERIOD * 5, units='ns')

    core_done_trigger = event_irq.wait()
    if trap is not None:
        if trap.value == 1:
            raise CoreExceptionException("The core set its trap pin")
        core_done_trigger = First(core_done_trigger, RisingEdge(trap))

    if TIMEOUT_PERIODS > 0:
        await with_timeout(core_done_trigger, TIMEOUT_PERIODS * CLK_PERIOD, timeout_unit='ns')
    else:
        await core_done_trigger

    uart_printer.flush()

    if (trap is not None) and trap.value == 1:
        raise CoreExceptionException("The core set its trap pin")

    dut._log.info("expected_data: " + str(expected_data))
    for i in range(0, len(expected_data), 4):
        got = resdata_mem[RESDATA_OFFSET+i:RESDATA_OFFSET+i+4]
        expected = expected_data[i:i+4]
        dut._log.info("got: 0x" + str(got.hex()) + ", expected: 0x" + str(expected.hex()))
        if got != expected:
            with open("outputs_got.txt", "w") as f:
                dump_32bithex(f, resdata_mem[RESDATA_OFFSET:RESDATA_OFFSET+len(expected_data)])
            with open("outputs_expected.txt", "w") as f:
                dump_32bithex(f, expected_data)
            raise ResultMismatchException("At 0x%X: Got 0x%08x, expected 0x%08x. Wrote complete results to outputs_got.txt and outputs_expected.txt." % (i, struct.unpack('<L', got)[0], struct.unpack('<L', expected)[0]))
