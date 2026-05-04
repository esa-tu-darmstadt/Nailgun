from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import cocotb


@dataclass
class PeripheralCtx:
    dut: Any
    clk: Any
    env: dict
    memsi: list
    data_memview: Any = None

    def add_memview(self, busidx, mv) -> None:
        idxs = [busidx] if isinstance(busidx, int) else list(busidx)
        for i in idxs:
            self.memsi[i].memview.children.append(mv)

    def start(self, coro) -> None:
        cocotb.start_soon(coro)


class SimPeripheral:
    name: str = "<unnamed>"

    def probe(self, dut) -> bool:
        return True

    def attach(self, ctx: PeripheralCtx) -> None:
        raise NotImplementedError
