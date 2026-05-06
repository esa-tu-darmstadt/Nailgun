import struct
import cocotb
from cocotb.triggers import FallingEdge

from mem.memutil import MemView
from .base import SimPeripheral, PeripheralCtx


# CLINT MMIO offsets relative to base.
_OFFS_MSIP        = 0x00000
_OFFS_MTIMECMP_LO = 0x04000
_OFFS_MTIMECMP_HI = 0x04004
_OFFS_MTIME_LO    = 0x0BFF8
_OFFS_MTIME_HI    = 0x0BFFC

# Range covered by the CLINT MemView. mtime[hi] is the last live register at
# 0x0BFFC; round up so the declared region cleanly spans the whole map.
CLINT_REGION_LEN = 0x10000


class _ClintImpl:
    def __init__(self, base):
        self.CLINT_BASE = base
        self.clint_mtime = 0
        self.clint_mtime_h = 0
        self.clint_mtimecmp = 0
        self.clint_mtimecmp_h = 0
        self.clint_software_irq = 0

    @cocotb.coroutine
    def run(self, dut, clk):
        while True:
            yield FallingEdge(clk)
            if ((self.clint_mtime_h << 32) + self.clint_mtime) >= ((self.clint_mtimecmp_h << 32) + self.clint_mtimecmp):
                dut.irq_i.value = (1 << 7)
            else:
                dut.irq_i.value = 0
            if self.clint_software_irq != 0:
                dut.irq_i.value += (1 << 3)
            new_mtime = ((self.clint_mtime_h << 32) + self.clint_mtime) + 1
            self.clint_mtime = new_mtime & 0xffffffff
            self.clint_mtime_h = (new_mtime >> 32) & 0xffffffff

    def check_clint_write(self, addr_begin, addr_end, word, wstrb):
        print(f"INFO: CLINT WRITE: addr: {addr_begin:0X} word: {struct.unpack('<I', word)[0]}")
        print(f"CURRENT VALUES: clint_mtime={self.clint_mtime} clint_mtime_h={self.clint_mtime_h} clint_mtimecmp={self.clint_mtimecmp} clint_mtimecmp_h={self.clint_mtimecmp_h}")
        word = struct.unpack('<I', word)[0]
        if addr_begin == self.CLINT_BASE + _OFFS_MSIP:
            self.clint_software_irq = word & 1
        if addr_begin == self.CLINT_BASE + _OFFS_MTIME_LO:
            assert wstrb == 0xF
            self.clint_mtime = word
            return True
        elif addr_begin == self.CLINT_BASE + _OFFS_MTIME_HI:
            assert wstrb == 0xF
            self.clint_mtime_h = word
            return True
        elif addr_begin == self.CLINT_BASE + _OFFS_MTIMECMP_LO:
            assert wstrb == 0xF
            self.clint_mtimecmp = word
            return True
        elif addr_begin == self.CLINT_BASE + _OFFS_MTIMECMP_HI:
            assert wstrb == 0xF
            self.clint_mtimecmp_h = word
            return True
        print(f"clint: Unexpected write to {addr_begin:0X} = {word:0X}")
        return False

    def check_clint_read(self, addr_begin, addr_end, big_endian):
        print(f"INFO: CLINT REAd: addr: {addr_begin:0X}")
        print(f"CURRENT VALUES: clint_mtime={self.clint_mtime} clint_mtime_h={self.clint_mtime_h} clint_mtimecmp={self.clint_mtimecmp} clint_mtimecmp_h={self.clint_mtimecmp_h}")
        if addr_begin == self.CLINT_BASE + _OFFS_MTIME_LO:
            return self.clint_mtime.to_bytes(4, byteorder="little")
        elif addr_begin == self.CLINT_BASE + _OFFS_MTIME_HI:
            return self.clint_mtime_h.to_bytes(4, byteorder="little")
        elif addr_begin == self.CLINT_BASE + _OFFS_MTIMECMP_LO:
            return self.clint_mtimecmp.to_bytes(4, byteorder="little")
        elif addr_begin == self.CLINT_BASE + _OFFS_MTIMECMP_HI:
            return self.clint_mtimecmp_h.to_bytes(4, byteorder="little")
        print(f"ERROR clint: Unexpected read to {addr_begin:0X}")
        return None


class Clint(SimPeripheral):
    name = "clint"

    def __init__(self, base, busidx):
        self.base = base
        self.busidx = busidx
        self._impl = None

    def probe(self, dut) -> bool:
        return hasattr(dut, "irq_i")

    def attach(self, ctx: PeripheralCtx) -> None:
        ctx.dut.irq_i.value = 0
        self._impl = _ClintImpl(self.base)
        ctx.start(self._impl.run(ctx.dut, ctx.clk))
        ctx.add_memview(self.busidx, MemView(
            read_cb=self._impl.check_clint_read,
            write_cb=self._impl.check_clint_write,
            base_addr=self.base,
            length=CLINT_REGION_LEN,
        ))
