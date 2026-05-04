import array
import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly
from cocotb.types import LogicArray

from memutil import HierarchicalMemView, word_range, word_to_bytes
from .base import SimPeripheral, PeripheralCtx


# The HWSchedulerPlugin context port is LSB-first, like every other bus model in
# nailgun (see the endianness note at the top of mem/memutil.py).
_BIG_ENDIAN = False


class _SRAMSlave:
    """SRAM-like bus slave hard-wired to NaxRiscv's HWSchedulerPlugin
    context-switch port. Inlined here because it has only ever served the
    ctx-iface peripheral."""

    def __init__(self, dut, clk, memview):
        self.dut = dut
        self.clk = clk
        self.memview = memview
        cocotb.start_soon(self._process())

    async def _process(self):
        clock_re = RisingEdge(self.clk)
        clock_fe = FallingEdge(self.clk)

        await clock_fe
        self.dut.HWSchedulerPlugin_io_mem_write_ready.value = True

        while True:
            while True:
                await clock_re
                await ReadOnly()
                if self.dut.HWSchedulerPlugin_io_mem_write_valid.value:
                    break

            _st = int(self.dut.HWSchedulerPlugin_io_mem_write_payload_addr)
            num_bytes = len(self.dut.HWSchedulerPlugin_io_mem_write_payload_data.value) >> 3  # / 8
            _end = _st + num_bytes
            word = self.dut.HWSchedulerPlugin_io_mem_write_payload_data.value
            wstrb = LogicArray("1" * num_bytes, word_range(num_bytes, _BIG_ENDIAN))

            # cocotb-1 handed out MSB-first BinaryValues, so .buff had to be
            # reversed to get LSB-first byte lanes; word_to_bytes yields that
            # order directly.
            word = array.array('B', word_to_bytes(word, _BIG_ENDIAN))

            await self.memview.awrite(_st, _end, word, wstrb)


class CtxIface(SimPeripheral):
    """Tiny SRAM-like context-switch state interface (NaxRiscv HW scheduler).

    Mirrors only `ctx.data_memview` into its private bus — narrow scope is
    intentional. Probes via the `HWSchedulerPlugin_io_mem_write_ready` signal.
    """
    name = "ctx_iface"

    def probe(self, dut) -> bool:
        return hasattr(dut, "HWSchedulerPlugin_io_mem_write_ready")

    def attach(self, ctx: PeripheralCtx) -> None:
        ctx.dut.HWSchedulerPlugin_io_mem_write_ready.value = False
        slave = _SRAMSlave(ctx.dut, ctx.clk, HierarchicalMemView([]))
        slave.memview.children.append(ctx.data_memview)
