from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Event


@dataclass
class PeripheralCtx:
    dut: Any
    clk: Any
    env: dict
    memsi: list
    # Producer-side queue for per-instruction RTL trace events. Tracer
    # peripherals push CoreTracedInstr entries here; consumers (the ISS
    # lockstep peripheral) get their own subscriber queue via
    # `subscribe_core_trace()`. ProcessorTest fans the producer queue out to
    # all subscribers via QueueBroadcast after attach completes.
    core_trace_queue: Queue = field(default_factory=Queue)
    # Set by ProcessorTest after `run()` returns so consumer coroutines (the
    # ISS driver in particular) can shut down cleanly.
    completion_event: Event = field(default_factory=Event)
    # Raised by the test_control peripheral when the test program writes the
    # IRQ-completion address; the harness awaits this in `_run_test`.
    test_done_event: Event = field(default_factory=Event)
    # Address of the ELF's `_test_resdata` symbol (None if the program
    # didn't define one). Set by ProcessorTest after `TestLoader` runs and
    # consumed by the test_control peripheral when it picks which memview
    # to read for the post-run result check.
    resdata_location: int = None
    # The tracer peripheral that successfully attached (if any). The ISS
    # lockstep peripheral consults it for the per-core
    # `is_start_of_interrupt(traced_instr)` predicate. Set by the tracer's
    # `attach()`.
    tracer_peripheral: Any = None
    _core_trace_subscribers: list = field(default_factory=list)

    def add_memview(self, busidx, mv) -> None:
        idxs = [busidx] if isinstance(busidx, int) else list(busidx)
        for i in idxs:
            self.memsi[i].memview.children.append(mv)

    def start(self, coro) -> None:
        cocotb.start_soon(coro)

    def subscribe_core_trace(self) -> Queue:
        """Return a fresh Queue that will receive every entry published to
        `core_trace_queue` after the ProcessorTest fan-out kicks in."""
        q = Queue()
        self._core_trace_subscribers.append(q)
        return q


class SimPeripheral:
    name: str = "<unnamed>"

    def probe(self, dut) -> bool:
        return True

    def attach(self, ctx: PeripheralCtx) -> None:
        raise NotImplementedError
