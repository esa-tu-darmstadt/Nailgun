# Copyright (c) 2014 Potential Ventures Ltd
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of Potential Ventures Ltd,
#       SolarFlare Communications Inc nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL POTENTIAL VENTURES LTD BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Modified, with improved AXI4Slave

"""Drivers for Advanced Microcontroller Bus Architecture."""

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, Lock, Timer
from cocotb.handle import Immediate
from cocotb_bus.drivers import BusDriver
from cocotb.types import LogicArray

from .memutil import MemView, rebase_word, word_to_bytes
from .busutil import BusDelay

import array


class AXIProtocolError(Exception):
    pass


axi4_lite_signals = [
    "AWVALID", "AWADDR", "AWREADY",        # Write address channel
    "WVALID", "WREADY", "WDATA", "WSTRB",  # Write data channel
    "BVALID", "BREADY", "BRESP",           # Write response channel
    "ARVALID", "ARADDR", "ARREADY",        # Read address channel
    "RVALID", "RREADY", "RRESP", "RDATA"  # Read data channel
]

axi4_additional_signals = [
    "WLAST",
    "RLAST",
    "ARSIZE",
    "AWSIZE",
    "ARBURST",
    "AWBURST",
    "ARLEN",
    "AWLEN",
    "ARLOCK",
    "AWLOCK",
    "ARCACHE",
    "AWCACHE",
    "ARPROT",
    "AWPROT",
    "ARID",
    "RID",
    "AWID",
    "BID"
]

axi4_id_signals = [
    "ARID",
    "RID",
    "AWID",
    "BID"
]

class AXI4LiteMaster(BusDriver):
    """AXI4-Lite Master.

    TODO: Kill all pending transactions if reset is asserted.
    """

    def __init__(self, entity, name, clock, signals=None, **kwargs):
        self._signals = axi4_lite_signals if signals is None else signals
        BusDriver.__init__(self, entity, name, clock, **kwargs)
        # Drive some sensible defaults (setimmediatevalue to avoid x asserts)
        self.bus.AWVALID.value = Immediate(0)
        self.bus.WVALID.value = Immediate(0)
        self.bus.ARVALID.value = Immediate(0)
        self.bus.BREADY.value = Immediate(1)
        self.bus.RREADY.value = Immediate(1)

        # Mutex for each channel that we master to prevent contention
        self.write_address_busy = Lock()
        self.read_address_busy = Lock()
        self.write_data_busy = Lock()

    async def _send_write_address(self, address, delay=0):
        """
        Send the write address, with optional delay (in clocks)
        """
        await self.write_address_busy.acquire()
        for cycle in range(delay):
            await RisingEdge(self.clock)

        self.bus.AWADDR.value = address
        self.bus.AWVALID.value = 1

        while True:
            await ReadOnly()
            if self.bus.AWREADY.value:
                break
            await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        self.bus.AWVALID.value = 0
        self.write_address_busy.release()

    async def _send_write_data(self, data, delay=0, byte_enable=0xF):
        """Send the write address, with optional delay (in clocks)."""
        await self.write_data_busy.acquire()
        for cycle in range(delay):
            await RisingEdge(self.clock)

        self.bus.WDATA.value = data
        self.bus.WVALID.value = 1
        self.bus.WSTRB.value = byte_enable

        while True:
            await ReadOnly()
            if self.bus.WREADY.value:
                break
            await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        self.bus.WVALID.value = 0
        self.write_data_busy.release()

    async def write(
        self, address: int, value: int, byte_enable: int = 0xf,
        address_latency: int = 0, data_latency: int = 0, sync: bool = True
    ) -> LogicArray:
        """Write a value to an address.

        Args:
            address: The address to write to.
            value: The data value to write.
            byte_enable: Which bytes in value to actually write.
                Default is to write all bytes.
            address_latency: Delay before setting the address (in clock cycles).
                Default is no delay.
            data_latency: Delay before setting the data value (in clock cycles).
                Default is no delay.
            sync: Wait for rising edge on clock initially.
                Defaults to True.

        Returns:
            The write response value.

        Raises:
            AXIProtocolError: If write response from AXI is not ``OKAY``.
        """
        if sync:
            await RisingEdge(self.clock)

        c_addr = cocotb.start_soon(self._send_write_address(address,
                                                      delay=address_latency))
        c_data = cocotb.start_soon(self._send_write_data(value,
                                                   byte_enable=byte_enable,
                                                   delay=data_latency))

        if c_addr:
            await c_addr
        if c_data:
            await c_data

        # Wait for the response
        while True:
            await ReadOnly()
            if self.bus.BVALID.value and self.bus.BREADY.value:
                result = self.bus.BRESP.value
                break
            await RisingEdge(self.clock)

        await RisingEdge(self.clock)

        if int(result):
            raise AXIProtocolError("Write to address 0x%08x failed with BRESP: %d"
                                   % (address, int(result)))

        return result

    async def read(self, address: int, sync: bool = True) -> LogicArray:
        """Read from an address.

        Args:
            address: The address to read from.
            sync: Wait for rising edge on clock initially.
                Defaults to True.

        Returns:
            The read data value.

        Raises:
            AXIProtocolError: If read response from AXI is not ``OKAY``.
        """
        if sync:
            await RisingEdge(self.clock)

        self.bus.ARADDR.value = address
        self.bus.ARVALID.value = 1

        while True:
            await ReadOnly()
            if self.bus.ARREADY.value:
                break
            await RisingEdge(self.clock)

        await RisingEdge(self.clock)
        self.bus.ARVALID.value = 0

        while True:
            await ReadOnly()
            if self.bus.RVALID.value and self.bus.RREADY.value:
                data = self.bus.RDATA.value
                result = self.bus.RRESP.value
                break
            await RisingEdge(self.clock)

        if int(result):
            raise AXIProtocolError("Read address 0x%08x failed with RRESP: %d" %
                                   (address, int(result)))

        return data

    def __len__(self):
        return 2**len(self.bus.ARADDR)

def check_for_id(entity, name):
    bus_signals = [sig[0] for sig in entity._sub_handles.items() if name in sig[0]]
    arid = [arid for arid in bus_signals if "arid" in arid.lower()]
    return len(arid) > 0

class AXI4Master(AXI4LiteMaster):
    """
    Full AXI4 Master
    """

    def __init__(self, entity, name, clock):
        signals = axi4_lite_signals + axi4_additional_signals
        self._has_id = check_for_id(entity, name)
        if self._has_id:
            signals += axi4_id_signals
        AXI4LiteMaster.__init__(self, entity, name, clock, signals=signals)

        # Drive some sensible defaults (setimmediatevalue to avoid x asserts)
        self.bus.WLAST.value = Immediate(1)
        self.bus.ARSIZE.value = Immediate(0b010) # 4 bytes
        self.bus.AWSIZE.value = Immediate(0b010) # 4 bytes
        self.bus.ARBURST.value = Immediate(1) # INCR
        self.bus.AWBURST.value = Immediate(1) # INCR
        self.bus.ARLEN.value = Immediate(0)
        self.bus.AWLEN.value = Immediate(0)
        self.bus.ARLOCK.value = Immediate(0)
        self.bus.AWLOCK.value = Immediate(0)
        self.bus.ARCACHE.value = Immediate(0)
        self.bus.AWCACHE.value = Immediate(0)
        self.bus.ARPROT.value = Immediate(0)
        self.bus.AWPROT.value = Immediate(0)
        if self._has_id:
            self.bus.ARID.value = Immediate(0)
            self.bus.AWID.value = Immediate(0)

class AXI4Slave(BusDriver):
    '''
    AXI4 Slave

    Monitors an internal memory and handles read and write requests.
    '''

    def __init__(self, entity, name, clock, memview : MemView, event=None,
                 big_endian=False, artificial_write_delay=0, artificial_read_delay=0,
                 SAMPLE_DELAY=0, ASSIGN_DELAY=0, enable_prints=True,
                 **kwargs):
        self._signals = axi4_lite_signals
        self._optional_signals = [
            "RCOUNT",  "WCOUNT",  "RACOUNT", "WACOUNT",
            "ARLOCK",  "AWLOCK",  "ARCACHE", "AWCACHE",
            "ARQOS",   "AWQOS",   "WID"
        ] + axi4_additional_signals
        # cocotb-bus weirdness
        self._optional_signals = self._optional_signals + [sig.lower() for sig in self._optional_signals]
        BusDriver.__init__(self, entity, name, clock, **kwargs)
        self.clock = clock
        self.busdelay = BusDelay(SAMPLE_DELAY, ASSIGN_DELAY)

        self.memview = memview

        self._has_id = hasattr(self.bus, "ARID") or hasattr(self.bus, "arid")
        # Assuming _has_id -> has ARID,RID,AWID,BID
        if self._has_id:
            self.bus_arid = self.bus.ARID if hasattr(self.bus, "ARID") else self.bus.arid
            self.bus_rid = self.bus.RID if hasattr(self.bus, "ARID") else self.bus.rid
            self.bus_awid = self.bus.AWID if hasattr(self.bus, "ARID") else self.bus.awid
            self.bus_bid = self.bus.BID if hasattr(self.bus, "ARID") else self.bus.bid

        self._has_size = hasattr(self.bus, "ARSIZE") or hasattr(self.bus, "arsize")
        # Assuming _has_size -> has ARSIZE,AWSIZE
        if self._has_size:
            self.bus_arsize = self.bus.ARSIZE if hasattr(self.bus, "ARSIZE") else self.bus.arsize
            self.bus_awsize = self.bus.AWSIZE if hasattr(self.bus, "AWSIZE") else self.bus.awsize

        self._has_burst = hasattr(self.bus, "ARBURST") or hasattr(self.bus, "arburst")
        # Assuming _has_burst -> has WLAST,RLAST,ARBURST,AWBURST,ARLEN,AWLEN
        if self._has_burst:
            self.bus_wlast = self.bus.WLAST if hasattr(self.bus, "ARBURST") else self.bus.wlast
            self.bus_rlast = self.bus.RLAST if hasattr(self.bus, "ARBURST") else self.bus.rlast
            self.bus_arlen = self.bus.ARLEN if hasattr(self.bus, "ARBURST") else self.bus.arlen
            self.bus_awlen = self.bus.AWLEN if hasattr(self.bus, "ARBURST") else self.bus.awlen
            self.bus_arburst = self.bus.ARBURST if hasattr(self.bus, "ARBURST") else self.bus.arburst
            self.bus_awburst = self.bus.AWBURST if hasattr(self.bus, "ARBURST") else self.bus.awburst

        self._has_prot = hasattr(self.bus, "ARPROT") or hasattr(self.bus, "arprot")
        # Assuming _has_prot -> has ARPROT, AWPROT
        if self._has_prot:
            self.bus_arprot = self.bus.ARPROT if hasattr(self.bus, "ARPROT") else self.bus.arprot
            self.bus_awprot = self.bus.AWPROT if hasattr(self.bus, "ARPROT") else self.bus.awprot

        self.big_endian = big_endian
        self.artificial_write_delay=artificial_write_delay
        self.artificial_read_delay=artificial_read_delay
        self.bus.ARREADY.value = Immediate(1)
        self.bus.RVALID.value = Immediate(0)
        if self._has_burst:
            self.bus_rlast.value = Immediate(0)
        self.bus.AWREADY.value = Immediate(0)
        self.bus.BVALID.value = Immediate(0)
        self.bus.BRESP.value = Immediate(0)
        self.bus.RRESP.value = Immediate(0)
        self.bus.RDATA.value = Immediate(0)
        if self._has_id:
            self.bus_bid.value = Immediate(0)
            self.bus_rid.value = Immediate(0)
        self._ar_requests = []
        self._aw_requests = []
        self._w_requests = []

        self.enable_prints = enable_prints

        self.write_address_busy = Lock()
        self.read_address_busy = Lock()
        self.write_data_busy = Lock()

        cocotb.start_soon(self._read_addr())
        cocotb.start_soon(self._read_data())
        cocotb.start_soon(self._write_addr())
        cocotb.start_soon(self._write_data())
        cocotb.start_soon(self._write_process())

    def burst_nextaddr(self, prev, burst, axlen, size_in_bytes, diff_beats=1):
        if burst == 0b00 or diff_beats == 0:
            return prev
        next = (prev + size_in_bytes * diff_beats) & ~(size_in_bytes - 1)
        if burst == 0b10: #Wrap
            #-> See https://zipcpu.com/blog/2019/04/27/axi-addr.html
            match axlen:
                case 1:
                    mask_lenbits = 1
                case 3:
                    mask_lenbits = 2
                case 7:
                    mask_lenbits = 3
                case 15:
                    mask_lenbits = 4
                case _:
                    raise AXIProtocolError("For WRAP burst mode, AxLEN must be in [1, 3, 7, 15], but is %d." % (axlen))
            mask = (size_in_bytes << mask_lenbits) - 1
            next = (prev & ~mask) | (next & mask)
        return next

    def _size_to_bytes_in_beat(self, AxSIZE):
        if AxSIZE <= 7:
            return 2 ** AxSIZE
        return None

    async def _write_process(self):
        clock_re = RisingEdge(self.clock)
        self.bus.BVALID.value = 0

        # Same shape as _read_data, for the same reason: writes must overlap.
        # The memory update is not a bus event, so accepted beats are retired
        # without spending a cycle, and B responses are driven one per cycle
        # with BVALID held across consecutive ones.
        b_pending = []            # (bid, delay)
        while True:
            while self._w_requests and len(b_pending) < self.MAX_PENDING_BEATS:
                (_st, _end, word, wstrb,
                 wlast, aw_request) = self._w_requests.pop(0)
                (_awaddr, _awlen, _awsize,
                 _awburst, _awprot, _awid) = aw_request

                # Assert the word byte length is a power of two
                assert(len(word) == len(word) & ~(len(word) - 1))
                if (len(word) > _end - _st):
                    # Select the active byte lanes for a narrow transfer
                    #Note: Big endian is untested
                    _st_wordoffs = _st & (len(word) - 1)
                    word = word[_st_wordoffs:_end-_st+_st_wordoffs]
                    wstrb = wstrb[_st_wordoffs:_end-_st+_st_wordoffs-1] if self.big_endian else wstrb[_end-_st+_st_wordoffs-1:_st_wordoffs]
                    wstrb = rebase_word(wstrb, self.big_endian)
                await self.memview.awrite(_st, _end, word, wstrb)

                if wlast:
                    b_pending.append((_awid, self.artificial_write_delay))

            await self.busdelay.assign_delay()
            drive = bool(b_pending) and b_pending[0][1] == 0
            if drive:
                self.bus.BVALID.value = 1
                if self._has_id:
                    self.bus_bid.value = b_pending[0][0]
            else:
                self.bus.BVALID.value = 0

            await self.busdelay.sample_delay(assign_delay_applied=True)
            accepted = drive and bool(self.bus.BREADY.value)
            await clock_re
            if accepted:
                b_pending.pop(0)
            elif b_pending and b_pending[0][1] > 0:
                head = b_pending[0]
                b_pending[0] = (head[0], head[1] - 1)



    async def _write_data(self):
        clock_re = RisingEdge(self.clock)
        self.bus.WREADY.value = 0

        while True:
            while True:
                await clock_re
                await self.busdelay.assign_delay()
                self.bus.WREADY.value = 0 if (len(self._aw_requests) == 0 or len(self._w_requests) >= 8) else 1
                await self.busdelay.sample_delay(assign_delay_applied=True)
                if self.bus.WREADY.value and self.bus.WVALID.value:
                    break

            _awaddr, _awlen, _awsize, _awburst, _awprot, _awid = self._aw_requests[0]

            word = array.array('B', word_to_bytes(self.bus.WDATA.value, self.big_endian))
            wlast = self.bus_wlast.value if self._has_burst else 1
            # cocotb-1 handed out MSB-first BinaryValues, so this used to flip the
            # strobe to LSB-first explicitly. Re-base to keep byte-lane indexing
            # independent of how WSTRB is declared in the HDL.
            wstrb = rebase_word(self.bus.WSTRB.value, self.big_endian)

            bytes_in_beat = self._size_to_bytes_in_beat(_awsize)
            _st = _awaddr  # start
            _end = _st + bytes_in_beat  # end

            self._w_requests.append((_st, _end, word, wstrb, wlast, self._aw_requests[0]))
            if wlast:
                self._aw_requests = self._aw_requests[1:]
            else:
                if _awlen == 0:
                    raise AXIProtocolError("Write to address 0x%08x: Expected wlast (burst end)" % (_awaddr))
                # Next write beat: Incremented address (assuming incr mode) by beat byte size (2**awsize), then aligned by 2**awsize - 1.
                next_addr = self.burst_nextaddr(_awaddr, _awburst, _awlen, bytes_in_beat)
                self._aw_requests[0] = (next_addr, _awlen - 1, _awsize, _awburst, _awprot, _awid)
            if self.enable_prints:
                print(
                    "(WADDR) %08x\n" % _awaddr +
                    "WDATA   %s\n" % ' '.join([('%02x' % _byte) for _byte in word]) +
                    "WSTRB   %s\n" % str(wstrb) +
                    "WLAST   %d\n" % wlast)



    async def _write_addr(self):
        self.bus.AWREADY.value = 0
        clock_re = RisingEdge(self.clock)

        while True:
            while True:
                await clock_re
                await self.busdelay.assign_delay()
                self.bus.AWREADY.value = 0 if (len(self._aw_requests) > 4) else 1
                await self.busdelay.sample_delay(assign_delay_applied=True)
                if self.bus.AWREADY.value and self.bus.AWVALID.value:
                    break

            _awaddr = int(self.bus.AWADDR)
            _awlen = int(self.bus_awlen) if self._has_burst else 0
            _awsize = int(self.bus_awsize) if self._has_size else 2 #Default 4 bytes per beat
            _awburst = int(self.bus_awburst) if self._has_burst else 0b00
            _awprot = int(self.bus_awprot) if self._has_prot else 0b000
            _awid = int(self.bus_awid) if self._has_id else 0

            burst_length = _awlen + 1
            bytes_in_beat = self._size_to_bytes_in_beat(_awsize)

            self._aw_requests.append((_awaddr, _awlen, _awsize, _awburst, _awprot, _awid))

            if self.enable_prints:
                print(
                    "AWADDR  %08x\n" % _awaddr +
                    "AWLEN   %d\n" % _awlen +
                    "AWSIZE  %d\n" % _awsize +
                    "AWBURST %d\n" % _awburst +
                    "AWPROT %d\n" % _awprot +
                    "AWID %d\n" % _awid +
                    "BURST_LENGTH %d\n" % burst_length +
                    "Bytes in beat %d\n" % bytes_in_beat)

    # Outstanding beats (read or write) this slave will hold before it stops
    # accepting more. Only a bound against unbounded growth -- masters here
    # limit themselves well below it.
    MAX_PENDING_BEATS = 32

    async def _read_data(self):
        """Read data channel: one beat per cycle, RVALID held across beats.

        Reads must overlap. A slave that finishes one transaction before
        looking at the next has a throughput of one read per several cycles no
        matter how low its latency is, and that ceiling propagates into the
        master: a CPU frontend that can only advance once a response is
        buffered will never have one buffered, so it fetches at the slave's
        transaction rate rather than one instruction per cycle. Per-transaction
        latency does not reveal this -- AR-to-R can be 0 cycles while the
        transaction-to-transaction period is 3.

        Accepted addresses are therefore expanded into a beat queue up front,
        and a beat is presented every cycle for as long as the queue is
        non-empty.
        """
        clock_re = RisingEdge(self.clock)
        self.bus.RVALID.value = 0
        if self._has_burst:
            self.bus_rlast.value = 0

        pending = []          # (addr, bytes_in_beat, rid, rlast, delay)
        while True:
            # Expand accepted addresses into beats, so several reads are in
            # flight at once rather than strictly one after another.
            while self._ar_requests and len(pending) < self.MAX_PENDING_BEATS:
                (_araddr, _arlen, _arsize,
                 _arburst, _arprot, _arid) = self._ar_requests.pop(0)
                burst_length = _arlen + 1
                bytes_in_beat = self._size_to_bytes_in_beat(_arsize)
                if self.enable_prints:
                    print("ARADDR %08x BURST_LENGTH %d Bytes in beat %d\n"
                          % (_araddr, burst_length, bytes_in_beat))
                for _beat in range(burst_length):
                    _st = self.burst_nextaddr(_araddr, _arburst, _arlen,
                                              bytes_in_beat, diff_beats=_beat)
                    pending.append((_st, bytes_in_beat, _arid,
                                    1 if _beat == burst_length - 1 else 0,
                                    self.artificial_read_delay if _beat == 0 else 0))

            await self.busdelay.assign_delay()
            drive = bool(pending) and pending[0][4] == 0
            if drive:
                _st, bytes_in_beat, _arid, rlast, _ = pending[0]
                rdata = await self.memview.aread(_st, _st + bytes_in_beat,
                                                 len(self.bus.RDATA.value),
                                                 self.big_endian)
                self.bus.RVALID.value = 1
                self.bus.RDATA.value = rdata
                if self._has_id:
                    self.bus_rid.value = _arid
                if self._has_burst:
                    self.bus_rlast.value = rlast
                if self.enable_prints:
                    print("RDATA  %s\nRID    %d\nRLAST  %d\n"
                          % (' '.join('%02x' % b for b in
                                      word_to_bytes(rdata, self.big_endian)),
                             _arid, rlast))
            else:
                self.bus.RVALID.value = 0
                if self._has_burst:
                    self.bus_rlast.value = 0

            await self.busdelay.sample_delay(assign_delay_applied=True)
            accepted = drive and bool(self.bus.RREADY.value)
            await clock_re
            if accepted:
                pending.pop(0)
            elif pending and pending[0][4] > 0:
                head = pending[0]
                pending[0] = head[:4] + (head[4] - 1,)


    async def _read_addr(self):
        self.bus.ARREADY.value = 0
        clock_re = RisingEdge(self.clock)

        while True:
            while True:
                await clock_re
                await self.busdelay.assign_delay()
                self.bus.ARREADY.value = 0 if (len(self._ar_requests) > 4) else 1
                await self.busdelay.sample_delay(assign_delay_applied=True)
                if self.bus.ARREADY.value and self.bus.ARVALID.value:
                    break

            _araddr = int(self.bus.ARADDR)
            _arlen = int(self.bus_arlen) if self._has_burst else 0
            _arsize = int(self.bus_arsize) if self._has_size else 2 #Default 4 bytes per beat
            _arburst = int(self.bus_arburst) if self._has_burst else 0b00
            _arprot = int(self.bus_arprot) if self._has_prot else 0b000
            _arid = int(self.bus_arid) if self._has_id else 0

            self._ar_requests.append((_araddr, _arlen, _arsize, _arburst, _arprot, _arid))

            if self.enable_prints:
                burst_length = _arlen + 1
                bytes_in_beat = self._size_to_bytes_in_beat(_arsize)
                print(
                    "ARADDR  %08x\n" % _araddr +
                    "ARLEN   %d\n" % _arlen +
                    "ARSIZE  %d\n" % _arsize +
                    "ARBURST %d\n" % _arburst +
                    "ARPROT %d\n" % _arprot +
                    "BURST_LENGTH %d\n" % burst_length +
                    "Bytes in beat %d\n" % bytes_in_beat)

