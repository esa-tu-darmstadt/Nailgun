from mem.memutil import MemView
from .base import SimPeripheral, PeripheralCtx


class DebugPinPeripheral(SimPeripheral):
    """MMIO write at `base_addr` is forwarded to `dut.debugState`.

    Skipped (probe returns False) on DUTs that don't expose `debugState`;
    those writes then fall through to whichever memview claims the address
    (typically the test_control bytearray).
    """
    name = "debug_pin"

    def __init__(self, base_addr: int, busidx):
        self.base_addr = base_addr
        self.busidx = busidx
        self._dut = None

    def probe(self, dut) -> bool:
        try:
            _ = dut.debugState
            return True
        except Exception:
            return False

    def attach(self, ctx: PeripheralCtx) -> None:
        self._dut = ctx.dut
        ctx.add_memview(self.busidx, MemView(
            read_cb=self._read,
            write_cb=self._write,
            base_addr=self.base_addr,
            length=4,
        ))

    def _write(self, addr_begin, addr_end, word, wstrb):
        self._dut.debugState.value = word
        return True

    def _read(self, addr_begin, addr_end, big_endian):
        return bytes([0] * (addr_end - addr_begin))
