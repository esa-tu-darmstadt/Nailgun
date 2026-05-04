import cocotb
from cocotb.triggers import RisingEdge

from .base import SimPeripheral, PeripheralCtx


class DummyIrqTrigger(SimPeripheral):
    name = "dummy_irq_trigger"

    def __init__(self, sequence=(1, 2, 4, 8), intial_wait : int = 200000, gap_cycles: int = 5000):
        self._sequence = tuple(sequence)
        self._gap_cycles = gap_cycles
        self._intial_wait = intial_wait

    def probe(self, dut) -> bool:
        return hasattr(dut, "ext_irq_src_i")

    def attach(self, ctx: PeripheralCtx) -> None:
        ctx.start(self._run(ctx.dut, ctx.clk))

    async def _run(self, dut, clk):
        for _ in range(self._intial_wait):
            await RisingEdge(clk)
        for value in self._sequence:
            for _ in range(self._gap_cycles):
                await RisingEdge(clk)
            dut.ext_irq_src_i.value = value
            print(f"INFO: DUMMY_IRQ: ext_irq_src_i <= 0x{value:02X}")
