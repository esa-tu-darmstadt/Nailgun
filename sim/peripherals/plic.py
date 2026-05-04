import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, NextTimeStep, Lock

from memutil import MemView
from .base import SimPeripheral, PeripheralCtx


class _PlicImpl:
    # 7 x 32-bit registers in the cv32e40p driver layout: info_l, info_h,
    # edgelvl, prios, ie, thresh, id (claim/complete).
    REG_SIZE = 0x1C

    def __init__(self, dut, clk, plic_base):
        self.dut = dut
        self.clk = clk
        self.plic_base = plic_base
        # The dedicated PLIC port nets are 32-bit wide on the data path,
        # 16-bit on the address path, 4-bit on the byte-enable lane.
        self.dut.plic_we.setimmediatevalue(0)
        self.dut.plic_re.setimmediatevalue(0)
        self.dut.plic_be.setimmediatevalue(0)
        self.dut.plic_waddr.setimmediatevalue(0)
        self.dut.plic_raddr.setimmediatevalue(0)
        self.dut.plic_wdata.setimmediatevalue(0)
        # Tie the PLIC source lines low until something explicitly raises them;
        # otherwise they'd boot as 'x and propagate into the gateway logic.
        self.dut.ext_irq_src_i.setimmediatevalue(0)
        # Serialize concurrent read/write callbacks so the dedicated port strobes
        # don't overlap.
        self._lock = Lock("plic_port_lock")

    def _in_range(self, addr_begin, addr_end):
        return (addr_begin >= self.plic_base
                and addr_end <= self.plic_base + self.REG_SIZE)

    async def write(self, addr_begin, addr_end, word, wstrb):
        if not self._in_range(addr_begin, addr_end):
            return False
        offset = (addr_begin - self.plic_base) & 0xFFFF
        wdata = int.from_bytes(bytes(word), "little")
        be_int = int(wstrb)
        print(f"INFO: PLIC WRITE: addr=0x{addr_begin:08X} offset=0x{offset:04X} "
              f"wdata=0x{wdata:08X} be=0x{be_int:X}")
        await self._lock.acquire()
        try:
            await RisingEdge(self.clk)
            self.dut.plic_we.value = 1
            self.dut.plic_be.value = be_int
            self.dut.plic_waddr.value = offset
            self.dut.plic_wdata.value = wdata
            await RisingEdge(self.clk)
            self.dut.plic_we.value = 0
            self.dut.plic_be.value = 0
        finally:
            self._lock.release()
        return True

    async def read(self, addr_begin, addr_end, big_endian):
        if not self._in_range(addr_begin, addr_end):
            return None
        offset = (addr_begin - self.plic_base) & 0xFFFF
        await self._lock.acquire()
        try:
            await RisingEdge(self.clk)
            self.dut.plic_re.value = 1
            self.dut.plic_raddr.value = offset
            # On the next rising edge the PLIC's registered rdata flop captures
            # the value addressed by raddr (and the claim strobe fires for ID-reg
            # reads, clearing the gateway pending bit).
            await RisingEdge(self.clk)
            self.dut.plic_re.value = 0
            await ReadOnly()
            rdata = int(self.dut.plic_rdata.value)
            # Leave the read-only phase before returning so the caller can drive
            # its bus signals (e.g. AXI RDATA) without hitting "write during
            # read-only sync phase" errors.
            await NextTimeStep()
        finally:
            self._lock.release()
        print(f"INFO: PLIC READ:  addr=0x{addr_begin:08X} offset=0x{offset:04X} "
              f"rdata=0x{rdata:08X}")
        return rdata.to_bytes(4, "big" if big_endian else "little")


class Plic(SimPeripheral):
    name = "plic"

    def __init__(self, base, busidx):
        self.base = base
        self.busidx = busidx

    def probe(self, dut) -> bool:
        return hasattr(dut, "plic_we")

    def attach(self, ctx: PeripheralCtx) -> None:
        impl = _PlicImpl(ctx.dut, ctx.clk, self.base)
        ctx.add_memview(self.busidx, MemView(
            read_cb=impl.read,
            write_cb=impl.write,
            base_addr=self.base,
            length=_PlicImpl.REG_SIZE,
        ))
