import importlib
from collections import deque
from typing import Callable

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Event, First

from .base import SimPeripheral, PeripheralCtx
from testutil import test_envarg_true, get_envarg_or


class TraceMismatchException(Exception):
    pass


class _ISSDriver:
    """Pulls trace entries from the (subscribed) RTL-side queue, drives the
    ISS one step at a time, and feeds matching ISS results into the
    peripheral-private iss_trace_queue for the lockstep comparator to
    consume. Body is the same control flow that previously lived in
    sim/test_iss_lockstep.py:ISSDriver — kept private here because the only
    legitimate caller is the ISSLockstep peripheral.
    """
    def __init__(self, dut, shutdown_event: Event,
                 core_trace_queue: Queue, iss_trace_queue_out: Queue,
                 pred_is_start_of_interrupt: Callable,
                 isaxes: list, env: dict, IS_64: bool, PRINT_ISS: bool):
        from iss.iss_adapter import ISSTbAdapter
        self.dut = dut
        self.shutdown_event = shutdown_event
        self.core_trace_queue = core_trace_queue
        self.iss_trace_queue_out = iss_trace_queue_out
        self.iss_adapter = ISSTbAdapter(dut, isaxes, [], env=env, IS_64=IS_64, PRINT_ISS=PRINT_ISS)
        self.core_interrupt_pending = False
        self.pred_is_start_of_interrupt = pred_is_start_of_interrupt
        cocotb.start_soon(self._handle_iss())

    def set_core_interrupt_pending(self):
        """Hook for tracer-driven interrupt notification. Reserved — currently
        no caller in tree, preserved for parity with the prior ISSDriver
        public API."""
        self.core_interrupt_pending = True

    @cocotb.coroutine
    async def _handle_iss(self):
        shutdown_trigger = self.shutdown_event.wait()
        core_trace_queue_delayed: deque = deque()
        shutdown_iss = False
        while not shutdown_iss:
            core_traced = None
            if self.core_trace_queue.qsize() > 0:
                core_traced = self.core_trace_queue.get_nowait()
            else:
                get_trigger = cocotb.start_soon(self.core_trace_queue.get())
                core_traced = await First(shutdown_trigger, get_trigger)
            if self.shutdown_event.is_set():
                break
            if self.core_interrupt_pending and self.pred_is_start_of_interrupt(core_traced):
                self.dut._log.info("ISS transferring to interrupt handler in %d cycle(s)" % len(core_trace_queue_delayed))
                self.iss_adapter.handleInterruptInNumCommits(len(core_trace_queue_delayed))
                self.core_interrupt_pending = False
            core_trace_queue_delayed.append(core_traced)
            # Keep the ISS one step behind the core while an interrupt is
            # pending so the adapter can be told about the jump one tick
            # before it commits.
            while len(core_trace_queue_delayed) > (1 if self.core_interrupt_pending else 0):
                self.iss_adapter.traceSetCompareResult = True
                res = await self.iss_adapter.processStep()
                if res is None:
                    shutdown_iss = True
                    break
                assert(len(res) <= 1)
                for i in range(len(res)):
                    core_trace_queue_delayed.popleft()
                    await self.iss_trace_queue_out.put(res[i])
        self.iss_adapter.shutdown()


class ISSLockstepPeripheral(SimPeripheral):
    """Lockstep an ISS reference model against the RTL trace.

    On `attach`, gated by env `SIM_ENABLE_ISS_LOCKSTEP`, this peripheral:
      1. Loads the requested ISAX handlers (predefined zol, renode-script,
         disaxkill/disaxfence, multi-context) from env+ISAX_YAML.
      2. Builds the ISSTbAdapter wrapping the riscvvp ISS.
      3. Subscribes twice to `ctx.core_trace_queue` (filled by the per-core
         tracer peripheral that attached earlier in the list) — one stream
         for the driver, one for the comparator.
      4. Spawns a private `_ISSDriver` coroutine that consumes RTL trace
         entries, steps the ISS, and publishes matching ISS results to a
         peripheral-private `iss_trace_queue`.
      5. Spawns a private `_observe_traces` coroutine that pairs each RTL
         trace entry with the matching ISS result and asserts equality.

    Per-core specifics (XLEN, the interrupt-entry predicate) come from the
    constructor and from `ctx.tracer_peripheral.is_start_of_interrupt`.
    """
    name = "iss_lockstep"

    def __init__(self, is_64: bool):
        self.is_64 = is_64
        self._driver = None
        self._iss_trace_queue: Queue | None = None

    @cocotb.coroutine
    async def _observe_traces(self, dut, rtl_trace: Queue, iss_trace: Queue, print_iss: bool):
        while True:
            core_trace_entry = await rtl_trace.get()
            iss_trace_entry = await iss_trace.get()
            if not (core_trace_entry == iss_trace_entry):
                dut._log.error("-TRACE mismatch ISS %s; Core %s" % (str(iss_trace_entry), str(core_trace_entry)))
                raise TraceMismatchException("ISS trace not matching core")
            elif print_iss:
                dut._log.info("-TRACE match ISS %s; Core %s" % (str(iss_trace_entry), str(core_trace_entry)))

    def probe(self, dut) -> bool:
        return True

    def attach(self, ctx: PeripheralCtx) -> None:
        env = ctx.env
        if not test_envarg_true(env, "SIM_ENABLE_ISS_LOCKSTEP"):
            ctx.dut._log.info("ISS lockstep disabled by env (SIM_ENABLE_ISS_LOCKSTEP)")
            return
        if ctx.tracer_peripheral is None:
            ctx.dut._log.warning("ISS lockstep requested but no tracer peripheral attached — skipping")
            return

        # Lazy: ISS-side imports pull in pyriscvvp + sim-only deps that we
        # don't want to require when lockstep is disabled.
        from iss.iss_renode_adapter import ISSRenodeISAXAdapter
        from iss.isax.isax_predefined import ISSFenceKillISAX, ISSContextISAX
        from isax_yaml_tools import extract_encodings, yaml_instr_filter_decoupled_writeback

        dut = ctx.dut
        isax_yaml = get_envarg_or(env, "ISAX_YAML", None)
        isax_python = get_envarg_or(env, "ISAX_PYTHON", "")
        isax_renode = get_envarg_or(env, "ISAX_RENODE", None)
        if isax_renode == "":
            isax_renode = None
        number_of_contexts = int(get_envarg_or(env, "NUMBER_OF_CONTEXTS", "1"))
        if number_of_contexts <= 0:
            raise ValueError("NUMBER_OF_CONTEXTS must be at least 1")
        if number_of_contexts >= 10**12:
            raise ValueError("NUMBER_OF_CONTEXTS must be below 10**12")
        print_iss = test_envarg_true(env, "PRINT_ISS")

        if isax_yaml is not None:
            all_encodings = extract_encodings(isax_yaml)
            decoupled_encodings = extract_encodings(isax_yaml, yaml_instr_filter_decoupled_writeback)
        else:
            all_encodings = dict()
            decoupled_encodings = dict()

        pyhandlers = dict()
        for pymodule_name in ["iss.isax.isax_zol"]:
            try:
                pymodule = importlib.import_module(pymodule_name)
                pyhandlers.update(pymodule.getHandlers(dut))
            except ImportError:
                dut._log.warning("Could not import ISAX module %s" % pymodule_name)
        dut._log.info("Found predefined ISAX handlers: %s (selection: %s)" % (
            ','.join(pyhandlers.keys()),
            isax_python if isax_python else "<none>"))

        isaxes: list = []
        context_switch_callbacks = []
        if isax_python != "":
            for pyhandler_name in isax_python.split(','):
                if pyhandler_name == "":
                    continue
                if pyhandler_name not in pyhandlers:
                    dut._log.warning("Could not find requested predefined ISAX handler %s" % pyhandler_name)
                    continue
                isaxes.append(pyhandlers[pyhandler_name])

        if isax_renode is not None:
            def find_encoding_match(instr, encodings):
                for name, pattern in encodings.items():
                    matches = True
                    for i in range(32):
                        if pattern[i] != "-" and int(pattern[i]) != ((instr >> 31-i) & 1):
                            matches = False
                            break
                    if matches:
                        return True, name
                return False, None
            def cb_instr_decoupled(instr):
                found, _ = find_encoding_match(instr, decoupled_encodings)
                return found
            def cb_instr_name(instr):
                _, name = find_encoding_match(instr, all_encodings)
                return name
            renode_adapter = ISSRenodeISAXAdapter(dut, isax_renode, cb_instr_decoupled, cb_instr_name, print_iss)
            isaxes.append(renode_adapter)
            context_switch_callbacks.append(lambda ctxnum: renode_adapter.handleContextSwitch(ctxnum))
        if len(decoupled_encodings) > 0:
            # Always present: SCAIE-V's disaxkill/disaxfence may or may not be
            # disabled in the build, but the adapter handler is harmless when
            # they aren't issued.
            isaxes.append(ISSFenceKillISAX(dut, True, True))
        if number_of_contexts > 1:
            isaxes.append(ISSContextISAX(dut, number_of_contexts, context_switch_callbacks))

        # Driver and comparator each consume the RTL trace stream
        # independently — one to step the ISS, one to pair-check entries.
        # The ISS-trace queue between them is fully owned here.
        driver_rtl_trace = ctx.subscribe_core_trace()
        compare_rtl_trace = ctx.subscribe_core_trace()
        self._iss_trace_queue = Queue()
        self._driver = _ISSDriver(
            dut,
            ctx.completion_event,
            driver_rtl_trace,
            self._iss_trace_queue,
            ctx.tracer_peripheral.is_start_of_interrupt,
            isaxes, env, self.is_64, print_iss,
        )
        cocotb.start_soon(self._observe_traces(dut, compare_rtl_trace, self._iss_trace_queue, print_iss))
