import cocotb
import inspect
from cocotb.types import LogicArray, Range
from typing import Optional

# Error handling is not optimal (MemViewErrors aren't passed through HierarchicalMemView)

class MemViewError(Exception):
    pass


# cocotb 2.0 replaced BinaryValue with LogicArray. The helpers below reproduce the
# BinaryValue(n_bits=..., bigEndian=...) semantics the bus models rely on:
#   * bigEndian=False indexes/slices LSB-first, i.e. Range(n-1, "downto", 0),
#     and its .buff is little-endian byte order.
#   * bigEndian=True indexes MSB-first, i.e. Range(0, "to", n-1), .buff big-endian.
# Everything in nailgun instantiates the bus models with big_endian=False, but the
# parameter is threaded through so the (untested) big-endian path keeps working.

def word_range(n_bits: int, big_endian: bool) -> Range:
    """Index scheme equivalent to BinaryValue(n_bits=n_bits, bigEndian=big_endian)."""
    return Range(0, "to", n_bits - 1) if big_endian else Range(n_bits - 1, "downto", 0)

def _byteorder(big_endian: bool) -> str:
    return "big" if big_endian else "little"

def make_word(n_bits: int, big_endian: bool) -> LogicArray:
    """Zero-initialized word, replacing BinaryValue(n_bits=..., bigEndian=...)."""
    return LogicArray(0, word_range(n_bits, big_endian))

def word_from_bytes(data, n_bits: int, big_endian: bool) -> LogicArray:
    """Replaces `bv = BinaryValue(n_bits=...); bv.buff = data`."""
    return LogicArray.from_bytes(bytes(data), word_range(n_bits, big_endian),
                                 byteorder=_byteorder(big_endian))

def word_to_bytes(word: LogicArray, big_endian: bool) -> bytes:
    """Replaces `bv.buff`."""
    return word.to_bytes(byteorder=_byteorder(big_endian))

def rebase_word(word: LogicArray, big_endian: bool) -> LogicArray:
    """Re-label a slice to 0-based indices.

    cocotb-1 slices produced a fresh 0-based BinaryValue; cocotb-2 slices keep the
    parent's index labels (`la[5:2].range == Range(5, 'downto', 2)`), so consumers
    that index from 0 need the result re-based.
    """
    return LogicArray(str(word), word_range(len(word), big_endian))

async def _maybe_await(value):
    if inspect.iscoroutine(value):
        return await value
    return value

def rotate_left(data: bytes, n: int) -> bytes:
    """
    Rotate an entire bytes object to the left by `n` bits.
    """
    total_bits = len(data) * 8
    n = n % total_bits  # Normalize

    if n == 0:
        return data

    as_int = int.from_bytes(data, byteorder='big')
    rotated = ((as_int << n) | (as_int >> (total_bits - n))) & ((1 << total_bits) - 1)
    return rotated.to_bytes(len(data), byteorder='big')

def rotate_right(data: bytes, n: int) -> bytes:
    """
    Rotate an entire bytes object to the right by `n` bits.
    """
    total_bits = len(data) * 8
    n = n % total_bits  # Normalize

    if n == 0:
        return data

    as_int = int.from_bytes(data, byteorder='big')
    rotated = ((as_int >> n) | (as_int << (total_bits - n))) & ((1 << total_bits) - 1)
    return rotated.to_bytes(len(data), byteorder='big')

def _extend_word(_st, word : LogicArray, n_word_bits, big_endian) -> LogicArray:
    if len(word) < n_word_bits:
        if (n_word_bits & 7) != 0 or (len(word) & 7) != 0:
            raise MemViewError("Word length is not in full bytes")
        # Note: Not tested for big endian
        in_word_byte_rotate_amount = _st & ((n_word_bits>>3) - 1) #>>3 -> uint div by 8
        word_new_buff = word_to_bytes(word, big_endian) + (b'\x00' * ((n_word_bits - len(word)) >> 3))
        word_new_buff = rotate_right(word_new_buff, in_word_byte_rotate_amount * 8) #Rotate depending on misalignment of _st by the word byte width
        return word_from_bytes(word_new_buff, n_word_bits, big_endian)
    return word

# MemView base class, can be instantiated with callbacks that handle reads and writes.
class MemView():
    # read_cb: (start byte position, one-beyond-last byte position, is big endian: bool)
    # write_cb: (start byte position, one-beyond-last byte position, word: bytes, wstrb: LogicArray)
    # base_addr/length: optional declared address range. If set, HierarchicalMemView
    #   uses it to dispatch most-specific-first (smaller declared region wins over a
    #   larger one that contains it). Leave as None for callback-only views that
    #   want to fall back to insertion-order matching.
    def __init__(self, read_cb=None, write_cb=None, *, base_addr=None, length=None):
        self._read_cb = read_cb
        self._write_cb = write_cb
        self.base_addr = base_addr
        self.length = length

    def _claims(self, _st, _end) -> Optional[bool]:
        """Region containment for [_st, _end). Returns:
            True  — view declares a region that fully contains the access
            False — view declares a region that does NOT contain the access
            None  — view did not declare a region (try via callback)
        """
        if self.base_addr is None or self.length is None:
            return None
        return self.base_addr <= _st and _end <= self.base_addr + self.length

    def _write(self, _st, _end, word : LogicArray, wstrb : LogicArray) -> bool | MemViewError:
        return (self._write_cb is not None) and self._write_cb(_st,_end,word,wstrb)

    def _read(self, _st, _end, n_word_bits, big_endian) -> LogicArray | None | MemViewError:
        if self._read_cb is None:
            return None
        word_data = self._read_cb(_st,_end,big_endian)
        if word_data is None:
            return None
        return word_from_bytes(word_data, (_end-_st)*8, big_endian)

    # Public: Writes a word into the memory view in range [_st,_end). Can raise a MemViewError.
    # wstrb: For each byte in word, wstrb[i] indicates whether the new byte should be written.
    def write(self, _st, _end, word : bytes, wstrb : LogicArray):
        res = self._write(_st, _end, word, wstrb)
        if res == False:
            raise MemViewError("Write to address 0x%08x failed: No matching handler" % _st)
        if isinstance(res, MemViewError):
            raise res

    # Public: Reads a word from the memory view. Can raise a MemViewError.
    # n_word_bits: The number of bits the output word has (must be a multiple of 8).
    def read(self, _st, _end, n_word_bits, big_endian : bool = False) -> LogicArray:
        res = self._read(_st, _end, n_word_bits, big_endian)
        if res is None:
            raise MemViewError("Read from address 0x%08x failed: No matching handler" % _st)
        if isinstance(res, MemViewError):
            raise res
        return _extend_word(_st, res, n_word_bits, big_endian)

    # Async variants: callbacks may be coroutine functions (for cocotb-driven peripherals).
    # The base implementation defers to the sync path if the callback returned a non-coroutine,
    # otherwise awaits. Subclasses override _write_a/_read_a to await child views.
    async def _write_a(self, _st, _end, word, wstrb):
        if self._write_cb is None:
            return False
        return await _maybe_await(self._write_cb(_st, _end, word, wstrb))

    async def _read_a(self, _st, _end, n_word_bits, big_endian):
        if self._read_cb is None:
            return None
        word_data = await _maybe_await(self._read_cb(_st, _end, big_endian))
        if word_data is None:
            return None
        return word_from_bytes(word_data, (_end-_st)*8, big_endian)

    async def awrite(self, _st, _end, word : bytes, wstrb : LogicArray):
        res = await self._write_a(_st, _end, word, wstrb)
        if res == False:
            raise MemViewError("Write to address 0x%08x failed: No matching handler" % _st)
        if isinstance(res, MemViewError):
            raise res

    async def aread(self, _st, _end, n_word_bits, big_endian : bool = False) -> LogicArray:
        res = await self._read_a(_st, _end, n_word_bits, big_endian)
        if res is None:
            raise MemViewError("Read from address 0x%08x failed: No matching handler" % _st)
        if isinstance(res, MemViewError):
            raise res
        return _extend_word(_st, res, n_word_bits, big_endian)

# MemView backed by a bytearray, with optional callbacks.
class BytearrayMemView(MemView):
    def __init__(self, memory : bytearray, memory_section_offs=0, memory_section_len=-1, memory_baseaddr=0,
            read_cb=None, write_cb=None, auto_resize=False):
        if memory_section_len == -1:
            memory_section_len = len(memory) - memory_section_offs
        MemView.__init__(self, read_cb, write_cb, base_addr=memory_baseaddr, length=memory_section_len)
        self.memory = memory
        self.memory_section_offs = memory_section_offs
        self.memory_section_len = memory_section_len
        self.memory_baseaddr = memory_baseaddr
        self.auto_resize = auto_resize

    def _write(self, _st, _end, word : bytes, wstrb) -> bool | MemViewError:
        base_res = MemView._write(self,_st,_end,word,wstrb)
        if base_res == True:
            return True
        if _st < self.memory_baseaddr or _end > self.memory_baseaddr + self.memory_section_len:
            return MemViewError("Write to address 0x%08x: Out of range [%08x,%08x)" % (_st, self.memory_baseaddr, self.memory_baseaddr + self.memory_section_len))
        memoryarr_startoffs = _st - self.memory_baseaddr + self.memory_section_offs
        memoryarr_endoffs = _end - self.memory_baseaddr + self.memory_section_offs
        if memoryarr_endoffs > len(self.memory):
            if not self.auto_resize:
                return MemViewError("Write to address 0x%08x out of bounds of backing array (%08x > %08x)" % (_st, memoryarr_endoffs, len(self.memory)))
            self.memory += bytearray(memoryarr_endoffs - len(self.memory))
        for i in range(len(wstrb)):
            if wstrb[i] == 0:
                word[i] = self.memory[memoryarr_startoffs + i]
        self.memory[memoryarr_startoffs : memoryarr_endoffs] = word
        return True

    def _read(self, _st, _end, n_word_bits, big_endian) -> LogicArray | None | MemViewError:
        base_res = MemView._read(self,_st,_end,n_word_bits,big_endian)
        if isinstance(base_res, LogicArray):
            print("Read from address 0x%08x -> %s (callback)" % (_st, str(word_to_bytes(base_res, big_endian))))
            return base_res
        if _st < self.memory_baseaddr or _end > self.memory_baseaddr + self.memory_section_len:
            return MemViewError("Read from address 0x%08x: Out of range [%08x,%08x)" % (_st, self.memory_baseaddr, self.memory_baseaddr + self.memory_section_len))
        memoryarr_startoffs = _st - self.memory_baseaddr + self.memory_section_offs
        memoryarr_endoffs = _end - self.memory_baseaddr + self.memory_section_offs
        if memoryarr_endoffs > len(self.memory):
            if not self.auto_resize:
                return MemViewError("Read from address 0x%08x: Out of bounds of backing array (%08x > %08x)" % (_st, memoryarr_endoffs, len(self.memory)))
            self.memory += bytearray(memoryarr_endoffs - len(self.memory))
        return word_from_bytes(self.memory[memoryarr_startoffs : memoryarr_endoffs],
                               (_end-_st)*8, big_endian)

    async def _write_a(self, _st, _end, word, wstrb):
        base_res = await MemView._write_a(self, _st, _end, word, wstrb)
        if base_res == True:
            return True
        # Fall through to bytearray-backed write (sync semantics)
        return self._write(_st, _end, word, wstrb)

    async def _read_a(self, _st, _end, n_word_bits, big_endian):
        base_res = await MemView._read_a(self, _st, _end, n_word_bits, big_endian)
        if isinstance(base_res, LogicArray):
            return base_res
        # Fall through to bytearray-backed read (sync semantics)
        return self._read(_st, _end, n_word_bits, big_endian)

# MemView backed by several child MemViews, with optional callbacks.
#
# Children are dispatched most-specific-first: a child whose declared region
# (MemView.base_addr/length) fully contains the access wins over a child with a
# larger declared region. Children that did not declare a region are tried last,
# in insertion order, matching legacy behavior.
class HierarchicalMemView(MemView):
    def __init__(self, children,
            read_cb=None, write_cb=None, *, base_addr=None, length=None):
        MemView.__init__(self, read_cb, write_cb, base_addr=base_addr, length=length)
        self.children = children

    def _ordered(self, _st, _end):
        """Yield children in priority order for an access to [_st, _end).
           Children whose declared region does not contain the access are skipped."""
        claimed = []
        unknown = []
        for c in self.children:
            v = c._claims(_st, _end) if isinstance(c, MemView) else None
            if v is True:
                claimed.append(c)
            elif v is None:
                unknown.append(c)
            # v is False -> declared out of range, skip
        claimed.sort(key=lambda c: c.length)
        return claimed + unknown

    def _write(self, _st, _end, word : bytes, wstrb) -> bool | MemViewError:
        base_res = MemView._write(self,_st,_end,word,wstrb)
        if base_res == True:
            return True
        for child in self._ordered(_st, _end):
            child_res = child._write(_st,_end,word,wstrb)
            if child_res == True:
                return True
        return False

    def _read(self, _st, _end, n_word_bits, big_endian) -> LogicArray | None | MemViewError:
        base_res = MemView._read(self,_st,_end,n_word_bits,big_endian)
        if isinstance(base_res, LogicArray):
            return base_res
        for child in self._ordered(_st, _end):
            child_res = child._read(_st,_end,n_word_bits,big_endian)
            if isinstance(child_res, LogicArray):
                return child_res
        return None

    async def _write_a(self, _st, _end, word, wstrb):
        base_res = await MemView._write_a(self, _st, _end, word, wstrb)
        if base_res == True:
            return True
        for child in self._ordered(_st, _end):
            child_res = await child._write_a(_st, _end, word, wstrb)
            if child_res == True:
                return True
        return False

    async def _read_a(self, _st, _end, n_word_bits, big_endian):
        base_res = await MemView._read_a(self, _st, _end, n_word_bits, big_endian)
        if isinstance(base_res, LogicArray):
            return base_res
        for child in self._ordered(_st, _end):
            child_res = await child._read_a(_st, _end, n_word_bits, big_endian)
            if isinstance(child_res, LogicArray):
                return child_res
        return None

