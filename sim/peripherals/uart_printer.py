import cocotb
from cocotb.triggers import Event

from mem.memutil import MemView

from .base import SimPeripheral, PeripheralCtx


class _UARTPrinter:
    def __init__(self):
        self.buffer = b''

    def write_byte(self, byte):
        char = chr(byte)
        if char == '\n':
            print(f"\n\n\nSIMULATION PERFORMED A PRINTF:\n{self.buffer.decode(errors='replace')}\n\n\n")
            self.buffer = b''
        else:
            self.buffer += bytes([byte])

    def flush(self):
        if self.buffer:
            print(f"\n\n\nSIMULATION PERFORMED A PRINTF:\n{self.buffer.decode(errors='replace')}\n\n\n")
            self.buffer = b''


class UartPrinterPeripheral(SimPeripheral):
    """MMIO byte-write sink that buffers print bytes line-by-line.

    A non-zero byte write at `base_addr` is appended to the buffer; on
    `\\n` (or at completion time) the buffer is printed. Word-aligned writes
    consume only the bytes whose `wstrb` is set. Reads return zero.
    """
    name = "uart_printer"

    def __init__(self, base_addr: int, busidx):
        self.base_addr = base_addr
        self.busidx = busidx
        self._uart_printer = _UARTPrinter()

    def probe(self, dut) -> bool:
        return True

    def attach(self, ctx: PeripheralCtx) -> None:
        ctx.add_memview(self.busidx, MemView(
            read_cb=self._read,
            write_cb=self._write,
            base_addr=self.base_addr,
            length=4,
        ))
        cocotb.start_soon(self._flush_on_completion(ctx.completion_event))

    def _write(self, addr_begin, addr_end, word, wstrb):
        if word[0] != 0 and wstrb[0] != 0:
            for i in range(len(wstrb.binstr)):
                if wstrb[i] != 0:
                    self._uart_printer.write_byte(word[i])
            return True
        return False

    def _read(self, addr_begin, addr_end, big_endian):
        return bytes([0] * (addr_end - addr_begin))

    @cocotb.coroutine
    async def _flush_on_completion(self, completion_event: Event):
        await completion_event.wait()
        self._uart_printer.flush()
