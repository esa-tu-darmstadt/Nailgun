import cocotb
from cocotb.triggers import Timer, RisingEdge
from processortest import ProcessorTest
from testutil import test_envarg_true, get_envarg_or

# Sensible values for 200MHz GLS: CLK_PERIOD=5000, SAMPLE_DELAY=2500, ASSIGN_DELAY=300
CLK_PERIOD = int(get_envarg_or(cocotb.plusargs, "CLK_PERIOD", "1000")) # Length of a clock period in ps
SAMPLE_DELAY = int(get_envarg_or(cocotb.plusargs, "SAMPLE_DELAY", "0")) # When to sample an output by the core
ASSIGN_DELAY = int(get_envarg_or(cocotb.plusargs, "ASSIGN_DELAY", "0")) # When to change an input to the core
TIMEOUT_PERIODS = int(get_envarg_or(cocotb.plusargs, "CYCLE_TIMEOUT", "1000")) # Number of clock periods until timeout
PRINT_CLK = test_envarg_true(cocotb.plusargs, "PRINT_CLK")

@cocotb.test()
async def run_test(dut):
    # dut._discover_all() works in recent versions of Verilator.
    # Note that _discover_all() on inner scopes can still cause issues
    #  trying to overwrite a signal value.
    # -> https://github.com/verilator/verilator/issues/3919
    dut._discover_all()

    is_gls = test_envarg_true(cocotb.plusargs, "GLS")
    reset_cycles = 20
    reset_clkgate_cycles_pre = int(get_envarg_or(cocotb.plusargs, "RESET_CLKGATE_CYCLES_PRE", "0"))
    reset_clkgate_cycles_post = int(get_envarg_or(cocotb.plusargs, "RESET_CLKGATE_CYCLES_POST", "0"))

    if 'VSS' in dut._sub_handles:
        assert(is_gls)
        dut.VSS.setimmediatevalue(0)
        dut.VDD.setimmediatevalue(1)
    if 'shift_enable' in dut._sub_handles:
        assert(is_gls)
        dut.shift_enable.setimmediatevalue(0)
        dut.test_mode.setimmediatevalue(0)
    if 'DFT_sdi_1' in dut._sub_handles:
        assert(is_gls)
        dut.DFT_sdi_1.setimmediatevalue(0)
    if 'SI1' in dut._sub_handles:
        assert(is_gls)
        dut.SI1.setimmediatevalue(0)

    proctest = ProcessorTest(dut, CLK_PERIOD, SAMPLE_DELAY, ASSIGN_DELAY, TIMEOUT_PERIODS, env=cocotb.plusargs)

    await proctest.run(PRINT_CLK, reset_cycles, reset_clkgate_cycles_pre, reset_clkgate_cycles_post)

    await RisingEdge(proctest.clk)
