import cocotb
from cocotb.triggers import RisingEdge

from .base import SimPeripheral, PeripheralCtx


class ClockPrintPeripheral(SimPeripheral):
    """Prints `-` on every rising edge of the clock — visible heartbeat for
    long simulations. Probe returns False unless the constructor was passed
    a truthy `print_clk`, so the peripheral attaches only when the env opts
    in (typically via `PRINT_CLK`).
    """
    name = "clock_print"

    def __init__(self, print_clk: bool):
        self.print_clk = print_clk

    def probe(self, dut) -> bool:
        return self.print_clk

    def attach(self, ctx: PeripheralCtx) -> None:
        cocotb.start_soon(self._print_clock(ctx.clk))

    @cocotb.coroutine
    async def _print_clock(self, clk):
        while True:
            await RisingEdge(clk)
            print("-", flush=True)
