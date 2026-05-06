import struct

from mem.memutil import BytearrayMemView, MemView
from testutil import dump_32bithex, get_envarg_or

from .base import SimPeripheral, PeripheralCtx


class ResultMismatchException(Exception):
    pass


class InputBinaryException(Exception):
    pass


class TestControlPeripheral(SimPeripheral):
    """Test-harness CTRL bus owner + post-run result check.

    Two responsibilities:
      * Test-done IRQ: writes to `CTRL_BASE` or `CTRL_BASE+0x4000` set
        `ctx.test_done_event`, which the harness awaits.
      * Result-data scratchpad: any other write inside the CTRL region is
        absorbed by a passive bytearray, which is also where ELF programs
        normally place `_test_resdata`.

    The debug-pin (`+4`) and UART byte sink (`+8`) live in their own
    peripherals (`DebugPinPeripheral`, `UartPrinterPeripheral`); their
    smaller declared regions take dispatch priority over this peripheral's
    big bytearray view via `HierarchicalMemView`.

    `do_result_check()` is called by the harness once the test-done trigger
    fires; it reads the resdata back via the right memview and compares
    against the expected file.
    """
    name = "test_control"

    def __init__(self, env):
        self.env = env
        self.ctrl_busidx = [int(s) for s in env["CTRL_BUSIDX"].split(',')]
        self.ctrl_base = int(env["CTRL_BASE"], 16)
        self.ctrl_results_offs = int(env["CTRL_RESULTS_OFFS"], 16) if "CTRL_RESULTS_OFFS" in env else 0x20000

        # CTRL bytearray upper bound — preserve the original IMEM_SIZE-derived
        # heuristic so auto_resize behavior matches.
        imem_base = int(env["IMEM_BASE"], 16)
        dmem_base = int(env["DMEM_BASE"], 16)
        size = 0x10000000
        if dmem_base > imem_base:
            size = dmem_base - imem_base
        if self.ctrl_base > imem_base:
            size = min(size, self.ctrl_base - imem_base)
        self.ctrl_results_size = size

        expected_path = get_envarg_or(env, "EXPECTED", None)
        self.expected_data = bytearray()
        if expected_path is None:
            pass
        elif expected_path.endswith(".bin"):
            with open(expected_path, "rb") as f:
                self.expected_data = bytearray(f.read())
                fill_to_4align = ((len(self.expected_data) + 3) & ~3) - len(self.expected_data)
                self.expected_data += bytearray([0] * fill_to_4align)
        else:
            with open(expected_path, "r") as f:
                for line in f:
                    line_lstrip = line.lstrip()
                    if len(line_lstrip) != 0 and line_lstrip[0] != '#':
                        self.expected_data += bytearray(int(line_lstrip, 16).to_bytes(4, byteorder='little'))

        self._ctx: PeripheralCtx | None = None
        self._dut = None
        self._ctrl_mem = bytearray()
        self._ctrl_memview = None

    def probe(self, dut) -> bool:
        return True

    def attach(self, ctx: PeripheralCtx) -> None:
        self._ctx = ctx
        self._dut = ctx.dut
        self._ctrl_memview = BytearrayMemView(
            self._ctrl_mem, 0, self.ctrl_results_size, self.ctrl_base,
            read_cb=self._check_ctrl_read, write_cb=self._check_ctrl_write,
            auto_resize=True,
        )
        ctx.add_memview(self.ctrl_busidx, self._ctrl_memview)

    def _resolve_resdata_target(self) -> tuple[MemView, int]:
        """Pick the (memview, address) pair to read the result from.

        If the ELF defined `_test_resdata`, scan every bus's memview children
        for one that fully claims the result range — works whether resdata
        landed in the CTRL bytearray, DMEM, or some other peripheral's
        region. Without an ELF symbol, fall back to the CTRL bytearray at
        the configured default offset.
        """
        rd_loc = self._ctx.resdata_location
        if rd_loc is None:
            rd_loc = self.ctrl_base + self.ctrl_results_offs
            if rd_loc + len(self.expected_data) > self.ctrl_base + self.ctrl_results_size:
                raise InputBinaryException("Expected results file is larger than the CTRL fallback region")
            return self._ctrl_memview, rd_loc
        end = rd_loc + len(self.expected_data)
        for bus in self._ctx.memsi:
            for child in bus.memview.children:
                if isinstance(child, MemView) and child._claims(rd_loc, end) is True:
                    return child, rd_loc
        raise InputBinaryException(
            "_test_resdata at 0x%X (+%d bytes) doesn't fit in any registered memview" % (rd_loc, len(self.expected_data)))

    def _check_ctrl_write(self, addr_begin, addr_end, word, wstrb):
        if addr_begin == self.ctrl_base or addr_begin == self.ctrl_base + 0x4000:
            # Assuming little endian
            if word[0] != 0 and wstrb[0] != 0:
                self._ctx.test_done_event.set()
                return True
            print("test_control: Unexpected write to IRQ")
            return False
        return False

    def _check_ctrl_read(self, addr_begin, addr_end, big_endian):
        # IRQ register reads return 0; everything else falls through to the
        # bytearray (including resdata).
        if addr_begin >= self.ctrl_base and addr_end <= self.ctrl_base + 4:
            return bytes([0] * (addr_end - addr_begin))
        return None

    def do_result_check(self) -> None:
        resdata_memview, resdata_location = self._resolve_resdata_target()
        self._dut._log.info("expected_data: " + str(self.expected_data))
        got_all = bytearray()
        mismatch_exception = None
        for i in range(0, len(self.expected_data), 4):
            got = resdata_memview.read(resdata_location+i, resdata_location+i+4, 32).buff
            got_all += got
            expected = self.expected_data[i:i+4]
            self._dut._log.info("got: 0x%s, expected: 0x%s%s" % (str(got.hex()), str(expected.hex()), " (ERR)" if (got != expected) else ""))
            if mismatch_exception is None and got != expected:
                mismatch_exception = ResultMismatchException(
                    "At 0x%X: Got 0x%08x, expected 0x%08x. Wrote complete results to outputs_got.txt and outputs_expected.txt." % (
                        i, struct.unpack('<L', got)[0], struct.unpack('<L', expected)[0]))
        with open("outputs_got.txt", "w") as f:
            dump_32bithex(f, got_all)
        with open("outputs_expected.txt", "w") as f:
            dump_32bithex(f, self.expected_data)
        if mismatch_exception is not None:
            raise mismatch_exception
