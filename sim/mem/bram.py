import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, Lock
from cocotb.handle import Immediate
from cocotb_bus.drivers import BusDriver

from .memutil import MemView, rebase_word, word_to_bytes
from .busutil import BusDelay

import array

class BRAMProtocolError(Exception):
    pass

bram_signals = [
    "addr",
    "en", "we",
    "din", "dout"
]

class BRAMSlave(BusDriver):
    def __init__(self, entity, name, clock, memview,
                 big_endian=False, SAMPLE_DELAY=0, ASSIGN_DELAY=0,
                 enable_prints=True, **kwargs):
        self._signals = bram_signals
        BusDriver.__init__(self, entity, name, clock, **kwargs)
        self.clock = clock
        self.busdelay = BusDelay(SAMPLE_DELAY, ASSIGN_DELAY)

        self.memview = memview

        self.big_endian = big_endian
        self.enable_prints = enable_prints

        self.bus.dout.value = Immediate(0)

        cocotb.start_soon(self._process())

    async def _process(self):
        clock_re = RisingEdge(self.clock)
        assign_delay_applied = False

        while True:
            while True:
                await self.busdelay.sample_delay(assign_delay_applied)
                if self.bus.en.value:
                    break
                await clock_re
                assign_delay_applied = False

            if self.bus.we.value != 0:
                _st = int(self.bus.addr)
                _end = _st + (len(self.bus.din.value) >> 3) #/ 8
                # cocotb-1 handed out MSB-first BinaryValues, hence the binstr
                # reversal; re-basing gives LSB-first byte-lane indexing directly.
                wstrb = rebase_word(self.bus.we.value, self.big_endian)

                word = array.array('B', word_to_bytes(self.bus.din.value, self.big_endian))

                await self.memview.awrite(_st,_end,word,wstrb)

                if self.enable_prints:
                    print("BRAM write - addr %08x, din %08x, we %s" % (_st, int(self.bus.din), str(wstrb)))


            _st = int(self.bus.addr)
            _end = _st + (len(self.bus.dout.value) >> 3) #/ 8

            await clock_re
            await self.busdelay.assign_delay()
            assign_delay_applied = True

            read_val = await self.memview.aread(_st,_end, len(self.bus.dout.value), self.big_endian)
            self.bus.dout.value = read_val

            if self.enable_prints:
                print("BRAM read - addr %08x, data %08x\n" % (_st, int(read_val)))
