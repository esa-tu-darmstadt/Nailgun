import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, Lock
from cocotb_bus.drivers import BusDriver
from cocotb.binary import BinaryValue

from memutil import MemView

import array

class BRAMProtocolError(Exception):
    pass

bram_signals = [
    "addr",
    "en", "we",
    "din", "dout"
]

class BRAMSlave(BusDriver):
    def __init__(self, entity, name, clock, memview, event=None,
                 big_endian=False, **kwargs):
        self._signals = bram_signals
        BusDriver.__init__(self, entity, name, clock, **kwargs)
        self.clock = clock

        self.memview = memview

        self.big_endian = big_endian

        cocotb.start_soon(self._process())

    @cocotb.coroutine
    async def _process(self):
        clock_re = RisingEdge(self.clock)

        while True:
            while True:
                await ReadOnly()
                if self.bus.en.value:
                    break

            if self.bus.we.value != 0:
                _st = int(self.bus.addr)
                _end = _st + (self.bus.din.value.n_bits >> 3) #/ 8
                word = self.bus.din.value
                wstrb = self.bus.we.value

                wstrb.binstr= wstrb.binstr[::-1]

                word.big_endian = self.big_endian
                word = array.array('B', word.buff)

                self.memview.write(_st,_end,word,wstrb)

                if __debug__ or True:
                    print("BRAM write - addr %08x, din %08x, we %s" % (_st, int(self.bus.din), str(wstrb)))


            _st = int(self.bus.addr)
            _end = _st + (self.bus.dout.value.n_bits >> 3) #/ 8

            await clock_re

            read_val = self.memview.read(_st,_end, self.bus.dout.value.n_bits, self.big_endian)
            self.bus.dout.value = read_val

            if __debug__ or True:
                print("BRAM read - addr %08x, data %08x\n" % (_st, read_val.integer))
