import cocotb
from cocotb.triggers import FallingEdge

from .clint import Clint
from .base import PeripheralCtx


# NaxRiscv exception code that triggers the auto-reset (mcause for the
# context-switch trap path that previously gated `ABUSE_CLINT`).
_NAX_CTXSWITCH_MCAUSE = 0x80000007


class NaxClint(Clint):
    """CLINT plus NaxRiscv-specific mtime auto-reset on context switch.

    The auto-reset taps NaxRiscv-internal signals
    (`top_INST.NaxRiscv_inst.HWSchedulerPlugin_logic_ctxSwitchUnit.*`) and
    clears mtime whenever the context-switch unit signals a switch with the
    expected mcause. Splitting this off from `Clint` keeps the generic CLINT
    free of core-internal coupling.
    """
    name = "nax_clint"

    def attach(self, ctx: PeripheralCtx) -> None:
        super().attach(ctx)
        ctx.start(self._auto_reset_loop(ctx.dut, ctx.clk))

    @cocotb.coroutine
    def _auto_reset_loop(self, dut, clk):
        ctx_unit = dut.top_INST.NaxRiscv_inst.HWSchedulerPlugin_logic_ctxSwitchUnit
        while True:
            yield FallingEdge(clk)
            if ctx_unit.io_switch_bank.value and ctx_unit.io_trap_payload_mcause.value == _NAX_CTXSWITCH_MCAUSE:
                self._impl.clint_mtime = 0
                self._impl.clint_mtime_h = 0
