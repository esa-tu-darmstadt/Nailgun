# Based on tapasco-pe-tb
import os
import struct
import cocotb
from cocotb.clock import Clock
from cocotb.result import TestFailure, TestSuccess
from cocotb.triggers import Timer, RisingEdge, FallingEdge, Event, with_timeout, First
from amba import AXI4Slave
from bram import BRAMSlave
from memutil import MemView, HierarchicalMemView, BytearrayMemView

CLK_PERIOD = 1 # Length of a clock period in ns
TIMEOUT_PERIODS = 1e6 # Number of clock periods until timeout

@cocotb.coroutine
def clock_print(clk):
    while True:
        yield RisingEdge(clk)
#        print ("-", flush=True)

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
    # dut._discover_all()  would allow signals to be searched via the dut._sub_handles dict, but calling it causes issues with Verilator.
    # -> In short: some query methods of Verilator will return ports from inner modules rather than from the TOP pseudo-module, causing any values to be overwritten by the simulator.
    # -> https://github.com/verilator/verilator/issues/3919
    clk = dut.clk
    rst = dut.rst
    trap = dut.trap if ("HAS_TRAP_PIN" in os.environ) else None

    cocotb.start_soon(Clock(clk, CLK_PERIOD, units='ns').start())
    cocotb.start_soon(clock_print(clk))

    NUM_BUSSI = int(os.environ["NUM_BUSSI"])
    memsi = []
    for i_bussi in range(NUM_BUSSI):
        bussi_type = os.environ["BUSSI%d_TYPE" % i_bussi]
        bussi_signame = os.environ["BUSSI%d_SIGNAME" % i_bussi]
        match bussi_type:
            case "AXI4":
                memsi.append(AXI4Slave(dut, bussi_signame, clk, HierarchicalMemView([]), big_endian=False))
            case "BRAM":
                memsi.append(BRAMSlave(dut, bussi_signame, clk, HierarchicalMemView([]), big_endian=False))
            case _:
                raise ConfigException("Unknown BusSI type " + bussi_type)

    #NOTE: Expects that IMEM and DMEM are not the same memories (i.e. on a different bus or with disjoint address ranges)

    IMEM_BUSIDX=int(os.environ["IMEM_BUSIDX"])
    IMEM_BASE=int(os.environ["IMEM_BASE"], 16)
    EXCEPTION_BASE = int(os.environ["EXCEPTION_BASE"], 16) if ("EXCEPTION_BASE" in os.environ) else None

    DMEM_BUSIDX=int(os.environ["DMEM_BUSIDX"])
    DMEM_BASE=int(os.environ["DMEM_BASE"], 16)
    DMEM_SIZE=int(os.environ["DMEM_SIZE"], 16)
    DMEM_RESULTS_OFFS=int(os.environ["DMEM_RESULTS_OFFS"], 16)

    CTRL_BUSIDX=int(os.environ["CTRL_BUSIDX"])
    CTRL_BASE=int(os.environ["CTRL_BASE"], 16)


    TESTPROG = os.environ["TESTPROG"]
    EXPECTED = os.environ["EXPECTED"]

    with open(TESTPROG+"_instr.bin", "rb") as f:
        instr_mem = bytearray(f.read())
        instr_mem += bytearray([0] * 4096)
    with open(TESTPROG+"_data.bin", "rb") as f:
        data_mem = bytearray(f.read())
        if len(data_mem) > DMEM_SIZE:
            raise InputBinaryException("Data file (0x%08x bytes) larger than DMEM_SIZE (0x%08x bytes)" % (len(data_mem), DMEM_SIZE))
        data_mem += bytearray([0] * (DMEM_SIZE - len(data_mem)))
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
    if len(data_mem) - DMEM_RESULTS_OFFS < len(expected_data):
        raise InputBinaryException("Expected results file is larger than the physical data memory section")

    event_irq = Event('core_irq')

    def check_instr_read(addr_begin, addr_end, big_endian):
#        if addr_begin >= IMEM_BASE and addr_end < (IMEM_BASE + len(instr_mem)):
#            print("instruction read %08x" % addr_begin)
        if (EXCEPTION_BASE is not None) and addr_begin == EXCEPTION_BASE:
            raise CoreExceptionException("The core fetched the exception handler address 0x%08x" % addr_begin)
        return None

    def check_data_read(addr_begin, addr_end, big_endian):
#        if addr_begin >= DMEM_BASE and addr_end < (DMEM_BASE + DMEM_SIZE):
#            print("data read %08x" % addr_begin)
        return None
    def check_data_write(addr_begin, addr_end, word, wstrb):
        return False

    def check_ctrl_write(addr_begin, addr_end, word, wstrb):
        if addr_begin == CTRL_BASE: # Assuming little endian
            if word[0] != 0 and wstrb[0] != 0:
                # Handle IRQ write
                event_irq.set()
                return True
 #           print("check_ctrl_write: Unexpected write to IRQ")
            return False
        return False
    def check_ctrl_read(addr_begin, addr_end, big_endian):
        # For now, always return 0 for read access on the CTRL memory space.
        if addr_begin >= CTRL_BASE and addr_end <= CTRL_BASE+16:
            return bytes([0] * (addr_end - addr_begin))
        return None

    instr_memview = BytearrayMemView(instr_mem, 0, len(instr_mem), IMEM_BASE, read_cb=check_instr_read)
    memsi[IMEM_BUSIDX].memview.children.append(instr_memview)

    data_memview = BytearrayMemView(data_mem, 0, len(data_mem), DMEM_BASE, read_cb=check_data_read, write_cb=check_data_write)
    memsi[DMEM_BUSIDX].memview.children.append(data_memview)

    ctrl_memview = MemView(read_cb=check_ctrl_read, write_cb=check_ctrl_write)
    memsi[CTRL_BUSIDX].memview.children.append(ctrl_memview)

#    print("Setting rst")

    rst.value = 1
    await Timer(CLK_PERIOD * 10, units='ns')
    rst.value = 0

#    print("Reset done")

    # Make sure the trap output stabilizes before sampling it.
    await Timer(CLK_PERIOD * 5, units='ns')

    core_done_trigger = event_irq.wait()
    if trap is not None:
        if trap.value == 1:
            raise CoreExceptionException("The core set its trap pin")
        core_done_trigger = First(core_done_trigger, RisingEdge(trap))

    await with_timeout(core_done_trigger, TIMEOUT_PERIODS * CLK_PERIOD, timeout_unit='ns')

    if (trap is not None) and trap.value == 1:
        raise CoreExceptionException("The core set its trap pin")

#    print("expected_data: " + str(expected_data))
    for i in range(0, len(expected_data), 4):
        got = data_mem[DMEM_RESULTS_OFFS+i:DMEM_RESULTS_OFFS+i+4]
        expected = expected_data[i:i+4]
#        print("got: 0x" + str(got.hex()) + ", expected: 0x" + str(expected.hex()))
        if got != expected:
            with open("outputs_got.txt", "w") as f:
                dump_32bithex(f, data_mem[DMEM_RESULTS_OFFS:DMEM_RESULTS_OFFS+len(expected_data)])
            with open("outputs_expected.txt", "w") as f:
                dump_32bithex(f, expected_data)
            raise ResultMismatchException("At 0x%X: Got 0x%08x, expected 0x%08x. Wrote complete results to outputs_got.txt and outputs_expected.txt." % (i, struct.unpack('<L', got)[0], struct.unpack('<L', expected)[0]))

