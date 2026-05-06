import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ReadOnly, Event, with_timeout, First
from mem.amba import AXI4Slave
from mem.bram import BRAMSlave
from mem.simplebus import SimpleBusSlave
from mem.memutil import HierarchicalMemView, BytearrayMemView, MemView
from TestLoader import TestLoader
from testutil import test_envarg_true, get_envarg_or, QueueBroadcast
from peripherals.base import PeripheralCtx
from peripherals.test_control import TestControlPeripheral
from peripherals.debug_pin import DebugPinPeripheral
from peripherals.uart_printer import UartPrinterPeripheral
from peripherals.clock_print import ClockPrintPeripheral
import disas

class ConfigException(Exception):
    pass
class CoreExceptionException(Exception):
    pass

class ProcessorTest:

    def __init__(self, dut, CLK_PERIOD, SAMPLE_DELAY, ASSIGN_DELAY, TIMEOUT_PERIODS,
                 env=os.environ):
        self.dut = dut
        self.CLK_PERIOD = CLK_PERIOD
        self.SAMPLE_DELAY = SAMPLE_DELAY
        self.ASSIGN_DELAY = ASSIGN_DELAY
        self.TIMEOUT_PERIODS = TIMEOUT_PERIODS
        self.completion_event = Event('processortest_completion')
        self.clk = dut.clk
        self.rst = dut.rst
        self.rst.setimmediatevalue(1) # High active reset
        self.trap = dut.trap if ("HAS_TRAP_PIN" in env) else None

        self.PRINT_IMEM = test_envarg_true(env, "PRINT_IMEM")
        self.PRINT_DMEM = test_envarg_true(env, "PRINT_DMEM")
        self.PRINT_BRAM = test_envarg_true(env, "PRINT_BRAM")
        self.PRINT_AXI = test_envarg_true(env, "PRINT_AXI")
        self.CORE_NAME = env["CORE_NAME"]
        self.ISAX_YAML = env["ISAX_YAML"]
        self.RESET_CYCLES = 20
        self.RESET_CLKGATE_CYCLES_PRE = int(get_envarg_or(cocotb.plusargs, "RESET_CLKGATE_CYCLES_PRE", "0"))
        self.RESET_CLKGATE_CYCLES_POST = int(get_envarg_or(cocotb.plusargs, "RESET_CLKGATE_CYCLES_POST", "0"))

        disas.register_isax_yaml(self.ISAX_YAML)
        # Optionally you can manually add patterns like so:
        # disas.register_isax_patterns({
        #     'HW_CTX_LOAD':  "0000000----------000-----0001011",
        #     'HW_CTX_STORE_ONLY_SWITCH_BACK': "0000000----------101-----0001011",
        #     'HW_SCHED_SET_FIRST_CTX_ID': "0000000----------001-----0001011",
        #     'HW_SCHED_ADD_RDY_TASK': "0000000----------011-----0001011",
        #     'HW_SCHED_RM_RDY_TASK': "0000000----------100-----0001011",
        #     'HW_SCHED_NEXT_TASK': "0000000----------111-----0001011",
        # })

        self.NUM_BUSSI = int(env["NUM_BUSSI"])
        self.memsi = []
        for i_bussi in range(self.NUM_BUSSI):
            bussi_type = env["BUSSI%d_TYPE" % i_bussi]
            bussi_signame = env["BUSSI%d_SIGNAME" % i_bussi]
            match bussi_type:
                case "AXI4":
                    self.memsi.append(AXI4Slave(dut, bussi_signame, self.clk, HierarchicalMemView([]),
                                                SAMPLE_DELAY=SAMPLE_DELAY, ASSIGN_DELAY=ASSIGN_DELAY,
                                                big_endian=False, enable_prints=self.PRINT_AXI))
                case "BRAM":
                    self.memsi.append(BRAMSlave(dut, bussi_signame, self.clk, HierarchicalMemView([]),
                                                SAMPLE_DELAY=SAMPLE_DELAY, ASSIGN_DELAY=ASSIGN_DELAY,
                                                big_endian=False, enable_prints=self.PRINT_BRAM))
                case "Simple":
                    self.memsi.append(SimpleBusSlave(dut, bussi_signame, self.clk, HierarchicalMemView([]),
                                                     SAMPLE_DELAY=SAMPLE_DELAY, ASSIGN_DELAY=ASSIGN_DELAY,
                                                     big_endian=False, enable_prints=self.PRINT_BRAM))
                case _:
                    raise ConfigException("Unknown BusSI type " + bussi_type)

        #NOTE: Expects that IMEM and DMEM are not the same memories (i.e. on a different bus or with disjoint address ranges)

        self.IMEM_BUSIDX=[int(idxstr) for idxstr in env["IMEM_BUSIDX"].split(',')]
        self.IMEM_BASE=int(env["IMEM_BASE"], 16)
        self.EXCEPTION_BASE = int(env["EXCEPTION_BASE"], 16) if ("EXCEPTION_BASE" in env) else None

        self.DMEM_BUSIDX=[int(idxstr) for idxstr in env["DMEM_BUSIDX"].split(',')]
        self.DMEM_BASE=int(env["DMEM_BASE"], 16)
        self.DMEM_SIZE=int(env["DMEM_SIZE"], 16)

        ctrl_base_for_imem = int(env["CTRL_BASE"], 16)

        self.IMEM_SIZE = 0x10000000
        if self.DMEM_BASE > self.IMEM_BASE:
            self.IMEM_SIZE = self.DMEM_BASE - self.IMEM_BASE
        if ctrl_base_for_imem > self.IMEM_BASE:
            self.IMEM_SIZE = min(self.IMEM_SIZE, ctrl_base_for_imem - self.IMEM_BASE)

        TESTPROG = env["TESTPROG"]

        self.allowSpeculativeReads = test_envarg_true(env, "ALLOW_SPECULATIVE_READS")

        self.testStarted = False

        self.instr_mem = bytearray()
        instr_memview = BytearrayMemView(self.instr_mem, 0, self.IMEM_SIZE, self.IMEM_BASE, read_cb=self.check_instr_read, auto_resize=True)
        for busidx in self.IMEM_BUSIDX:
            self.memsi[busidx].memview.children.append(instr_memview)

        self.data_mem = bytearray(self.DMEM_SIZE)
        self.past_speculative_reads = set()
        data_memview = BytearrayMemView(self.data_mem, 0, self.DMEM_SIZE, self.DMEM_BASE, read_cb=self.check_data_read, write_cb=self.check_data_write)
        for busidx in self.DMEM_BUSIDX:
            self.memsi[busidx].memview.children.append(data_memview)

        # Region-less catch-all on the data bus: HierarchicalMemView only
        # invokes children whose declared region contains the access, so an
        # unmapped read (e.g. NaxRiscv speculative read at 0x0) needs an
        # unclaimed-region fallback to land in. Tried last by `_ordered()`.
        if self.allowSpeculativeReads:
            speculative_view = MemView(read_cb=self._check_speculative_read,
                                       write_cb=self._check_speculative_write)
            for busidx in self.DMEM_BUSIDX:
                self.memsi[busidx].memview.children.append(speculative_view)

        elfLoader = TestLoader(dut._log, [instr_memview, data_memview], [(self.IMEM_BASE,self.IMEM_BASE+self.IMEM_SIZE),(self.DMEM_BASE,self.DMEM_BASE+self.DMEM_SIZE)])
        resdata_location = elfLoader.load_test_case(TESTPROG+".elf")

        # Each core declares its own peripherals via CoreSupport.peripherals().
        # Iterate the list, probe each peripheral against the DUT, attach the
        # ones that apply. `probe()` replaces the previous try/except guards
        # and the CORE_NAME == "NaxRiscv" branch. The CoreSupport module +
        # its python deps were copied into this sim_dir at simulation setup
        # time, so the discovery walks `./cores/` (cwd-relative).
        import scaiev
        scaiev.register_cores()
        core_support = scaiev.get_core_support(self.CORE_NAME)
        peripheral_env = dict(env)
        peripheral_env["CLK_PERIOD"] = str(self.CLK_PERIOD)
        peripheral_ctx = PeripheralCtx(dut=dut, clk=self.clk, env=peripheral_env,
                                       memsi=self.memsi,
                                       completion_event=self.completion_event,
                                       resdata_location=resdata_location)

        # The test_control peripheral (CTRL bus owner + result-check) attaches
        # unconditionally — the harness needs a reference for do_result_check.
        # The debug-pin and UART byte sink are default peripherals: they sit
        # alongside any core-supplied peripherals in the probe/attach loop.
        # Their smaller declared regions (4 bytes each) shadow the
        # test_control bytearray for their addresses via HierarchicalMemView
        # dispatch.
        ctrl_base = int(peripheral_env["CTRL_BASE"], 16)
        ctrl_busidx = [int(s) for s in peripheral_env["CTRL_BUSIDX"].split(',')]
        self._test_control = TestControlPeripheral(peripheral_env)
        self._test_control.attach(peripheral_ctx)

        default_peripherals = [
            DebugPinPeripheral(ctrl_base + 4, ctrl_busidx),
            UartPrinterPeripheral(ctrl_base + 8, ctrl_busidx),
            ClockPrintPeripheral(test_envarg_true(peripheral_env, "PRINT_CLK")),
        ]
        for p in default_peripherals + core_support.peripherals(peripheral_env):
            if p.probe(dut):
                dut._log.info(f"attaching peripheral: {p.name}")
                p.attach(peripheral_ctx)
            else:
                dut._log.info(f"skipping peripheral (probe failed): {p.name}")
        self._peripheral_ctx = peripheral_ctx

        # Fan the per-core tracer's RTL trace stream out to all subscribers
        # (e.g. the ISS lockstep peripheral's driver and comparator). When no
        # peripheral subscribed the producer queue is left untouched.
        if peripheral_ctx._core_trace_subscribers:
            QueueBroadcast(peripheral_ctx.core_trace_queue, *peripheral_ctx._core_trace_subscribers)

        #Append to end of instruction memory, needed as cores tend to prefetch instructions
        self.instr_mem += bytearray(min(self.IMEM_SIZE-len(self.instr_mem),4*32))

    async def run(self):
        clkdriver = Clock(self.clk, self.CLK_PERIOD, units='ps')
        assert(self.RESET_CYCLES > self.RESET_CLKGATE_CYCLES_PRE)

        # Reset the core
        cocotb.start_soon(clkdriver.start(self.RESET_CYCLES - self.RESET_CLKGATE_CYCLES_PRE))
        self.dut._log.info("Setting rst")

        self.rst.value = 1
        await Timer(self.CLK_PERIOD * self.RESET_CYCLES + self.ASSIGN_DELAY, units='ps')
        self.rst.value = 0
        self.dut._log.info("Reset done")

        if self.ASSIGN_DELAY > 0:
            await Timer(self.CLK_PERIOD - self.ASSIGN_DELAY, units='ps')

        if self.RESET_CLKGATE_CYCLES_POST > 0:
            self.dut._log.info("Waiting for %d ps" % (self.CLK_PERIOD * self.RESET_CLKGATE_CYCLES_POST))
            await Timer(self.CLK_PERIOD * self.RESET_CLKGATE_CYCLES_POST, units='ps')

        # Start the simulation until completion / timeout
        cocotb.start_soon(clkdriver.start())
        self.dut._log.info("Driving clock again")
        self.testStarted = True

        await self._run_test()

    def check_instr_read(self, addr_begin, addr_end, big_endian):
        if self.PRINT_IMEM and self.testStarted and addr_begin >= self.IMEM_BASE and addr_end < (self.IMEM_BASE + len(self.instr_mem)):
            print("instruction read %08x" % addr_begin)
            # Initialize the disassembler for RISC-V (32-bit)
            instr_data = self.instr_mem[addr_begin - self.IMEM_BASE:addr_end - self.IMEM_BASE]
            for i in range(0, len(instr_data), 4):
                assembly = disas.disassemble(instr_data[i:i+4])
                for idx, asm in enumerate(assembly):
                    print(f"Address: 0x{addr_begin + i + idx * int(4 / len(assembly)):08x}, Instruction: {asm}")
        if (self.EXCEPTION_BASE is not None) and addr_begin == self.EXCEPTION_BASE:
            raise CoreExceptionException("The core fetched the exception handler address 0x%08x" % addr_begin)
        return None

    def check_data_read(self, addr_begin, addr_end, big_endian):
        # Only invoked for in-range accesses (data_memview claims [DMEM_BASE,
        # DMEM_BASE+DMEM_SIZE)); out-of-range speculative reads are handled by
        # `_check_speculative_read` on a separate region-less fallback view.
        if self.testStarted and self.PRINT_DMEM:
            print("data read %08x" % addr_begin)
        return None
    def check_data_write(self, addr_begin, addr_end, word, wstrb):
        if self.testStarted and self.PRINT_DMEM:
            print("data write %08x: %s strb %s" % (addr_begin, ' '.join([('%02x' % _byte) for _byte in word]), str(wstrb)))
        return False

    def _check_speculative_read(self, addr_begin, addr_end, big_endian):
        if not self.testStarted:
            return None
        print("WARNING: unmapped (speculative?) read at: %08x" % addr_begin)
        self.past_speculative_reads.add(addr_begin)
        return bytes([0] * (addr_end - addr_begin))

    def _check_speculative_write(self, addr_begin, addr_end, word, wstrb):
        if self.testStarted and addr_begin in self.past_speculative_reads:
            self.past_speculative_reads.remove(addr_begin)
            print("WARNING: allowing write-back of previously speculatively unmapped read: %08x - %08X" % (addr_begin, addr_end))
            return True
        return False

    async def _sample_delay(self):
        if self.SAMPLE_DELAY > 0:
            await Timer(self.SAMPLE_DELAY, units='ps')
        await ReadOnly()

    async def _run_test(self):
        # Make sure the trap output stabilizes before sampling it.
        timeout_periods = self.TIMEOUT_PERIODS
        if self.trap is not None:
            await Timer(self.CLK_PERIOD * 5, units='ps')
            timeout_periods -= 5
        await self._sample_delay()

        core_done_trigger = self._peripheral_ctx.test_done_event.wait()
        if self.trap is not None:
            if self.trap.value == 1:
                raise CoreExceptionException("The core set its trap pin")
            core_done_trigger = First(core_done_trigger, RisingEdge(self.trap))

        if timeout_periods > 0:
            await with_timeout(core_done_trigger, timeout_periods * self.CLK_PERIOD - self.SAMPLE_DELAY, timeout_unit='ps')
        else:
            await core_done_trigger

        if (self.trap is not None) and self.trap.value == 1:
            raise CoreExceptionException("The core set its trap pin")

        self._test_control.do_result_check()
