#!/usr/bin/env python3
"""CV-X-IF glue logic generator.

Turns a Longnail-generated ISAX (``ISAX_<name>.yaml`` + ``ISAX_<name>.sv``,
scheduled against ``deps/longnail/datasheets/CVXIF.yaml``) into SystemVerilog
glue that attaches it to a CORE-V-XIF (CV-X-IF) host -- CV32E40X in practice,
since CV32E40P has no X-interface.

This is a standalone alternative to SCAIE-V: the core RTL is not touched at
all, only the standard eXtension interface is used.

What the glue does
------------------
1. **Decode.**  Every offered instruction word is matched against the ISAX's
   encoding masks; the match drives ``issue_resp.accept`` and
   ``issue_resp.writeback``.  Unknown instructions are rejected in the same
   cycle (``issue_ready = 1``, ``accept = 0``) so the core never waits on us.

2. **Issue -> input buffer.**  On the issue handshake the instruction word,
   rs1/rs2, ``id`` and ``rd`` are latched into a one-entry input buffer.
   ``issue_ready`` is withheld while that buffer is occupied or while an
   operand the instruction needs is not yet valid (``rs_valid``).

3. **Commit gate.**  The buffered instruction is admitted into the ISAX
   pipeline only after the core marked it non-speculative
   (``commit_valid && !commit_kill``).  Nothing inside the ISAX is therefore
   ever speculative, which is why ``RdFlush`` can be tied to 0 and custom
   registers need no rollback.  A ``commit_kill`` for the buffered
   instruction -- or for any older one, which per spec kills all newer
   instructions too -- drops the buffer entry.

4. **Shadow pipeline.**  A rigid in-order pipeline of ``LMAX+1`` stages (the
   stages the ISAX actually uses, i.e. the virtual datasheet's pipeline)
   carries valid / id / rd / we / decode-one-hot / result payload alongside
   the ISAX datapath.  It generates every ``RdIValid_*`` and ``RdStall_*``
   input of the ISAX and consumes its ``WrStall_*`` outputs:

       rdstall[LMAX] = result back-pressure
       rdstall[s]    = rdstall[s+1] | wrstall[s+1]      (s < LMAX)
       hold[s]       = rdstall[s]   | wrstall[s]

   ``RdStall`` deliberately excludes the same stage's ``WrStall``, as SCAIE-V's
   core-interface contract requires.

   The pipeline is as deep as the ISAX needs, taken from the stages that appear
   in the generated ISAX ports (not from the datasheet's ``last stage``).
   Because both ends of CV-X-IF are handshakes, an arbitrarily long ISAX just
   means a longer shadow pipeline -- there is no need for a decoupled writeback
   path, and CVXIF.yaml declares WrRD ``spawn: false`` so the scheduler never
   picks one.  ``_spawn`` ports can still show up (a CoreDSL ``spawn { }``
   block forces them regardless of the schedule); they are handled as one more
   in-order stage, which is exactly right here since the core blocks at WB
   until the result arrives either way.

5. **Result.**  Every accepted+committed instruction produces exactly one
   result transaction -- including instructions that do not write rd, which
   the interface requires to report back with ``we = 0``.

6. **Custom registers.**  ISAX-private register files live in the glue,
   including their initializers.  A conservative admission interlock keeps
   accesses ordered: an instruction touching register R is not admitted while
   an older in-flight instruction still has a pending access to R.  Because
   the pipeline is rigid and in-order, that is sufficient -- no forwarding
   network and no per-stage scoreboard are needed.

Not supported (see the datasheet header for the reasoning): ``RdPC``/``WrPC``,
``RdRD``, ``RdMem``/``WrMem``, ``RdX``/``WrX``, ``MultiRdMem``/``MultiWrMem``,
``always`` blocks, and data-dependent ``WrRD`` valid.  Each is reported with a
diagnostic instead of being silently mis-generated.

Usage
-----
    tools/cvxif_glue_gen.py outputs/run_N/ISAX_FOO.yaml -o outputs/run_N
    tools/cvxif_glue_gen.py outputs/run_N/ISAX_FOO.yaml --sv path/to/ISAX_FOO.sv
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

import yaml

XLEN = 32

# --------------------------------------------------------------------------
# ISAX description (ISAX_<name>.yaml)
# --------------------------------------------------------------------------


class GlueError(Exception):
    """A property of the ISAX that CV-X-IF cannot express."""


@dataclass
class SchedEntry:
    iface: str
    stage: int
    has_valid: bool = False
    has_addr: bool = False
    has_size: bool = False
    decoupled: bool = False


@dataclass
class Instruction:
    name: str
    mask: str
    sharing_group: int | None
    ii: int
    schedule: list[SchedEntry] = field(default_factory=list)

    def uses(self, iface: str) -> bool:
        return any(e.iface == iface for e in self.schedule)

    def stages_of(self, iface: str) -> list[int]:
        return sorted({e.stage for e in self.schedule if e.iface == iface})


@dataclass
class CustReg:
    name: str
    width: int
    elements: int
    read_only: bool = False
    initializer: list[int] | None = None

    @property
    def addr_bits(self) -> int:
        return max(1, (self.elements - 1).bit_length())


@dataclass
class IsaxDesc:
    name: str
    instructions: list[Instruction]
    registers: list[CustReg]
    last_stage: int

    def reg(self, name: str) -> CustReg | None:
        for r in self.registers:
            if r.name == name:
                return r
        return None


def parse_isax_yaml(path: str) -> IsaxDesc:
    with open(path) as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, list):
        raise GlueError(f"{path}: expected a YAML list at the top level")

    name = os.path.basename(path)
    if name.startswith("ISAX_"):
        name = name[len("ISAX_"):]
    name = os.path.splitext(name)[0]

    instructions: list[Instruction] = []
    registers: list[CustReg] = []
    last_stage: int | None = None

    for entry in doc:
        if not isinstance(entry, dict):
            raise GlueError(f"{path}: unexpected list element {entry!r}")
        if "register" in entry:
            registers.append(CustReg(
                name=entry["register"],
                width=int(entry["width"]),
                elements=int(entry.get("elements", 1)),
                read_only=bool(entry.get("read only", False)),
                initializer=entry.get("initializer"),
            ))
        elif "instruction" in entry:
            sched = []
            for s in entry.get("schedule", []) or []:
                sched.append(SchedEntry(
                    iface=s["interface"],
                    stage=int(s["stage"]),
                    has_valid="has valid" in s,
                    has_addr="has addr" in s,
                    has_size="has size" in s,
                    decoupled="is decoupled" in s or "is dynamic decoupled" in s,
                ))
            sg = entry.get("sharing group")
            instructions.append(Instruction(
                name=entry["instruction"],
                mask=entry["mask"],
                sharing_group=None if sg is None else int(sg),
                ii=int(entry.get("II", 1)),
                schedule=sched,
            ))
        elif "always" in entry:
            raise GlueError(
                f"{path}: ISAX '{entry['always']}' is an `always` block. CV-X-IF "
                "only ever hands over instructions; there is no interface through "
                "which a free-running ISAX could observe or drive the core.")
        elif "last stage" in entry:
            last_stage = int(entry["last stage"])
        elif "module" in entry:
            pass
        else:
            raise GlueError(f"{path}: unrecognised entry {sorted(entry)}")

    if not instructions:
        raise GlueError(f"{path}: no instructions")
    if last_stage is None:
        raise GlueError(f"{path}: no `last stage` entry")
    return IsaxDesc(name, instructions, registers, last_stage)


def mask_to_care_value(mask: str) -> tuple[int, int]:
    """Encoding mask (MSB-first, '-' = don't care) -> (care, value) bit masks."""
    if len(mask) != 32:
        raise GlueError(f"encoding mask '{mask}' is {len(mask)} bits, expected 32")
    care = 0
    value = 0
    for i, ch in enumerate(mask):
        bit = 31 - i
        if ch == "-":
            continue
        if ch not in "01":
            raise GlueError(f"encoding mask '{mask}' has an invalid character '{ch}'")
        care |= 1 << bit
        if ch == "1":
            value |= 1 << bit
    return care, value


# --------------------------------------------------------------------------
# ISAX module port list (ISAX_<name>.sv)
# --------------------------------------------------------------------------


@dataclass
class SvPort:
    name: str
    direction: str  # "input" / "output"
    width: int


_PORT_ITEM_RE = re.compile(
    r"^(?:(input|output)\s+(?:wire|logic|reg)?\s*)?"
    r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?"
    r"(\w+)$")


def parse_sv_ports(path: str, module: str) -> list[SvPort]:
    """Port list of `module` in a CIRCT-emitted SystemVerilog file.

    CIRCT groups ports: only the first name of a group carries the direction
    and the range, the rest inherit both.
    """
    with open(path) as f:
        text = f.read()
    text = re.sub(r"//[^\n]*", "", text)
    m = re.search(r"^module\s+" + re.escape(module) + r"\s*\((.*?)\n\s*\);",
                  text, re.S | re.M)
    if not m:
        raise GlueError(f"{path}: could not find the port list of module '{module}'")

    ports: list[SvPort] = []
    direction = None
    width = 1
    for item in m.group(1).split(","):
        item = " ".join(item.split())
        if not item:
            continue
        pm = _PORT_ITEM_RE.match(item)
        if not pm:
            raise GlueError(f"{path}: cannot parse port declaration '{item}'")
        new_dir, msb, lsb, name = pm.groups()
        if new_dir:
            direction = new_dir
            width = 1  # a new group without a range is a 1-bit group
        if msb is not None:
            width = int(msb) - int(lsb) + 1
        elif new_dir:
            width = 1
        if direction is None:
            raise GlueError(f"{path}: port '{name}' has no direction")
        ports.append(SvPort(name, direction, width))
    return ports


# --------------------------------------------------------------------------
# Port classification
# --------------------------------------------------------------------------

# Interface prefixes CV-X-IF cannot serve, with the reason reported to the user.
_UNSUPPORTED_HEADS = {
    "RdPC": "x_issue_req_t carries no program counter",
    "WrPC": "CV-X-IF explicitly excludes control-transfer instructions",
    "RdRD": "the interface offers rs1/rs2 only, there is no read port for rd",
    "RdMem": "the memory (request/response) interface was removed in CV-X-IF v1.0",
    "WrMem": "the memory (request/response) interface was removed in CV-X-IF v1.0",
    "MultiRdMem": "no counterpart in CV-X-IF",
    "MultiWrMem": "no counterpart in CV-X-IF",
    "RdCore": "no counterpart in CV-X-IF",
    "WrCore": "no counterpart in CV-X-IF",
}


@dataclass
class ClassifiedPort:
    port: SvPort
    head: str              # "RdRS1", "WrRD", "WrsignInfo", ...
    owner: str             # instruction name, or "sharegroup<N>"
    instr: str | None      # instruction name, None for shared ports
    group: int | None      # sharing group, None for per-instruction ports
    stage: int
    spawn: bool = False
    kind: str = ""         # "", "validReq", "addr", "size", "validResp"
    reg: str | None = None  # custom register name for Rd<R>/Wr<R> ports


def classify_ports(desc: IsaxDesc, ports: list[SvPort]) -> list[ClassifiedPort]:
    instr_names = sorted((i.name for i in desc.instructions), key=len, reverse=True)
    reg_names = sorted((r.name for r in desc.registers), key=len, reverse=True)
    out: list[ClassifiedPort] = []

    for p in ports:
        if p.name in ("clk_i", "rst_i"):
            continue
        m = re.match(r"^(.*)_(\d+)_(i|o)$", p.name)
        if not m:
            raise GlueError(
                f"ISAX port '{p.name}' does not follow the "
                "<iface>_<owner>_<stage>_<i|o> naming scheme and cannot be "
                "connected by the CV-X-IF glue")
        rest, stage_s, _ = m.groups()
        stage = int(stage_s)

        instr = None
        group = None
        owner = None
        gm = re.match(r"^(.*)_sharegroup(\d+)$", rest)
        if gm:
            head, group = gm.group(1), int(gm.group(2))
            owner = f"sharegroup{group}"
        else:
            for name in instr_names:
                if rest.endswith("_" + name):
                    instr = name
                    owner = name
                    head = rest[: -len(name) - 1]
                    break
            else:
                raise GlueError(
                    f"ISAX port '{p.name}' names neither a known instruction nor a "
                    "sharing group")

        spawn = False
        kind = ""
        for suffix in ("_validResp", "_validReq", "_addr", "_size"):
            if head.endswith(suffix):
                kind = suffix[1:]
                head = head[: -len(suffix)]
                break
        if head.endswith("_spawn"):
            spawn = True
            head = head[: -len("_spawn")]

        reg = None
        if head not in ("RdInstr", "RdRS1", "RdRS2", "RdIValid", "RdStall",
                        "RdFlush", "WrStall", "WrRD"):
            for rn in reg_names:
                if head == "Rd" + rn or head == "Wr" + rn:
                    reg = rn
                    break

        if reg is None and head in _UNSUPPORTED_HEADS:
            raise GlueError(
                f"ISAX port '{p.name}' requests the '{head}' interface, which the "
                f"CV-X-IF glue cannot provide: {_UNSUPPORTED_HEADS[head]}.")
        if reg is None and head not in ("RdInstr", "RdRS1", "RdRS2", "RdIValid",
                                        "RdStall", "RdFlush", "WrStall", "WrRD"):
            raise GlueError(f"ISAX port '{p.name}': unrecognised interface '{head}'")

        out.append(ClassifiedPort(p, head, owner, instr, group, stage,
                                  spawn, kind, reg))
    return out


# --------------------------------------------------------------------------
# SystemVerilog emission
# --------------------------------------------------------------------------


class SvWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str = "") -> None:
        self.lines.append(line)

    def section(self, title: str) -> None:
        self("")
        self("  // " + "-" * 72)
        self(f"  // {title}")
        self("  // " + "-" * 72)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def _sv_hex(value: int, width: int = 32) -> str:
    return f"{width}'h{value:0{(width + 3) // 4}x}"


def _or_terms(terms: list[str], zero: str = "1'b0") -> str:
    if not terms:
        return zero
    if len(terms) == 1:
        return terms[0]
    return "(" + " | ".join(terms) + ")"


class GlueGenerator:
    def __init__(self, desc: IsaxDesc, cports: list[ClassifiedPort],
                 isax_module: str, sources: tuple[str, str],
                 speculative: bool = True, no_input_buffer: bool = True,
                 ooo_result: bool = True):
        self.desc = desc
        self.cports = cports
        self.isax_module = isax_module
        self.sources = sources
        # Speculative admission: start executing at the issue handshake instead
        # of waiting for the commit, and hold the *result* until the commit
        # arrives. CV-X-IF forbids only speculative result transactions, not
        # speculative execution. Requires the ISAX to have no architectural
        # state, since a killed instruction is simply dropped -- there is no
        # rollback.
        # Speculative admission is the DEFAULT: it is both faster (~2.4-2.5x offload
        # throughput) and smaller (no commit-gated input buffer). Custom registers are the
        # one case it cannot serve -- a killed entry is dropped and there is no rollback --
        # so an ISAX that has them falls back to commit-gated admission automatically
        # rather than failing. `--non-speculative` forces the fallback for everyone else.
        self.speculative = speculative and not desc.registers
        # Bypassing the input buffer only works when admission does NOT wait for the
        # commit: in the commit-gated build the buffer IS the wait, and dropping it would
        # hold issue_ready low for the whole issue->commit window, pinning the core's ID
        # stage. It also feeds the core's operand bus combinationally into ISAX stage 0 --
        # measured arriving at ~92% of the period on CV32E40X -- so it trades 125 register
        # bits for the interface's worst timing path. Opt-in, and measure before adopting.
        self.no_input_buffer = no_input_buffer and self.speculative
        if no_input_buffer and not self.speculative:
            print("cvxif_glue_gen: --no-input-buffer needs speculative admission "
                  "(the buffer is the commit-wait in the commit-gated build); keeping it.")
        if speculative and desc.registers:
            print(f"cvxif_glue_gen: '{desc.name}' has {len(desc.registers)} custom register(s) "
                  f"({', '.join(r.name for r in desc.registers)}) -- falling back to "
                  f"commit-gated admission (their writes would be speculative with no way "
                  f"to roll them back on a commit_kill). Pass --non-speculative to silence.")

        self.instrs = desc.instructions
        self.idx = {ins.name: i for i, ins in enumerate(self.instrs)}
        self.n = len(self.instrs)

        stages = [cp.stage for cp in cports]
        self.lmax = max(stages) if stages else 0
        # An ISAX whose WrRD is decoupled lands at `last stage + 1`; the shadow
        # pipeline simply extends that far.
        self.lmax = max(self.lmax, 0)

        self._check_unsupported()

        self.by_head: dict[str, list[ClassifiedPort]] = {}
        for cp in cports:
            self.by_head.setdefault(cp.head, []).append(cp)

        # Which instructions write rd (statically -> issue_resp.writeback).
        self.wb_instrs = sorted({cp.instr for cp in self.by_head.get("WrRD", [])
                                 if cp.kind == "" and cp.instr})
        # Operand needs, for the rs_valid gating at issue.
        self.rs1_instrs = sorted({i.name for i in self.instrs if i.uses("RdRS1")})
        self.rs2_instrs = sorted({i.name for i in self.instrs if i.uses("RdRS2")})

        self.wrrd_at: dict[int, list[ClassifiedPort]] = {}
        for cp in self.by_head.get("WrRD", []):
            if cp.kind == "":
                self.wrrd_at.setdefault(cp.stage, []).append(cp)
        self.min_wr = min(self.wrrd_at) if self.wrrd_at else None
        # Out-of-order result emission: hand each result over at the stage that produces
        # it instead of dragging it to LMAX through 32-bit staging registers. Only sound
        # if no instruction still needs the shadow pipeline AFTER its WrRD -- an entry is
        # retired at the stage it emits from, so a later RdIValid/RdStall for it would
        # never fire. Checked here rather than assumed.
        #
        # And only if EVERY instruction has a WrRD: the result bids are built from the WrRD
        # stages, so an instruction without one (it only writes custom registers, or has no
        # architectural effect at all) would never produce its result transaction. CV-X-IF
        # requires one per accepted+committed instruction, and CV32E40X waits for it in WB
        # regardless of issue_resp.writeback -- ANTDOTP's SETUP hung that core on its first
        # offload. (CV32E40PX only tracks pending writebacks, which hid it there.) The
        # in-order emitter hands every instruction's result over at LMAX, we = 0 included.
        self.ooo_result = ooo_result
        if ooo_result:
            last_wr, last_obs = {}, {}
            for head, cps in self.by_head.items():
                for cp in cps:
                    if head == "WrRD":
                        last_wr[cp.instr] = max(last_wr.get(cp.instr, 0), cp.stage)
                    else:
                        last_obs[cp.instr] = max(last_obs.get(cp.instr, 0), cp.stage)
            bad = [i for i, w in last_wr.items() if last_obs.get(i, 0) > w]
            no_wr = [i.name for i in self.instrs if i.name not in last_wr]
            if bad or no_wr:
                self.ooo_result = False
                if bad:
                    why = (f"{', '.join(sorted(bad)[:3])} observe the interface after their "
                           f"WrRD, so they cannot retire there")
                else:
                    why = (f"{', '.join(sorted(no_wr)[:3])} have no WrRD, so no stage would "
                           f"emit their result")
                print(f"cvxif_glue_gen: --ooo-result not applicable ({why}); "
                      f"keeping in-order emission.")
        # Stages that carry an already-captured result payload: everything past
        # the earliest WrRD. The last stage always feeds the result register.
        # OOO emits at the producing stage, so nothing has to ride to LMAX.
        self.data_stages = set() if self.ooo_result else (
                            set(range(self.min_wr + 1, self.lmax + 1))
                            if self.min_wr is not None else set())
        self.res_sel_stages = (set(self.wrrd_at) if self.ooo_result
                               else {self.lmax} | {s - 1 for s in self.data_stages})

        self.max_stage_of: dict[str, int] = {}
        for head in ("RdRS1", "RdRS2", "RdInstr"):
            st = [cp.stage for cp in self.by_head.get(head, [])]
            if st:
                self.max_stage_of[head] = max(st)

        self._collect_custreg_accesses()

    # ---- validation ----------------------------------------------------

    def _check_unsupported(self) -> None:
        for cp in self.cports:
            if cp.head == "WrRD" and cp.kind == "validReq":
                raise GlueError(
                    f"'{cp.port.name}': instruction '{cp.instr}' writes rd "
                    "conditionally. CV-X-IF requires result.we to equal the "
                    "issue_resp.writeback reported at decode time, so a "
                    "data-dependent writeback cannot be expressed. Make the "
                    "instruction write rd unconditionally.")

    def _collect_custreg_accesses(self) -> None:
        """Per custom register: read/write ports and the admission interlock set."""
        self.cr_reads: dict[str, list[ClassifiedPort]] = {}
        self.cr_writes: dict[str, list[ClassifiedPort]] = {}
        self.cr_rd_addr: dict[tuple[str, str, int], ClassifiedPort] = {}
        self.cr_wr_addr: dict[tuple[str, str], ClassifiedPort] = {}
        self.cr_wr_valid: dict[tuple[str, str, int], ClassifiedPort] = {}
        self.cr_unused: list[ClassifiedPort] = []

        for cp in self.cports:
            if cp.reg is None:
                continue
            is_read = cp.head == "Rd" + cp.reg
            if is_read:
                if cp.kind == "":
                    self.cr_reads.setdefault(cp.reg, []).append(cp)
                elif cp.kind == "addr":
                    self.cr_rd_addr[(cp.reg, cp.instr, cp.stage)] = cp
                elif cp.kind == "validReq":
                    self.cr_unused.append(cp)
                else:
                    raise GlueError(f"'{cp.port.name}': unsupported custom-register "
                                    f"read sub-port '{cp.kind}'")
            else:
                if cp.kind == "":
                    self.cr_writes.setdefault(cp.reg, []).append(cp)
                elif cp.kind == "addr":
                    self.cr_wr_addr[(cp.reg, cp.instr)] = cp
                elif cp.kind == "validReq":
                    self.cr_wr_valid[(cp.reg, cp.instr, cp.stage)] = cp
                else:
                    raise GlueError(f"'{cp.port.name}': unsupported custom-register "
                                    f"write sub-port '{cp.kind}'")

        # (instruction, stage) accesses per register, for the interlock.
        self.cr_access: dict[str, list[tuple[str, int]]] = {}
        # Stages for which the custom-register logic needs an internal
        # instruction-valid vector (write enables + interlock terms).
        self.iv_stages: set[int] = set()
        for r in self.desc.registers:
            reg = r.name
            if r.read_only:
                # A ROM never changes, so no access to it can conflict.
                self.cr_access[reg] = []
                continue
            acc = [(cp.instr, cp.stage) for cp in self.cr_reads.get(reg, [])]
            acc += [(cp.instr, cp.stage) for cp in self.cr_writes.get(reg, [])]
            acc = sorted(set(a for a in acc if a[0]))
            self.cr_access[reg] = acc
            self.iv_stages.update(cp.stage for cp in self.cr_writes.get(reg, []))
            self.iv_stages.update(s for s in range(self.lmax)
                                  if any(a > s for (_, a) in acc))

    # ---- emission ------------------------------------------------------

    def generate(self) -> str:
        w = SvWriter()
        self._header(w)
        self._ports(w)
        self._decode(w)
        # Cross-section signals, declared before ANY section reads them and
        # `assign`ed where their logic lives: Verilator accepts forward
        # references inside a module, Genus' read_hdl (VLOGPT-20) does not.
        w.section("Cross-section wires (defined in their own sections below)")
        w("  wire            ib_pop;")
        w("  wire            ib_block;")
        w("  wire [LMAX:0]   sp_hold;")
        w("  wire            out_stall;")
        self._issue(w)
        # ISAX output wires are referenced by the stall network, the shadow
        # pipeline's result muxes and the result section below. Verilator accepts
        # forward references inside a module; Genus' read_hdl (VLOGPT-20) does
        # not, so declare them before first use.
        self._isax_output_wires(w)
        self._stalls(w)
        self._pipeline(w)
        self._operand_staging(w)
        self._custom_registers(w)
        self._result(w)
        self._isax_instance(w)
        self._assertions(w)
        w("endmodule")
        return w.text()

    def _header(self, w: SvWriter) -> None:
        yaml_src, sv_src = self.sources
        w("// " + "=" * 74)
        w(f"// CV-X-IF glue logic for ISAX '{self.desc.name}'.")
        w("//")
        w("// Generated by tools/cvxif_glue_gen.py -- DO NOT EDIT.")
        w(f"//   ISAX description : {yaml_src}")
        w(f"//   ISAX module      : {sv_src}")
        w("//   Virtual datasheet: deps/longnail/datasheets/CVXIF.yaml")
        w("//")
        w(f"// Shadow pipeline stages : 0 .. {self.lmax}")
        w(f"// Admission              : "
          f"{'speculative (at issue, result held until commit)' if self.speculative else 'commit-gated'}")
        w(f"// Instructions           : {len(self.instrs)}")
        w(f"// Custom registers       : {len(self.desc.registers)}")
        w("//")
        w("// Instructions are admitted into the ISAX pipeline only after the core")
        w("// marked them non-speculative (commit_kill = 0), so nothing inside the")
        w("// ISAX has to be rolled back and RdFlush is tied to 0.")
        w("// " + "=" * 74)
        w("")

    def _ports(self, w: SvWriter) -> None:
        w(f"module cvxif_glue_{self.desc.name} #(")
        w("  parameter int unsigned X_ID_WIDTH  = 4,")
        w("  parameter int unsigned X_NUM_RS    = 2,")
        w("  parameter int unsigned X_RFR_WIDTH = 32,")
        w("  parameter int unsigned X_RFW_WIDTH = 32")
        w(") (")
        w("  input  logic                                 clk_i,")
        w("  input  logic                                 rst_ni,")
        w("")
        w("  // ---- issue interface (cpu -> coprocessor) ----")
        w("  input  logic                                 x_issue_valid_i,")
        w("  output logic                                 x_issue_ready_o,")
        w("  input  logic [31:0]                          x_issue_req_instr_i,")
        w("  /* verilator lint_off UNUSEDSIGNAL */")
        w("  input  logic [1:0]                           x_issue_req_mode_i,  // privilege level: unused")
        w("  /* verilator lint_on UNUSEDSIGNAL */")
        w("  input  logic [X_ID_WIDTH-1:0]                x_issue_req_id_i,")
        w("  input  logic [X_NUM_RS*X_RFR_WIDTH-1:0]      x_issue_req_rs_i,")
        w("  input  logic [X_NUM_RS-1:0]                  x_issue_req_rs_valid_i,")
        w("  output logic                                 x_issue_resp_accept_o,")
        w("  output logic                                 x_issue_resp_writeback_o,")
        w("  output logic                                 x_issue_resp_dualwrite_o,")
        w("  output logic [2:0]                           x_issue_resp_dualread_o,")
        w("  output logic                                 x_issue_resp_loadstore_o,")
        w("  output logic                                 x_issue_resp_ecswrite_o,")
        w("  output logic                                 x_issue_resp_exc_o,")
        w("  // CV-X-IF v1.0 `issue_resp.register_read`: which source registers")
        w("  // this instruction actually needs. Rev 458c8a73 has no such field")
        w("  // (it hands over every operand unconditionally), so the CV32E40X")
        w("  // wrapper leaves this unconnected; CVA6 uses it to decide which")
        w("  // operands to wait for.")
        w("  output logic [X_NUM_RS-1:0]                  x_issue_resp_regread_o,")
        w("")
        w("  // ---- commit interface (cpu -> coprocessor, no ready) ----")
        w("  input  logic                                 x_commit_valid_i,")
        w("  input  logic [X_ID_WIDTH-1:0]                x_commit_id_i,")
        w("  input  logic                                 x_commit_commit_kill_i,")
        w("")
        w("  // ---- result interface (coprocessor -> cpu) ----")
        w("  output logic                                 x_result_valid_o,")
        w("  input  logic                                 x_result_ready_i,")
        w("  output logic [X_ID_WIDTH-1:0]                x_result_id_o,")
        w("  output logic [X_RFW_WIDTH-1:0]               x_result_data_o,")
        w("  output logic [4:0]                           x_result_rd_o,")
        w("  output logic [X_RFW_WIDTH/32-1:0]            x_result_we_o,")
        w("  output logic [5:0]                           x_result_ecsdata_o,")
        w("  output logic [2:0]                           x_result_ecswe_o,")
        w("  output logic                                 x_result_exc_o,")
        w("  output logic [5:0]                           x_result_exccode_o,")
        w("  output logic                                 x_result_err_o,")
        w("  output logic                                 x_result_dbg_o")
        w(");")
        w("")
        w(f"  localparam int unsigned LMAX   = {self.lmax};  // last shadow-pipeline stage")
        w(f"  localparam int unsigned NINSTR = {self.n};")
        # Width of the shadow pipeline's decode index. NINSTR==1 still needs one bit.
        w(f"  localparam int unsigned IDXW   = {max(1, (self.n - 1).bit_length())};"
          f"  // $clog2(NINSTR), the decode carried per stage")
        w("")
        w("  wire isax_rst = ~rst_ni;  // the Longnail ISAX uses an active-high reset")

    def _decode(self, w: SvWriter) -> None:
        w.section("Instruction decode")
        w("  wire [31:0] iw = x_issue_req_instr_i;")
        w("")
        for ins in self.instrs:
            care, value = mask_to_care_value(ins.mask)
            w(f"  // {ins.mask}"
              + (f"   (sharing group {ins.sharing_group}, II {ins.ii})"
                 if ins.sharing_group is not None else ""))
            w(f"  wire dec_{ins.name} = (iw & {_sv_hex(care)}) == {_sv_hex(value)};")
        w("")
        w(f"  wire [NINSTR-1:0] dec = {{"
          + ", ".join(f"dec_{ins.name}" for ins in reversed(self.instrs)) + "};")
        w("  wire dec_any = |dec;")
        w("")
        w("  // Static per-instruction properties the issue response must report.")
        w("  wire dec_wb      = "
          + _or_terms([f"dec_{n}" for n in self.wb_instrs]) + ";")
        w("  wire dec_use_rs1 = "
          + _or_terms([f"dec_{n}" for n in self.rs1_instrs]) + ";")
        w("  wire dec_use_rs2 = "
          + _or_terms([f"dec_{n}" for n in self.rs2_instrs]) + ";")

    def _emit_bypass(self, w: SvWriter) -> None:
        """Input-buffer bypass (--no-input-buffer, speculative only).

        Keeps every `ib_*` NAME so the rest of the generator is unchanged, but drives them
        combinationally from the issue interface instead of from registers: the instruction
        enters stage 0 in its issue cycle rather than one cycle later. `issue_ready` is then
        withheld exactly while stage 0 cannot take it -- which blocks the core's ID stage,
        and with it any instruction behind the ISAX one, for as long as stage 0 is held.
        """
        w("  // --no-input-buffer: no staging register between issue and stage 0.")
        w("  // NOTE: Genus enforces declare-before-use for wires (VLOGPT-20); lint does")
        w("  // not, so everything here is emitted in dependency order on purpose.")
        w("  wire rs_ok = (~dec_use_rs1 | x_issue_req_rs_valid_i[0])")
        w("             & (~dec_use_rs2 | x_issue_req_rs_valid_i[1]);")
        w("  wire [X_ID_WIDTH-1:0] cmt_delta_new = x_commit_id_i - x_issue_req_id_i;")
        w("  wire cmt_older_new  = cmt_delta_new[X_ID_WIDTH-1];")
        w("  wire new_commit_hit = x_commit_valid_i & ~x_commit_commit_kill_i")
        w("                      & ~cmt_older_new;")
        w("")
        w("  wire                  ib_valid_q  = x_issue_valid_i & dec_any & rs_ok;")
        w("  wire [X_ID_WIDTH-1:0] ib_id_q     = x_issue_req_id_i;")
        w("  wire [4:0]            ib_rd_q     = iw[11:7];")
        w("  wire                  ib_we_q     = dec_wb;")
        w("  wire [NINSTR-1:0]     ib_dec_q    = dec;")
        w("  wire [IDXW-1:0]       ib_idx_q    = dec_idx;")
        for head, sig, src in (("RdInstr", "ib_instr_q", "iw"),
                               ("RdRS1", "ib_rs1_q", "issue_rs1"),
                               ("RdRS2", "ib_rs2_q", "issue_rs2")):
            if head in self.max_stage_of:
                w(f"  wire [31:0]           {sig}  = {src};")
        w("")
        w("  // A commit arriving in the issue cycle marks the entry non-speculative")
        w("  // right away; otherwise the shadow pipeline's own tracking takes over.")
        w("  wire ib_commit_q    = new_commit_hit;")
        w("  wire ib_commit_hit  = 1'b0;   // nothing buffered to commit later")
        w("  wire ib_kill        = 1'b0;   // nothing buffered to kill; a kill in the")
        w("                                // issue cycle simply prevents the handshake")
        w("")
        w("  // Ready exactly when stage 0 can take it this cycle.")
        w("  assign x_issue_ready_o = ~dec_any | (~sp_hold[0] & rs_ok & ~ib_block);")
        w("  wire issue_hs = x_issue_valid_i & dec_any & rs_ok & ~sp_hold[0] & ~ib_block;")
        w("  wire _unused_hs = issue_hs;")
        w("")
        w("  // Admission: straight through in the issue cycle. `ib_pop` keeps its name")
        w("  // (the pipeline reads it) but no longer pops anything -- it just marks the")
        w("  // cycle in which the instruction is taken.")
        w("  wire ib_go  = ib_valid_q & ~ib_block & ~ib_kill;")
        w("  assign ib_pop = ib_go & ~sp_hold[0];")
        w("")

    def _issue(self, w: SvWriter) -> None:
        w.section("Issue interface, input buffer and commit gate")
        w("  assign x_issue_resp_accept_o    = dec_any;")
        w("  assign x_issue_resp_writeback_o = dec_wb;")
        w("")
        w("  // Index form of `dec`, encoded once at issue. The shadow pipeline carries")
        w("  // this instead of the one-hot; `dec` itself stays for the issue-time")
        w("  // decisions that read several of its bits at once.")
        w("  logic [IDXW-1:0] dec_idx;")
        w("  always_comb begin")
        w("    dec_idx = '0;")
        w("    for (int unsigned i = 0; i < NINSTR; i++)")
        w("      if (dec[i]) dec_idx = IDXW'(i);")
        w("  end")
        w("  assign x_issue_resp_dualwrite_o = 1'b0;   // X_RFW_WIDTH == XLEN")
        w("  assign x_issue_resp_dualread_o  = 3'b000; // X_RFR_WIDTH == XLEN")
        w("  assign x_issue_resp_loadstore_o = 1'b0;   // no memory interface")
        w("  assign x_issue_resp_ecswrite_o  = 1'b0;")
        w("  assign x_issue_resp_exc_o       = 1'b0;   // no ISAX-side exceptions")
        w("  // Zero-extended when X_NUM_RS > 2: no ISAX reads a third operand.")
        w("  assign x_issue_resp_regread_o   = {dec_use_rs2, dec_use_rs1};")
        w("")
        if "RdRS1" in self.max_stage_of:
            w("  wire [31:0] issue_rs1 = x_issue_req_rs_i[0*X_RFR_WIDTH +: 32];")
        if "RdRS2" in self.max_stage_of:
            w("  wire [31:0] issue_rs2 = x_issue_req_rs_i[1*X_RFR_WIDTH +: 32];")
        if not ({"RdRS1", "RdRS2"} & set(self.max_stage_of)):
            w("  wire _unused_rs = |x_issue_req_rs_i;  // no ISAX reads rs1/rs2")
        w("")
        if self.no_input_buffer:
            self._emit_bypass(w)
            return
        w("  logic                  ib_valid_q;   // input buffer occupied")
        w("  logic                  ib_commit_q;  // ... and non-speculative")
        w("  logic [X_ID_WIDTH-1:0] ib_id_q;")
        w("  logic [4:0]            ib_rd_q;")
        w("  logic                  ib_we_q;")
        w("  logic [NINSTR-1:0]     ib_dec_q;")
        w("  logic [IDXW-1:0]       ib_idx_q;")
        for head, sig in (("RdInstr", "ib_instr_q"), ("RdRS1", "ib_rs1_q"),
                          ("RdRS2", "ib_rs2_q")):
            if head in self.max_stage_of:
                w(f"  logic [31:0]           {sig};")
        w("")
        w("  // Operands are handed over exactly once, at issue: do not complete the")
        w("  // handshake before the ones this instruction needs are valid.")
        w("  wire rs_ok = (~dec_use_rs1 | x_issue_req_rs_valid_i[0])")
        w("             & (~dec_use_rs2 | x_issue_req_rs_valid_i[1]);")
        w("")
        w("  wire ib_free  = ~ib_valid_q | ib_pop;")
        w("  // Instructions we do not implement are rejected in the same cycle so the")
        w("  // core never stalls on us.")
        w("  assign x_issue_ready_o = ~dec_any | (ib_free & rs_ok);")
        w("  wire issue_hs = x_issue_valid_i & dec_any & ib_free & rs_ok;")
        w("")
        w("  // Age comparison in the wrapping id space (ids are allocated")
        w("  // incrementally and the in-flight window is far smaller than half the")
        w("  // id space): the modular difference lands in the negative half exactly")
        w("  // when commit.id is older.")
        w("  wire [X_ID_WIDTH-1:0] cmt_delta_ib  = x_commit_id_i - ib_id_q;")
        w("  wire [X_ID_WIDTH-1:0] cmt_delta_new = x_commit_id_i - x_issue_req_id_i;")
        w("  wire cmt_older_ib = cmt_delta_ib[X_ID_WIDTH-1];  // strictly older")
        w("  wire cmt_same_ib  = ~(|cmt_delta_ib);")
        w("  wire cmt_older_new = cmt_delta_new[X_ID_WIDTH-1];")
        w("")
        w("  // A kill is honoured only for the buffered instruction's OWN id.")
        w("  //")
        w("  // The spec also says a commit_kill kills every *newer* instruction, but")
        w("  // acting on that is unsafe against CV32E40X: it raises commit_kill for")
        w("  // every instruction the coprocessor rejects (`kill_rejected`) -- including")
        w("  // legal CSR accesses, which it offers on the issue interface and then")
        w("  // executes normally *without* flushing the pipeline. Killing newer")
        w("  // entries on such a commit would drop an ISAX instruction the core still")
        w("  // expects a result for, and the core would wait at WB forever.")
        w("  //")
        w("  // Safe, because the core marks every issue transaction individually: when")
        w("  // it really does flush, the buffered instruction receives its own")
        w("  // commit_kill (observed: a rejected illegal instruction traps, and both")
        w("  // its id and the speculatively accepted id behind it are killed by id).")
        w("  wire ib_kill = x_commit_valid_i &  x_commit_commit_kill_i")
        w("               & ib_valid_q & ~ib_commit_q & cmt_same_ib;")
        w("  // commit_kill=0 marks that instruction AND every older one non-speculative,")
        w("  // so the buffer is committed by its own id or by any newer one.")
        w("  wire ib_commit_hit = x_commit_valid_i & ~x_commit_commit_kill_i")
        w("                     & ib_valid_q & ~cmt_older_ib;")
        w("  // Same, for an instruction being latched in this very cycle.")
        w("  wire new_commit_hit = x_commit_valid_i & ~x_commit_commit_kill_i")
        w("                      & ~cmt_older_new;")
        w("")
        w("  always_ff @(posedge clk_i or negedge rst_ni) begin")
        w("    if (!rst_ni) begin")
        w("      ib_valid_q  <= 1'b0;")
        w("      ib_commit_q <= 1'b0;")
        w("    end else if (ib_kill) begin")
        w("      ib_valid_q  <= 1'b0;")
        w("      ib_commit_q <= 1'b0;")
        w("    end else if (issue_hs) begin")
        w("      ib_valid_q  <= 1'b1;")
        w("      ib_commit_q <= new_commit_hit;")
        w("      ib_id_q     <= x_issue_req_id_i;")
        w("      ib_rd_q     <= iw[11:7];")
        w("      ib_we_q     <= dec_wb;")
        w("      ib_dec_q    <= dec;")
        w("      ib_idx_q    <= dec_idx;")
        for head, sig, src in (("RdInstr", "ib_instr_q", "iw"),
                               ("RdRS1", "ib_rs1_q", "issue_rs1"),
                               ("RdRS2", "ib_rs2_q", "issue_rs2")):
            if head in self.max_stage_of:
                w(f"      {sig}  <= {src};")
        w("    end else if (ib_pop) begin")
        w("      ib_valid_q  <= 1'b0;")
        w("      ib_commit_q <= 1'b0;")
        w("    end else if (ib_commit_hit) begin")
        w("      ib_commit_q <= 1'b1;")
        w("    end")
        w("  end")
        w("")
        if self.speculative:
            w("  // Speculative admission: enter the ISAX pipeline at the issue")
            w("  // handshake. The commit is tracked per entry instead and gates")
            w("  // only the result transaction (see below).")
            w("  // ~ib_kill matters here and not in the commit-gated build: there,")
            w("  // ib_go requires ib_commit_q and ib_kill requires ~ib_commit_q, so")
            w("  // the two are mutually exclusive. Admitting on the same cycle as a")
            w("  // kill would leave the entry in the pipeline with no commit coming.")
            w("  wire ib_go  = ib_valid_q & ~ib_block & ~ib_kill;")
        else:
            w("  wire ib_go  = ib_valid_q & ib_commit_q & ~ib_block;")
        w("  assign ib_pop = ib_go & ~sp_hold[0];")

    def _ooo_arb_decl(self, w: SvWriter) -> None:
        """Declare the arbitration wires ahead of the stall chain that consumes them.

        Section order is issue -> stalls -> pipeline -> result, but the grants depend on
        pipeline state while the stall chain depends on the grants. Genus only requires
        DECLARE-before-use (VLOGPT-20), not assign-before-use, so the declarations go here
        and the assignments with the result logic, after the pipeline exists. Lint accepts
        either order, which is why linting alone did not catch the original bug.
        """
        w.section("Result arbitration (out-of-order) -- declarations")
        for st in sorted(self.wrrd_at, reverse=True):
            w(f"  wire res_here_{st};")
            w(f"  wire res_cand_{st};")
            w(f"  wire res_gnt_{st};")
        w("  wire res_any;")

    def _ooo_arb_assign(self, w: SvWriter) -> None:
        """Drive the wires declared by `_ooo_arb_decl` (needs the pipeline to exist)."""
        stages = sorted(self.wrrd_at, reverse=True)   # deepest first = oldest first
        w.section("Result arbitration (out-of-order)")
        w("  // `res_here` = the entry currently in this stage is one whose WrRD is HERE.")
        w("  // Every stage is traversed by every instruction, so liveness alone would")
        w("  // stall entries that are only passing through.")
        for st in stages:
            live = f"sp_live_{st}" if self.speculative else f"sp_valid_q[{st}]"
            idxs = sorted({self.idx[cp.instr] for cp in self.wrrd_at[st]})
            sel = " | ".join(f"(sp_idx_q[{st}] == IDXW'({i}))" for i in idxs)
            w(f"  assign res_here_{st} = {live} & ({sel});")
        w("")
        for st in stages:
            cmt = f" & sp_cmt_eff_{st}" if self.speculative else ""
            w(f"  assign res_cand_{st} = res_here_{st}{cmt};")
        w("")
        w("  // Fixed priority, deepest first.")
        older: list[str] = []
        for st in stages:
            blocked = "".join(f" & ~res_cand_{o}" for o in older)
            w(f"  assign res_gnt_{st} = ~out_stall & res_cand_{st}{blocked};")
            older.append(st)
        w("")
        w("  assign res_any = " + " | ".join(f"res_gnt_{st}" for st in stages) + ";")

    def _stalls(self, w: SvWriter) -> None:
        if self.ooo_result:
            self._ooo_arb_decl(w)
        w.section("Stall chain")
        w("  // RdStall of a stage must NOT contain that stage's own WrStall (SCAIE-V")
        w("  // core-interface contract); it carries everything downstream of it.")
        w("  wire [LMAX:0] sp_wrstall;")
        w("  wire [LMAX:0] sp_rdstall;")
        w("  assign sp_hold = sp_rdstall | sp_wrstall;")
        w("")
        for s in range(self.lmax + 1):
            terms = [f"{cp.port.name}_w"
                     for cp in self.by_head.get("WrStall", []) if cp.stage == s]
            # OOO: a stage that has a result ready but lost the arbitration for the single
            # result port holds its entry in place. No FIFO -- the shadow pipeline itself
            # is the buffer, which is why the loser must stall rather than be dropped.
            if self.ooo_result and s in self.wrrd_at:
                # res_here, NOT res_cand: an uncommitted entry is not bidding yet, but it
                # still must not advance past the only stage that can emit its result.
                terms.append(f"(res_here_{s} & ~res_gnt_{s})")
            w(f"  assign sp_wrstall[{s}] = " + _or_terms(sorted(terms)) + ";")
        w("")
        w("  // The only external back-pressure is the result port.")
        w(f"  assign sp_rdstall[{self.lmax}] = out_stall;")
        for s in range(self.lmax - 1, -1, -1):
            w(f"  assign sp_rdstall[{s}] = sp_rdstall[{s + 1}] | sp_wrstall[{s + 1}];")

    def _res_sel(self, stage: int) -> str:
        """Result payload of the instruction leaving `stage`."""
        base = f"sp_data_q[{stage}]" if stage in self.data_stages else "32'h0"
        expr = base
        for cp in sorted(self.wrrd_at.get(stage, []), key=lambda c: c.port.name):
            expr = (f"(sp_idx_q[{stage}] == IDXW'({self.idx[cp.instr]})) ? "
                    f"{cp.port.name}_w : {expr}")
        return expr

    def _pipeline(self, w: SvWriter) -> None:
        w.section("Shadow pipeline")
        w("  logic [LMAX:0]         sp_valid_q;")
        w("  logic [X_ID_WIDTH-1:0] sp_id_q   [0:LMAX];")
        w("  logic [4:0]            sp_rd_q   [0:LMAX];")
        w("  logic                  sp_we_q   [0:LMAX];")
        # The decode rides the shadow pipeline as an INDEX, not as a one-hot: it is the
        # widest field by far (NINSTR bits vs IDXW), and it is replicated across every
        # stage with a stall-hold mux on each bit. Consumers need at most one bit of it at
        # a time, so an equality compare against the index reconstructs what they used to
        # read from the one-hot -- (NINSTR - IDXW) flops and hold muxes saved per stage.
        w("  logic [IDXW-1:0]       sp_idx_q  [0:LMAX];")
        if self.speculative:
            w("  // Per-entry commit status. An entry may sit anywhere in the")
            w("  // pipeline when its commit transaction arrives.")
            w("  logic                  sp_cmt_q  [0:LMAX];")
        if self.data_stages:
            w("  // Result payload, captured at the WrRD stage and carried to the end.")
            w(f"  logic [31:0]           sp_data_q [{min(self.data_stages)}:LMAX];")
        w("")
        for s in sorted(self.res_sel_stages):
            w(f"  wire [31:0] sp_res_sel_{s} = {self._res_sel(s)};")
        w("")
        if self.speculative:
            w("  // Commit / kill matching by id against every in-flight entry: an")
            w("  // entry may sit anywhere in the pipeline when its commit arrives.")
            w("  // A killed entry is dropped in place and does not propagate.")
            for s in range(self.lmax + 1):
                w(f"  wire sp_cmt_hit_{s} = x_commit_valid_i & ~x_commit_commit_kill_i"
                  f" & sp_valid_q[{s}] & (x_commit_id_i == sp_id_q[{s}]);")
                w(f"  wire sp_kill_{s}    = x_commit_valid_i &  x_commit_commit_kill_i"
                  f" & sp_valid_q[{s}] & (x_commit_id_i == sp_id_q[{s}]);")
                w(f"  wire sp_live_{s}    = sp_valid_q[{s}] & ~sp_kill_{s};")
                w(f"  wire sp_cmt_eff_{s} = sp_cmt_q[{s}] | sp_cmt_hit_{s};")
            w("")
        w("  always_ff @(posedge clk_i or negedge rst_ni) begin")
        w("    if (!rst_ni) begin")
        w("      sp_valid_q <= '0;")
        w("    end else begin")
        for s in range(self.lmax + 1):
            live_prev = (f"sp_live_{s - 1}" if self.speculative
                         else f"sp_valid_q[{s - 1}]")
            # OOO: the entry that just handed its result over is done -- retire it here
            # instead of shifting it on. Sound because no instruction observes the
            # interface after its WrRD (checked in __init__).
            retire = (f" & ~res_gnt_{s - 1}"
                      if self.ooo_result and (s - 1) in self.wrrd_at else "")
            src_valid = ("ib_go" if s == 0
                         else f"{live_prev} & ~sp_hold[{s - 1}]{retire}")
            w(f"      if (!sp_hold[{s}]) begin")
            w(f"        sp_valid_q[{s}] <= {src_valid};")
            if self.speculative:
                src_cmt = ("(ib_commit_q | ib_commit_hit)" if s == 0
                           else f"sp_cmt_eff_{s - 1}")
                w(f"        sp_cmt_q[{s}]   <= {src_cmt};")
            if s == 0:
                w(f"        sp_id_q[0]      <= ib_id_q;")
                w(f"        sp_rd_q[0]      <= ib_rd_q;")
                w(f"        sp_we_q[0]      <= ib_we_q;")
                w(f"        sp_idx_q[0]     <= ib_idx_q;")
            else:
                w(f"        sp_id_q[{s}]      <= sp_id_q[{s - 1}];")
                w(f"        sp_rd_q[{s}]      <= sp_rd_q[{s - 1}];")
                w(f"        sp_we_q[{s}]      <= sp_we_q[{s - 1}];")
                w(f"        sp_idx_q[{s}]     <= sp_idx_q[{s - 1}];")
                if s in self.data_stages:
                    w(f"        sp_data_q[{s}]    <= sp_res_sel_{s - 1};")
            if self.speculative:
                # Stalled: absorb a kill in place, and a commit that arrives
                # while the entry is waiting.
                w("      end else begin")
                w(f"        if (sp_kill_{s})    sp_valid_q[{s}] <= 1'b0;")
                w(f"        if (sp_cmt_hit_{s}) sp_cmt_q[{s}]   <= 1'b1;")
            w("      end")
        w("    end")
        w("  end")
        w("")
        w("  // Per-instruction, per-stage instruction-valid for the ISAX.")
        for cp in sorted(self.by_head.get("RdIValid", []), key=lambda c: c.port.name):
            w(f"  wire {cp.port.name}_w = sp_valid_q[{cp.stage}] "
              f"& (sp_idx_q[{cp.stage}] == IDXW'({self.idx[cp.instr]}));")
        if self.iv_stages:
            w("")
            w("  // Internal instruction-valid, also for stages the ISAX does not")
            w("  // observe -- the custom-register write enables and the admission")
            w("  // interlock are built from these. Kept full-width for readability;")
            w("  // only the bits of instructions touching a register are consumed.")
            w("  /* verilator lint_off UNUSEDSIGNAL */")
            for s in sorted(self.iv_stages):
                # one decoder per stage that needs the full vector, instead of carrying it
                w(f"  wire [NINSTR-1:0] iv_{s} = "
                  f"sp_valid_q[{s}] ? (NINSTR'(1) << sp_idx_q[{s}]) : NINSTR'(0);")
            w("  /* verilator lint_on UNUSEDSIGNAL */")

    def _operand_staging(self, w: SvWriter) -> None:
        heads = [h for h in ("RdRS1", "RdRS2", "RdInstr") if h in self.max_stage_of]
        if not heads:
            return
        w.section("Operand / instruction-word staging")
        w("  // CV-X-IF hands the operands over once, at issue. Reads past stage 0 need")
        w("  // a shadow register per stage -- which is exactly what the datasheet's")
        w("  // `costly: 1` prices in, so Longnail normally reads them at stage 0.")
        src = {"RdRS1": "ib_rs1_q", "RdRS2": "ib_rs2_q", "RdInstr": "ib_instr_q"}
        sig = {"RdRS1": "stg_rs1", "RdRS2": "stg_rs2", "RdInstr": "stg_instr"}
        for head in heads:
            top = self.max_stage_of[head]
            w("")
            w(f"  logic [31:0] {sig[head]}_q [0:{top}];")
            w("  always_ff @(posedge clk_i) begin")
            for s in range(top + 1):
                rhs = src[head] if s == 0 else f"{sig[head]}_q[{s - 1}]"
                w(f"    if (!sp_hold[{s}]) {sig[head]}_q[{s}] <= {rhs};")
            w("  end")
            for cp in sorted(self.by_head.get(head, []), key=lambda c: c.port.name):
                w(f"  wire [31:0] {cp.port.name}_w = {sig[head]}_q[{cp.stage}];")

    def _custom_registers(self, w: SvWriter) -> None:
        if not self.desc.registers:
            w("")
            w("  assign ib_block = 1'b0;  // no custom registers, nothing to interlock")
            return

        w.section("ISAX-private custom registers")
        w("  // The register files live here, not in the ISAX. Admission is interlocked:")
        w("  // an instruction touching register R is not admitted while an older")
        w("  // in-flight instruction still has a pending access to R. With a rigid")
        w("  // in-order pipeline that alone orders all accesses correctly -- no")
        w("  // forwarding network and no per-stage scoreboard needed.")

        block_terms = []
        for reg in self.desc.registers:
            r = reg.name
            w("")
            w(f"  // ---- register {r} ({reg.width} bit x {reg.elements}"
              + (", read only" if reg.read_only else "") + ") ----")

            init = reg.initializer or []
            writes = sorted(self.cr_writes.get(r, []), key=lambda c: c.port.name)
            if reg.read_only and writes:
                raise GlueError(f"custom register '{r}' is declared read-only but the "
                                f"ISAX drives {writes[0].port.name}")

            if reg.read_only:
                # A ROM: constant, so it needs neither flops nor an interlock
                # (its value cannot change under an in-flight instruction).
                self._emit_rom(w, reg, init)
                continue

            single = reg.elements == 1
            if single:
                w(f"  logic [{reg.width - 1}:0] cr_{r}_q;")
            else:
                w(f"  logic [{reg.width - 1}:0] cr_{r}_q [0:{reg.elements - 1}];")

            # --- write ports ------------------------------------------------
            wr_infos = []
            for cp in writes:
                en_terms = [f"iv_{cp.stage}[{self.idx[cp.instr]}]",
                            f"~sp_hold[{cp.stage}]"]
                vld = self.cr_wr_valid.get((r, cp.instr, cp.stage))
                if vld is not None:
                    en_terms.append(f"{vld.port.name}_w")
                en = f"cr_we_{r}_{cp.instr}_{cp.stage}"
                w(f"  wire {en} = " + " & ".join(en_terms) + ";")
                addr_expr = None
                if not single:
                    ap = self.cr_wr_addr.get((r, cp.instr))
                    if ap is None:
                        raise GlueError(
                            f"custom register '{r}' has {reg.elements} elements but "
                            f"instruction '{cp.instr}' provides no write address port")
                    addr_expr = self._staged_addr(w, ap, cp.stage, reg)
                wr_infos.append((en, cp, addr_expr))

            # --- state ------------------------------------------------------
            w("  always_ff @(posedge clk_i or negedge rst_ni) begin")
            w("    if (!rst_ni) begin")
            if single:
                v = init[0] if init else 0
                w(f"      cr_{r}_q <= {reg.width}'d{v};")
            else:
                for e in range(reg.elements):
                    v = init[e] if e < len(init) else 0
                    w(f"      cr_{r}_q[{e}] <= {reg.width}'d{v};")
            w("    end else begin")
            if not wr_infos:
                w("      // read-only: no write ports")
            for en, cp, addr_expr in wr_infos:
                tgt = f"cr_{r}_q" if single else f"cr_{r}_q[{addr_expr}]"
                w(f"      if ({en}) {tgt} <= {cp.port.name}_w;")
            w("    end")
            w("  end")

            # --- read ports -------------------------------------------------
            for cp in sorted(self.cr_reads.get(r, []), key=lambda c: c.port.name):
                if single:
                    w(f"  wire [{reg.width - 1}:0] {cp.port.name}_w = cr_{r}_q;")
                else:
                    ap = self.cr_rd_addr.get((r, cp.instr, cp.stage))
                    if ap is None:
                        raise GlueError(
                            f"custom register '{r}' has {reg.elements} elements but "
                            f"'{cp.port.name}' comes without a read address port")
                    w(f"  wire [{reg.width - 1}:0] {cp.port.name}_w = "
                      f"cr_{r}_q[{ap.port.name}_w];")

            # --- interlock --------------------------------------------------
            acc = self.cr_access.get(r, [])
            busy_terms = []
            for s in range(self.lmax):
                later = sorted({i for (i, a) in acc if a > s})
                if later:
                    busy_terms.append("(" + " | ".join(
                        f"iv_{s}[{self.idx[i]}]" for i in later) + ")")
            touch = sorted({i for (i, _) in acc})
            if busy_terms and touch:
                w(f"  wire cr_busy_{r}  = " + " | ".join(busy_terms) + ";")
                w(f"  wire cr_touch_{r} = " + " | ".join(
                    f"ib_dec_q[{self.idx[i]}]" for i in touch) + ";")
                block_terms.append(f"(cr_touch_{r} & cr_busy_{r})")
            else:
                w(f"  // {r}: every access happens in stage 0 -- no interlock needed.")

        w("")
        w("  assign ib_block = " + _or_terms(block_terms) + ";")

    def _emit_rom(self, w: SvWriter, reg: CustReg, init: list[int]) -> None:
        """A read-only custom register: a constant, not a bank of flops."""
        r = reg.name
        vals = [init[e] if e < len(init) else 0 for e in range(reg.elements)]
        if reg.elements == 1:
            w(f"  localparam logic [{reg.width - 1}:0] CR_{r}_ROM = "
              f"{reg.width}'d{vals[0]};")
        else:
            w(f"  localparam logic [{reg.width - 1}:0] CR_{r}_ROM [0:{reg.elements - 1}]"
              " = '{")
            items = [f"{reg.width}'d{v}" for v in vals]
            for i in range(0, len(items), 6):
                row = ", ".join(items[i:i + 6])
                w(f"    {row}" + ("," if i + 6 < len(items) else ""))
            w("  };")
        for cp in sorted(self.cr_reads.get(r, []), key=lambda c: c.port.name):
            if reg.elements == 1:
                w(f"  wire [{reg.width - 1}:0] {cp.port.name}_w = CR_{r}_ROM;")
            else:
                ap = self.cr_rd_addr.get((r, cp.instr, cp.stage))
                if ap is None:
                    raise GlueError(
                        f"custom register '{r}' has {reg.elements} elements but "
                        f"'{cp.port.name}' comes without a read address port")
                w(f"  wire [{reg.width - 1}:0] {cp.port.name}_w = "
                  f"CR_{r}_ROM[{ap.port.name}_w];")

    def _staged_addr(self, w: SvWriter, addr_port: ClassifiedPort,
                     data_stage: int, reg: CustReg) -> str:
        """Pipeline a write address from its own stage to the data stage."""
        if addr_port.stage > data_stage:
            raise GlueError(
                f"'{addr_port.port.name}' is scheduled after its data port "
                f"(stage {addr_port.stage} > {data_stage})")
        if addr_port.stage == data_stage:
            return f"{addr_port.port.name}_w"
        base = f"cra_{reg.name}_{addr_port.instr}"
        w(f"  logic [{reg.addr_bits - 1}:0] {base}_q [{addr_port.stage}:{data_stage - 1}];")
        w("  always_ff @(posedge clk_i) begin")
        for s in range(addr_port.stage, data_stage):
            rhs = f"{addr_port.port.name}_w" if s == addr_port.stage else f"{base}_q[{s - 1}]"
            w(f"    if (!sp_hold[{s}]) {base}_q[{s}] <= {rhs};")
        w("  end")
        return f"{base}_q[{data_stage - 1}]"

    def _result_ooo(self, w: SvWriter) -> None:
        """Out-of-order result emission: each WrRD stage bids for the single result port.

        Priority is deepest-stage-first, which is age order (a deeper entry was admitted
        earlier), so a loser is at most one stage from winning and cannot starve. Losers
        stall in place via sp_wrstall -- the shadow pipeline is the buffer, so no result
        FIFO is needed. A winner retires at its stage rather than riding to LMAX, which is
        what removes the 32-bit staging registers this whole path used to need.
        """
        self._ooo_arb_assign(w)
        w.section("Result interface (out-of-order)")
        stages = sorted(self.wrrd_at, reverse=True)   # deepest first = oldest first
        w("  logic                  res_valid_q;")
        w("  logic [X_ID_WIDTH-1:0] res_id_q;")
        w("  logic [4:0]            res_rd_q;")
        w("  logic                  res_we_q;")
        w("  logic [31:0]           res_data_q;")
        w("")
        w("  // The register is free when it is empty or being drained this cycle.")
        w("  wire res_accept = res_valid_q & x_result_ready_i;")
        w("  assign out_stall = res_valid_q & ~res_accept;")
        w("")
        w("  always_ff @(posedge clk_i or negedge rst_ni) begin")
        w("    if (!rst_ni) begin")
        w("      res_valid_q <= 1'b0;")
        w("    end else if (!out_stall) begin")
        w("      res_valid_q <= res_any;")
        for fld, src in (("res_id_q", "sp_id_q"), ("res_rd_q", "sp_rd_q"),
                         ("res_we_q", "sp_we_q")):
            expr = "'0"
            for st in reversed(stages):
                expr = f"res_gnt_{st} ? {src}[{st}] : {expr}"
            w(f"      {fld}    <= {expr};")
        expr = "32'h0"
        for st in reversed(stages):
            expr = f"res_gnt_{st} ? sp_res_sel_{st} : {expr}"
        w(f"      res_data_q  <= {expr};")
        w("    end")
        w("  end")
        w("")
        # Candidates are gated on the commit, so what sits in the register is already
        # non-speculative: no res_cmt_q / res_kill machinery is needed here.
        w("  assign x_result_valid_o   = res_valid_q;")

    def _result(self, w: SvWriter) -> None:
        if self.ooo_result:
            self._result_ooo(w)
            self._result_tail(w)
            return
        w.section("Result interface")
        w("  // Every accepted+committed instruction produces exactly one result")
        w("  // transaction -- also the ones that do not write rd (we = 0).")
        w("  logic                  res_valid_q;")
        w("  logic [X_ID_WIDTH-1:0] res_id_q;")
        w("  logic [4:0]            res_rd_q;")
        w("  logic                  res_we_q;")
        w("  logic [31:0]           res_data_q;")
        w("")
        L = self.lmax
        if self.speculative:
            w("  // A result may only be handed over once the core has marked the")
            w("  // instruction non-speculative, so the holding register carries the")
            w("  // commit status and waits for it if it has not arrived yet.")
            w("  logic                  res_cmt_q;")
            w("  wire res_cmt_hit = x_commit_valid_i & ~x_commit_commit_kill_i")
            w("                   & res_valid_q & (x_commit_id_i == res_id_q);")
            w("  wire res_kill    = x_commit_valid_i &  x_commit_commit_kill_i")
            w("                   & res_valid_q & (x_commit_id_i == res_id_q);")
            w("  wire res_go     = res_valid_q & (res_cmt_q | res_cmt_hit);")
            w("  wire res_accept = res_go & x_result_ready_i;")
            w("  assign out_stall  = res_valid_q & ~res_accept;")
            w("")
            w("  always_ff @(posedge clk_i or negedge rst_ni) begin")
            w("    if (!rst_ni) begin")
            w("      res_valid_q <= 1'b0;")
            w("      res_cmt_q   <= 1'b0;")
            w("    end else if (!out_stall) begin")
            w(f"      res_valid_q <= sp_live_{L};")
            w(f"      res_cmt_q   <= sp_cmt_eff_{L};")
            w(f"      res_id_q    <= sp_id_q[{L}];")
            w(f"      res_rd_q    <= sp_rd_q[{L}];")
            w(f"      res_we_q    <= sp_we_q[{L}];")
            w(f"      res_data_q  <= sp_res_sel_{L};")
            w("    end else begin")
            w("      if (res_kill)    res_valid_q <= 1'b0;")
            w("      if (res_cmt_hit) res_cmt_q   <= 1'b1;")
            w("    end")
            w("  end")
            w("")
            w("  assign x_result_valid_o   = res_go;")
        else:
            w("  assign out_stall = res_valid_q & ~x_result_ready_i;")
            w("")
            w("  always_ff @(posedge clk_i or negedge rst_ni) begin")
            w("    if (!rst_ni) begin")
            w("      res_valid_q <= 1'b0;")
            w("    end else if (!out_stall) begin")
            w(f"      res_valid_q <= sp_valid_q[{L}];")
            w(f"      res_id_q    <= sp_id_q[{L}];")
            w(f"      res_rd_q    <= sp_rd_q[{L}];")
            w(f"      res_we_q    <= sp_we_q[{L}];")
            w(f"      res_data_q  <= sp_res_sel_{L};")
            w("    end")
            w("  end")
            w("")
            w("  assign x_result_valid_o   = res_valid_q;")
        self._result_tail(w)

    def _result_tail(self, w: SvWriter) -> None:
        """Interface assignments shared by the in-order and out-of-order emitters."""
        w("  assign x_result_id_o      = res_id_q;")
        w("  assign x_result_data_o    = X_RFW_WIDTH'(res_data_q);")
        # rd and we are gated with result_valid on purpose. The spec leaves the
        # result fields undefined while result_valid is 0, but CV32E40PX reads
        # rd anyway: cv32e40px_x_disp.sv suppresses its RAW stall with
        #   dep = regs_used & scoreboard[rs] & (x_result_rd_i != rs)
        # -- no `& x_result_valid_i`. Holding the previous transaction's rd
        # therefore cancels the interlock for the *next* instruction writing the
        # same register, and a dependent instruction reads the register one
        # writeback too early (measured: every result shifted by one). Driving
        # zero between transactions costs 5 gates and makes the term harmless.
        w("  assign x_result_rd_o      = res_valid_q ? res_rd_q : 5'b0;")
        w("  assign x_result_we_o      = res_valid_q ? (X_RFW_WIDTH/32)'(res_we_q)")
        w("                                          : (X_RFW_WIDTH/32)'(1'b0);")
        w("  assign x_result_ecsdata_o = 6'b0;")
        w("  assign x_result_ecswe_o   = 3'b0;")
        w("  assign x_result_exc_o     = 1'b0;")
        w("  assign x_result_exccode_o = 6'b0;")
        w("  assign x_result_err_o     = 1'b0;")
        w("  assign x_result_dbg_o     = 1'b0;")

    def _isax_output_wires(self, w: SvWriter) -> None:
        w.section("ISAX outputs")
        # One wire per ISAX output, declared BEFORE any section that reads them
        # (Genus rejects forward references). Custom-register read requests have
        # no effect on a plain register file, so those are deliberately left
        # dangling.
        ignored = {cp.port.name for cp in self.cr_unused}
        for cp in self.cports:
            if cp.port.direction != "output":
                continue
            width = cp.port.width
            decl = "wire" + (f" [{width - 1}:0]" if width > 1 else "")
            if cp.port.name in ignored:
                w("  /* verilator lint_off UNUSEDSIGNAL */")
                w(f"  {decl} {cp.port.name}_w;  // read request: no effect on a "
                  "register file")
                w("  /* verilator lint_on UNUSEDSIGNAL */")
            else:
                w(f"  {decl} {cp.port.name}_w;")

    def _isax_instance(self, w: SvWriter) -> None:
        w.section("ISAX instance")
        w("  // RdFlush is constant 0: nothing in the shadow pipeline is speculative.")
        w(f"  {self.isax_module} u_isax (")
        conns = ["    .clk_i (clk_i)", "    .rst_i (isax_rst)"]
        for cp in self.cports:
            conns.append(f"    .{cp.port.name} ({self._connect(cp)})")
        w(",\n".join(conns))
        w("  );")

    def _connect(self, cp: ClassifiedPort) -> str:
        if cp.port.direction == "output":
            return cp.port.name + "_w"
        if cp.head == "RdStall":
            return f"sp_rdstall[{cp.stage}]"
        if cp.head == "RdFlush":
            return f"{cp.port.width}'b0"
        return cp.port.name + "_w"

    def _assertions(self, w: SvWriter) -> None:
        w.section("Simulation-only checks")
        w("`ifndef SYNTHESIS")
        w("  /* verilator lint_off SYNCASYNCNET */  // rst_ni is only sampled here")
        w("  initial begin")
        w("    if (X_NUM_RS < 2)")
        w("      $fatal(1, \"cvxif_glue: X_NUM_RS must be >= 2\");")
        w("    if (X_RFR_WIDTH != 32 || X_RFW_WIDTH != 32)")
        w("      $fatal(1, \"cvxif_glue: only X_RFR_WIDTH == X_RFW_WIDTH == 32 is "
          "supported (no dual read/write)\");")
        w("  end")
        w("")
        w("  always_ff @(posedge clk_i) begin")
        w("    if (rst_ni) begin")
        w("      // Encoding masks must stay mutually exclusive.")
        w("      if (x_issue_valid_i && !$onehot0(dec))")
        w("        $error(\"cvxif_glue: instruction %08x matches several ISAX "
          "encodings\", iw);")
        for reg in self.desc.registers:
            writes = sorted(self.cr_writes.get(reg.name, []), key=lambda c: c.port.name)
            if len(writes) < 2:
                continue
            ens = ", ".join(f"cr_we_{reg.name}_{cp.instr}_{cp.stage}"
                            for cp in reversed(writes))
            w(f"      // The admission interlock must keep the {reg.name} write ports "
              "exclusive.")
            w(f"      if (!$onehot0({{{ens}}}))")
            w(f"        $error(\"cvxif_glue: concurrent writes to custom register "
              f"{reg.name}\");")
        w("    end")
        w("  end")
        w("  /* verilator lint_on SYNCASYNCNET */")
        w("`endif")


# --------------------------------------------------------------------------
# Self-checking protocol testbench
# --------------------------------------------------------------------------


def emit_protocol_tb(desc: IsaxDesc, gen: "GlueGenerator") -> str:
    """A CV32E40X-like host model that exercises the glue's CV-X-IF handshakes.

    Checks the properties the glue is responsible for -- decode/accept,
    writeback reporting, exactly one in-order result per accepted+committed
    instruction, none for killed ones -- plus the glue's own inline assertions
    (encoding exclusivity, custom-register write exclusivity). Instruction
    *results* are not modelled: that is the ISAX's business, not the glue's.
    """
    n = desc.name
    kinds = []
    for ins in desc.instructions:
        care, value = mask_to_care_value(ins.mask)
        wb = 1 if ins.name in gen.wb_instrs else 0
        kinds.append((ins.name, care, value, wb))

    pick_cases = []
    for i, (name, care, value, wb) in enumerate(kinds):
        pick_cases.append(
            f"      {i}: begin  // {name}\n"
            f"        instr = ($urandom() & ~{_sv_hex(care)}) | {_sv_hex(value)};\n"
            f"        is_isax = 1; wb = 1'b{wb};\n"
            f"      end")
    pick_cases.append(
        "      default: begin  // an instruction the coprocessor must reject\n"
        "        instr = 32'h00000013;  // addi x0, x0, 0\n"
        "        is_isax = 0; wb = 1'b0;\n"
        "      end")

    return f"""// ===========================================================================
// Self-checking CV-X-IF protocol testbench for cvxif_glue_{n}.
//
// Generated by tools/cvxif_glue_gen.py -- DO NOT EDIT.
//
// Models a CV32E40X-like host: issue in "ID", exactly one commit transaction
// per offloaded instruction in "EX" (occasionally a kill), and a result
// consumer with randomised back-pressure.
// ===========================================================================
`timescale 1ns/1ps

module tb_cvxif_glue_{n};

  localparam int IDW   = 4;
  localparam int NKIND = {len(kinds) + 1};

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic            issue_valid, issue_ready;
  logic [31:0]     issue_instr;
  logic [IDW-1:0]  issue_id;
  logic [63:0]     issue_rs;
  logic            resp_accept, resp_writeback, resp_dualwrite, resp_loadstore;
  logic            resp_ecswrite, resp_exc;
  logic [2:0]      resp_dualread;
  logic            commit_valid, commit_kill;
  logic [IDW-1:0]  commit_id;
  logic            result_valid, result_ready;
  logic [IDW-1:0]  result_id;
  logic [31:0]     result_data;
  logic [4:0]      result_rd;
  logic [0:0]      result_we;
  logic [5:0]      result_ecsdata, result_exccode;
  logic [2:0]      result_ecswe;
  logic            result_exc, result_err, result_dbg;

  cvxif_glue_{n} #(.X_ID_WIDTH(IDW)) dut (
    .clk_i(clk), .rst_ni(rst_n),
    .x_issue_valid_i(issue_valid), .x_issue_ready_o(issue_ready),
    .x_issue_req_instr_i(issue_instr), .x_issue_req_mode_i(2'b11),
    .x_issue_req_id_i(issue_id), .x_issue_req_rs_i(issue_rs),
    .x_issue_req_rs_valid_i(2'b11),
    .x_issue_resp_accept_o(resp_accept), .x_issue_resp_writeback_o(resp_writeback),
    .x_issue_resp_dualwrite_o(resp_dualwrite), .x_issue_resp_dualread_o(resp_dualread),
    .x_issue_resp_loadstore_o(resp_loadstore), .x_issue_resp_ecswrite_o(resp_ecswrite),
    .x_issue_resp_exc_o(resp_exc),
    .x_commit_valid_i(commit_valid), .x_commit_id_i(commit_id),
    .x_commit_commit_kill_i(commit_kill),
    .x_result_valid_o(result_valid), .x_result_ready_i(result_ready),
    .x_result_id_o(result_id), .x_result_data_o(result_data),
    .x_result_rd_o(result_rd), .x_result_we_o(result_we),
    .x_result_ecsdata_o(result_ecsdata), .x_result_ecswe_o(result_ecswe),
    .x_result_exc_o(result_exc), .x_result_exccode_o(result_exccode),
    .x_result_err_o(result_err), .x_result_dbg_o(result_dbg));

  typedef struct {{
    logic [IDW-1:0] id;
    logic [4:0]     rd;
    logic           we;
  }} exp_t;
  exp_t expq[$];

  // Remove a killed instruction's expectation by id. Not by position: with
  // speculative admission several instructions are in flight, so the killed
  // one is not necessarily the newest entry in the queue.
  task automatic drop_exp(input logic [IDW-1:0] id);
    foreach (expq[i])
      if (expq[i].id == id) begin
        expq.delete(i);
        return;
      end
  endtask

  bit drain = 0;
  int n_issued = 0, n_checked = 0, n_killed = 0, n_rejected = 0, errors = 0;

  logic [31:0] gen_instr;
  bit          gen_is_isax, gen_wb;

  task automatic pick(output logic [31:0] instr, output bit is_isax, output bit wb);
    case ($urandom_range(0, NKIND-1))
{chr(10).join(pick_cases)}
    endcase
  endtask

  bit             id_busy, id_offloaded, id_exp_valid;
  logic [IDW-1:0] id_id;
  exp_t           id_exp;
  bit             ex_busy;
  logic [IDW-1:0] ex_id;
  logic [IDW-1:0] next_id = 0;

  // The spec requires ids to be unique among all in-flight instructions -- an
  // instruction is in flight from its first issue_valid until its result
  // transaction (or its kill). A free-running counter is not enough once the
  // coprocessor holds several instructions at once, so allocate the next id
  // that is not currently live.
  bit id_live [0:(1<<IDW)-1];
  bit id_acc, ex_acc;          // was the ID/EX slot instruction accepted?

  function automatic logic [IDW-1:0] alloc_id();
    for (int k = 0; k < (1<<IDW); k++) begin
      logic [IDW-1:0] cand = next_id + k[IDW-1:0];
      if (!id_live[cand]) begin
        next_id      = cand + 1'b1;
        id_live[cand] = 1'b1;
        return cand;
      end
    end
    $fatal(1, "testbench: id space exhausted");
  endfunction

  // Pending commit transactions, drained one per cycle. CV32E40X marks every
  // issue transaction individually -- including instructions killed by a flush
  // before they reach EX, and including ones it rejected -- so the model never
  // relies on a kill implicitly covering newer instructions.
  logic [IDW-1:0] cmt_ids  [$];
  bit             cmt_kills[$];

  initial begin
    issue_valid = 0; issue_instr = 0; issue_id = 0; issue_rs = 0;
    commit_valid = 0; commit_id = 0; commit_kill = 0; result_ready = 0;
    id_busy = 0; ex_busy = 0; id_exp_valid = 0; id_offloaded = 0;
    id_acc = 0; ex_acc = 0;
    for (int i = 0; i < (1<<IDW); i++) id_live[i] = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1;
  end

  always @(posedge clk) result_ready <= ($urandom_range(0, 3) != 0);

  always @(posedge clk) begin
    if (rst_n) begin
      bit do_kill;
      commit_valid <= 1'b0;
      commit_kill  <= 1'b0;
      if (cmt_ids.size() > 0) begin
        commit_valid <= 1'b1;
        commit_id    <= cmt_ids.pop_front();
        commit_kill  <= cmt_kills.pop_front();
      end
      // ID: complete the issue handshake FIRST. A transaction is accepted on
      // the clock edge where issue_valid and issue_ready are both high, so it
      // must be recognised even if this same cycle also brings a flush --
      // deasserting issue_valid now cannot retract it.
      if (id_busy && !id_offloaded && issue_ready) begin
        if (resp_accept !== id_exp_valid) begin
          errors++;
          $error("accept %0d != expected %0d for %08x",
                 resp_accept, id_exp_valid, issue_instr);
        end
        if (resp_accept) begin
          if (resp_writeback !== id_exp.we) begin
            errors++;
            $error("writeback %0d != expected %0d for %08x",
                   resp_writeback, id_exp.we, issue_instr);
          end
          expq.push_back(id_exp);
          n_issued++;
        end else begin
          n_rejected++;
        end
        id_acc       = resp_accept;
        id_offloaded = 1;
        issue_valid <= 1'b0;
      end

      // EX: exactly one commit transaction per offloaded instruction.
      if (ex_busy) begin
        do_kill = ($urandom_range(0, 19) == 0);
        cmt_ids.push_back(ex_id);
        cmt_kills.push_back(do_kill);
        if (!ex_acc) id_live[ex_id] = 1'b0;   // rejected: no result will come
        ex_busy = 0;
        if (do_kill) begin
          n_killed++;
          drop_exp(ex_id);
          id_live[ex_id] = 1'b0;
          // The flush also takes out whatever is in ID. If that instruction
          // already completed its issue transaction it gets its OWN
          // commit_kill -- it is not left to be covered by the older one.
          if (id_busy && id_offloaded) begin
            cmt_ids.push_back(id_id);
            cmt_kills.push_back(1'b1);
            drop_exp(id_id);
            id_live[id_id] = 1'b0;
          end
          if (id_busy) begin
            // Also covers the not-yet-handshaked case: that instruction never
            // became an issue transaction, so its id is free again.
            id_live[id_id] = 1'b0;
            id_busy = 0; id_exp_valid = 0; id_offloaded = 0;
            issue_valid <= 1'b0;
          end
        end
      end

      if (id_busy && id_offloaded && !ex_busy) begin
        ex_busy = 1; ex_id = id_id; ex_acc = id_acc; id_busy = 0;
        issue_valid <= 1'b0;
      end

      if (!id_busy && !drain) begin
        pick(gen_instr, gen_is_isax, gen_wb);
        id_busy = 1; id_offloaded = 0;
        id_id   = alloc_id();
        id_exp.id = id_id;
        id_exp.rd = gen_instr[11:7];
        id_exp.we = gen_wb;
        id_exp_valid = gen_is_isax;
        issue_valid <= 1'b1;
        issue_instr <= gen_instr;
        issue_id    <= id_id;
        issue_rs    <= {{$urandom(), $urandom()}};
      end
    end
  end

  always @(posedge clk) begin
    if (rst_n && result_valid && result_ready) begin
      exp_t e;
      if (expq.size() == 0) begin
        errors++;
        $error("unexpected result transaction (id %0d)", result_id);
      end else begin
        e = expq.pop_front();
        if (result_id !== e.id) begin
          errors++; $error("result id %0d != expected %0d", result_id, e.id);
        end
        if (result_we !== e.we) begin
          errors++; $error("result we %0d != expected %0d (id %0d)",
                           result_we, e.we, e.id);
        end
        if (e.we && result_rd !== e.rd) begin
          errors++; $error("result rd %0d != expected %0d (id %0d)",
                           result_rd, e.rd, e.id);
        end
        id_live[e.id] = 1'b0;
        n_checked++;
      end
    end
  end

  always @(posedge clk) begin
    if (rst_n) begin
      if (resp_dualwrite || resp_loadstore || resp_ecswrite || resp_exc ||
          |resp_dualread) begin
        errors++; $error("unexpected issue_resp flags");
      end
      if (result_valid && (result_exc || result_err || result_dbg)) begin
        errors++; $error("unexpected result flags");
      end
    end
  end

  initial begin
    repeat (20000) @(posedge clk);
    drain = 1;
    repeat (500) @(posedge clk);
    $display("issued=%0d checked=%0d killed=%0d rejected=%0d outstanding=%0d errors=%0d",
             n_issued, n_checked, n_killed, n_rejected, expq.size(), errors);
    if (errors != 0)      $fatal(1, "FAILED: %0d error(s)", errors);
    if (n_checked < 500)  $fatal(1, "FAILED: too few results checked");
    if (expq.size() != 0) $fatal(1, "FAILED: %0d result(s) never arrived", expq.size());
    $display("PASS");
    $finish;
  end

endmodule
"""


# --------------------------------------------------------------------------
# CV32E40X interface wrapper
# --------------------------------------------------------------------------


def emit_xif_wrapper(desc: IsaxDesc) -> str:
    n = desc.name
    return f"""// ===========================================================================
// CV32E40X eXtension-interface wrapper for ISAX '{n}'.
//
// Generated by tools/cvxif_glue_gen.py -- DO NOT EDIT.
//
// Binds the flat glue ports to the `cv32e40x_if_xif` coproc modports. The
// parameters must match the `cv32e40x_if_xif` instance and the core, as
// required by the CV32E40X integration manual.
// ===========================================================================
module cvxif_coproc_{n} #(
  parameter int unsigned X_ID_WIDTH  = 4,
  parameter int unsigned X_NUM_RS    = 2,
  parameter int unsigned X_RFR_WIDTH = 32,
  parameter int unsigned X_RFW_WIDTH = 32
) (
  input  logic clk_i,
  input  logic rst_ni,

  cv32e40x_if_xif.coproc_compressed  xif_compressed_if,
  cv32e40x_if_xif.coproc_issue       xif_issue_if,
  cv32e40x_if_xif.coproc_commit      xif_commit_if,
  cv32e40x_if_xif.coproc_mem         xif_mem_if,
  cv32e40x_if_xif.coproc_mem_result  xif_mem_result_if,
  cv32e40x_if_xif.coproc_result      xif_result_if
);

  // No compressed ISAX encodings: answer immediately, never accept.
  assign xif_compressed_if.compressed_ready       = 1'b1;
  assign xif_compressed_if.compressed_resp.instr  = 32'b0;
  assign xif_compressed_if.compressed_resp.accept = 1'b0;

  // The memory (request/response) interface is unused (see CVXIF.yaml).
  assign xif_mem_if.mem_valid = 1'b0;
  assign xif_mem_if.mem_req   = '0;

  cvxif_glue_{n} #(
    .X_ID_WIDTH  (X_ID_WIDTH),
    .X_NUM_RS    (X_NUM_RS),
    .X_RFR_WIDTH (X_RFR_WIDTH),
    .X_RFW_WIDTH (X_RFW_WIDTH)
  ) u_glue (
    .clk_i                    (clk_i),
    .rst_ni                   (rst_ni),

    .x_issue_valid_i          (xif_issue_if.issue_valid),
    .x_issue_ready_o          (xif_issue_if.issue_ready),
    .x_issue_req_instr_i      (xif_issue_if.issue_req.instr),
    .x_issue_req_mode_i       (xif_issue_if.issue_req.mode),
    .x_issue_req_id_i         (xif_issue_if.issue_req.id),
    .x_issue_req_rs_i         (xif_issue_if.issue_req.rs),
    .x_issue_req_rs_valid_i   (xif_issue_if.issue_req.rs_valid),
    .x_issue_resp_accept_o    (xif_issue_if.issue_resp.accept),
    .x_issue_resp_writeback_o (xif_issue_if.issue_resp.writeback),
    .x_issue_resp_dualwrite_o (xif_issue_if.issue_resp.dualwrite),
    .x_issue_resp_dualread_o  (xif_issue_if.issue_resp.dualread),
    .x_issue_resp_loadstore_o (xif_issue_if.issue_resp.loadstore),
    .x_issue_resp_ecswrite_o  (xif_issue_if.issue_resp.ecswrite),
    .x_issue_resp_exc_o       (xif_issue_if.issue_resp.exc),
    .x_issue_resp_regread_o   (),  // v1.0-only field, absent from rev 458c8a73

    .x_commit_valid_i         (xif_commit_if.commit_valid),
    .x_commit_id_i            (xif_commit_if.commit.id),
    .x_commit_commit_kill_i   (xif_commit_if.commit.commit_kill),

    .x_result_valid_o         (xif_result_if.result_valid),
    .x_result_ready_i         (xif_result_if.result_ready),
    .x_result_id_o            (xif_result_if.result.id),
    .x_result_data_o          (xif_result_if.result.data),
    .x_result_rd_o            (xif_result_if.result.rd),
    .x_result_we_o            (xif_result_if.result.we),
    .x_result_ecsdata_o       (xif_result_if.result.ecsdata),
    .x_result_ecswe_o         (xif_result_if.result.ecswe),
    .x_result_exc_o           (xif_result_if.result.exc),
    .x_result_exccode_o       (xif_result_if.result.exccode),
    .x_result_err_o           (xif_result_if.result.err),
    .x_result_dbg_o           (xif_result_if.result.dbg)
  );

endmodule
"""


# --------------------------------------------------------------------------
# CV32E40PX interface wrapper (rev 458c8a73, packaged as structs)
# --------------------------------------------------------------------------


def emit_e40px_wrapper(desc: IsaxDesc) -> str:
    n = desc.name
    return f"""// ===========================================================================
// CV32E40PX eXtension-interface wrapper for ISAX '{n}'.
//
// Generated by tools/cvxif_glue_gen.py -- DO NOT EDIT.
//
// CV32E40PX (x-heep/cv32e40px -- not CV32E40P, which has no X-interface, and
// not CV32E40X) implements the *same* CV-X-IF revision as CV32E40X: issue_req
// carries the source operands, issue_resp has dualwrite/dualread/loadstore/
// ecswrite/exc, and the result carries the full ecs/exc/err/dbg side-band. Only
// the packaging differs -- `cv32e40px_core_v_xif_pkg` defines packed structs
// where CV32E40X defines a SystemVerilog interface -- so this wrapper is a
// field-for-field unpack, with none of the semantic translation the CVA6 (v1.0)
// wrapper has to do.
//
// One parameter difference that matters: the package sets X_NUM_RS = 3 (three
// read ports), so `rs` is 3 words wide and `rs_valid` three bits. The glue is
// parameterised on X_NUM_RS and only ever reads rs1/rs2.
//
// The memory interface is unused (see CVXIF.yaml) and tied off.
// ===========================================================================
module cvxif_coproc_e40px_{n}
  import cv32e40px_core_v_xif_pkg::*;
(
  input  logic               clk_i,
  input  logic               rst_ni,

  // compressed interface -- no compressed ISAX encodings
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic               x_compressed_valid_i,
  input  x_compressed_req_t  x_compressed_req_i,
  output logic               x_compressed_ready_o,
  output x_compressed_resp_t x_compressed_resp_o,

  input  logic               x_issue_valid_i,
  input  x_issue_req_t       x_issue_req_i,
  output logic               x_issue_ready_o,
  output x_issue_resp_t      x_issue_resp_o,

  input  logic               x_commit_valid_i,
  input  x_commit_t          x_commit_i,

  // memory interface -- unused
  input  logic               x_mem_ready_i,
  input  x_mem_resp_t        x_mem_resp_i,
  output logic               x_mem_valid_o,
  output x_mem_req_t         x_mem_req_o,
  input  logic               x_mem_result_valid_i,
  input  x_mem_result_t      x_mem_result_i,
  /* verilator lint_on UNUSEDSIGNAL */

  input  logic               x_result_ready_i,
  output logic               x_result_valid_o,
  output x_result_t          x_result_o
);

  assign x_compressed_ready_o       = 1'b1;
  assign x_compressed_resp_o.instr  = 32'b0;
  assign x_compressed_resp_o.accept = 1'b0;

  assign x_mem_valid_o = 1'b0;
  assign x_mem_req_o   = '0;

  cvxif_glue_{n} #(
    .X_ID_WIDTH  (X_ID_WIDTH),
    .X_NUM_RS    (RF_READ_PORTS),
    .X_RFR_WIDTH (X_RFR_WIDTH),
    .X_RFW_WIDTH (X_RFW_WIDTH)
  ) u_glue (
    .clk_i                    (clk_i),
    .rst_ni                   (rst_ni),

    .x_issue_valid_i          (x_issue_valid_i),
    .x_issue_ready_o          (x_issue_ready_o),
    .x_issue_req_instr_i      (x_issue_req_i.instr),
    .x_issue_req_mode_i       (x_issue_req_i.mode),
    .x_issue_req_id_i         (x_issue_req_i.id),
    .x_issue_req_rs_i         (x_issue_req_i.rs),
    .x_issue_req_rs_valid_i   (x_issue_req_i.rs_valid),
    .x_issue_resp_accept_o    (x_issue_resp_o.accept),
    .x_issue_resp_writeback_o (x_issue_resp_o.writeback),
    .x_issue_resp_dualwrite_o (x_issue_resp_o.dualwrite),
    .x_issue_resp_dualread_o  (x_issue_resp_o.dualread),
    .x_issue_resp_loadstore_o (x_issue_resp_o.loadstore),
    .x_issue_resp_ecswrite_o  (x_issue_resp_o.ecswrite),
    .x_issue_resp_exc_o       (x_issue_resp_o.exc),
    .x_issue_resp_regread_o   (),  // v1.0-only field, absent from this revision

    .x_commit_valid_i         (x_commit_valid_i),
    .x_commit_id_i            (x_commit_i.id),
    .x_commit_commit_kill_i   (x_commit_i.commit_kill),

    .x_result_valid_o         (x_result_valid_o),
    .x_result_ready_i         (x_result_ready_i),
    .x_result_id_o            (x_result_o.id),
    .x_result_data_o          (x_result_o.data),
    .x_result_rd_o            (x_result_o.rd),
    .x_result_we_o            (x_result_o.we),
    .x_result_ecsdata_o       (x_result_o.ecsdata),
    .x_result_ecswe_o         (x_result_o.ecswe),
    .x_result_exc_o           (x_result_o.exc),
    .x_result_exccode_o       (x_result_o.exccode),
    .x_result_err_o           (x_result_o.err),
    .x_result_dbg_o           (x_result_o.dbg)
  );

endmodule
"""


# --------------------------------------------------------------------------
# CVA6 interface wrapper (CV-X-IF v1.0)
# --------------------------------------------------------------------------


def emit_cva6_wrapper(desc: IsaxDesc, allow_custom_regs: bool = False) -> str:
    n = desc.name
    # CVA6 hardwires `commit.commit_kill = 0` (cvxif_issue_register_commit_if_
    # driver.sv), on the premise -- its own comment marks it "TODO to be
    # verified" -- that an instruction reaching issue is no longer speculative.
    # It is: an older instruction can still trap. The coprocessor then executes
    # the offloaded instruction, the trap flushes it, and after the handler
    # returns it is re-fetched and executed a *second* time, with no kill in
    # between to discard the first.
    #
    # Harmless for a stateless ISAX -- the orphaned result is simply never
    # consumed, and sparkle passes 35/35 that way. Fatal for one with custom
    # registers: measured on ANTDOTP, 80 offloads for 79 architectural
    # instructions, and the accumulator ends up one MAC too far.
    if desc.registers and not allow_custom_regs:
        raise GlueError(
            f"'{n}' has {len(desc.registers)} custom register(s) "
            f"({', '.join(r.name for r in desc.registers)}), which are not safe "
            "on CVA6: it never raises commit_kill, so an instruction offloaded "
            "in the shadow of a trapping instruction executes twice -- once "
            "before the flush and once after the handler returns -- and the "
            "second execution accumulates on top of the first. Stateless ISAXes "
            "are fine. Pass --allow-custom-regs to generate anyway (results are "
            "correct only if no ISAX instruction is ever flushed), or fix it "
            "core-side by driving commit_kill on flush.")
    return f"""// ===========================================================================
// CVA6 eXtension-interface wrapper for ISAX '{n}'.
//
// Generated by tools/cvxif_glue_gen.py -- DO NOT EDIT.
//
// CVA6 speaks CV-X-IF **v1.0**, the glue speaks rev 458c8a73. Three differences
// matter, and this wrapper is exactly the translation between them:
//
//  1. v1.0 bundles every channel into one `cvxif_req_t` / `cvxif_resp_t` pair of
//     packed structs instead of separate SystemVerilog interfaces.
//  2. v1.0 moved the source operands out of `issue_req` into their own
//     `register` channel. CVA6 builds with X_ISSUE_REGISTER_SPLIT = 0, so
//     `register_valid == issue_valid` (see cvxif_issue_register_commit_if_driver
//     .sv) and the operands still arrive in the issue cycle -- which is what the
//     glue assumes. A core with the split enabled would need a buffer here.
//  3. v1.0 added `issue_resp.register_read`, telling the core which operands to
//     wait for. Driving it from the ISAX's own decode avoids stalling on an rs2
//     field that a custom encoding uses as an immediate.
//
// Dropped, because v1.0 has no such fields: dualread/dualwrite, loadstore,
// ecswrite/ecsdata/ecswe, and the result-side exc/exccode/err/dbg. The memory
// interface is gone in v1.0 entirely, and CVXIF.yaml never uses it.
//
// CVA6 hardwires `commit.commit_kill = 0` and raises commit in the same cycle as
// the issue handshake, so the glue's commit gate opens immediately -- `new_commit
// _hit` covers exactly that case -- and no instruction is ever killed.
// ===========================================================================
module cvxif_coproc_cva6_{n} #(
  parameter int unsigned X_ID_WIDTH  = 4,
  parameter int unsigned X_NUM_RS    = 2,
  parameter int unsigned X_RFR_WIDTH = 32,
  parameter int unsigned X_RFW_WIDTH = 32,
  parameter type         cvxif_req_t  = logic,
  parameter type         cvxif_resp_t = logic
) (
  input  logic        clk_i,
  input  logic        rst_ni,
  input  cvxif_req_t  cvxif_req_i,
  output cvxif_resp_t cvxif_resp_o
);

  logic                      issue_ready;
  logic                      issue_accept;
  logic                      issue_writeback;
  logic [X_NUM_RS-1:0]       issue_regread;
  logic                      result_valid;
  logic [X_ID_WIDTH-1:0]     result_id;
  logic [X_RFW_WIDTH-1:0]    result_data;
  logic [4:0]                result_rd;
  logic [X_RFW_WIDTH/32-1:0] result_we;

  cvxif_resp_t resp;
  always_comb begin
    resp                       = '0;
    // No compressed ISAX encodings: answer immediately, never accept.
    resp.compressed_ready      = 1'b1;
    resp.compressed_resp.instr = 32'b0;
    resp.compressed_resp.accept = 1'b0;

    resp.issue_ready           = issue_ready;
    // X_ISSUE_REGISTER_SPLIT = 0: one handshake covers issue and register.
    resp.register_ready        = issue_ready;
    resp.issue_resp.accept     = issue_accept;
    resp.issue_resp.writeback  = issue_writeback;
    resp.issue_resp.register_read = issue_regread;

    resp.result_valid          = result_valid;
    resp.result.hartid         = '0;   // single hart
    resp.result.id             = result_id;
    resp.result.data           = result_data;
    resp.result.rd             = result_rd;
    resp.result.we             = result_we;
  end
  assign cvxif_resp_o = resp;

  cvxif_glue_{n} #(
    .X_ID_WIDTH  (X_ID_WIDTH),
    .X_NUM_RS    (X_NUM_RS),
    .X_RFR_WIDTH (X_RFR_WIDTH),
    .X_RFW_WIDTH (X_RFW_WIDTH)
  ) u_glue (
    .clk_i                    (clk_i),
    .rst_ni                   (rst_ni),

    .x_issue_valid_i          (cvxif_req_i.issue_valid),
    .x_issue_ready_o          (issue_ready),
    .x_issue_req_instr_i      (cvxif_req_i.issue_req.instr),
    .x_issue_req_mode_i       (2'b11),   // no `mode` in v1.0; unused by the glue
    .x_issue_req_id_i         (cvxif_req_i.issue_req.id),
    .x_issue_req_rs_i         (cvxif_req_i.register.rs),
    .x_issue_req_rs_valid_i   (cvxif_req_i.register.rs_valid),
    .x_issue_resp_accept_o    (issue_accept),
    .x_issue_resp_writeback_o (issue_writeback),
    .x_issue_resp_dualwrite_o (),
    .x_issue_resp_dualread_o  (),
    .x_issue_resp_loadstore_o (),
    .x_issue_resp_ecswrite_o  (),
    .x_issue_resp_exc_o       (),
    .x_issue_resp_regread_o   (issue_regread),

    .x_commit_valid_i         (cvxif_req_i.commit_valid),
    .x_commit_id_i            (cvxif_req_i.commit.id),
    .x_commit_commit_kill_i   (cvxif_req_i.commit.commit_kill),

    .x_result_valid_o         (result_valid),
    .x_result_ready_i         (cvxif_req_i.result_ready),
    .x_result_id_o            (result_id),
    .x_result_data_o          (result_data),
    .x_result_rd_o            (result_rd),
    .x_result_we_o            (result_we),
    .x_result_ecsdata_o       (),
    .x_result_ecswe_o         (),
    .x_result_exc_o           (),
    .x_result_exccode_o       (),
    .x_result_err_o           (),
    .x_result_dbg_o           ()
  );

endmodule
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def generate(yaml_path: str, sv_path: str | None = None,
             out_dir: str | None = None,
             emit_wrapper: bool = True,
             emit_testbench: bool = False,
             speculative: bool = True,
             no_input_buffer: bool = True,
             ooo_result: bool = True,
             emit_cva6: bool = False,
             emit_e40px: bool = False,
             allow_custom_regs: bool = False) -> list[str]:
    desc = parse_isax_yaml(yaml_path)
    module = f"ISAX_{desc.name}"
    if sv_path is None:
        sv_path = os.path.join(os.path.dirname(yaml_path) or ".", module + ".sv")
    if not os.path.isfile(sv_path):
        raise GlueError(
            f"{sv_path}: not found. The glue is generated against the actual port "
            "list of the Longnail-emitted ISAX module; pass it with --sv.")

    ports = parse_sv_ports(sv_path, module)
    cports = classify_ports(desc, ports)
    gen = GlueGenerator(desc, cports, module, (yaml_path, sv_path),
                        speculative=speculative, no_input_buffer=no_input_buffer,
                        ooo_result=ooo_result)

    out_dir = out_dir or (os.path.dirname(yaml_path) or ".")
    os.makedirs(out_dir, exist_ok=True)
    written = []

    glue_path = os.path.join(out_dir, f"cvxif_glue_{desc.name}.sv")
    with open(glue_path, "w") as f:
        f.write(gen.generate())
    written.append(glue_path)

    if emit_wrapper:
        wrap_path = os.path.join(out_dir, f"cvxif_coproc_{desc.name}.sv")
        with open(wrap_path, "w") as f:
            f.write(emit_xif_wrapper(desc))
        written.append(wrap_path)

    if emit_e40px:
        px_path = os.path.join(out_dir, f"cvxif_coproc_e40px_{desc.name}.sv")
        with open(px_path, "w") as f:
            f.write(emit_e40px_wrapper(desc))
        written.append(px_path)

    if emit_cva6:
        cva6_path = os.path.join(out_dir, f"cvxif_coproc_cva6_{desc.name}.sv")
        with open(cva6_path, "w") as f:
            f.write(emit_cva6_wrapper(desc, allow_custom_regs))
        written.append(cva6_path)

    if emit_testbench:
        tb_path = os.path.join(out_dir, f"tb_cvxif_glue_{desc.name}.sv")
        with open(tb_path, "w") as f:
            f.write(emit_protocol_tb(desc, gen))
        written.append(tb_path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate CV-X-IF glue logic for a Longnail-generated ISAX.")
    ap.add_argument("isax_yaml", help="ISAX_<name>.yaml emitted by -generate-isax-ports")
    ap.add_argument("--sv", help="ISAX_<name>.sv (default: next to the YAML)")
    ap.add_argument("-o", "--out-dir", help="output directory (default: YAML's dir)")
    ap.add_argument("--no-wrapper", action="store_true",
                    help="do not emit the cv32e40x_if_xif wrapper module")
    ap.add_argument("--cva6-wrapper", action="store_true",
                    help="also emit the CVA6 wrapper (CV-X-IF v1.0: one "
                         "cvxif_req_t/cvxif_resp_t struct pair, operands on the "
                         "register channel, issue_resp.register_read driven from "
                         "the ISAX decode)")
    ap.add_argument("--e40px-wrapper", action="store_true",
                    help="also emit the CV32E40PX wrapper (same CV-X-IF revision "
                         "as CV32E40X, but packed structs from "
                         "cv32e40px_core_v_xif_pkg instead of an interface)")
    ap.add_argument("--allow-custom-regs", action="store_true",
                    help="generate the CVA6 wrapper even for an ISAX with custom "
                         "registers. CVA6 never raises commit_kill, so such an "
                         "ISAX double-executes on a flush; only safe if no ISAX "
                         "instruction is ever flushed.")
    ap.add_argument("--testbench", action="store_true",
                    help="also emit a self-checking CV-X-IF protocol testbench")
    ap.add_argument("--in-order-result", dest="ooo_result", action="store_false",
                    help="force the pre-2026 in-order emission: every result rides 32-bit "
                         "staging registers to the last stage so one ordered result "
                         "transaction suffices. Out-of-order emission is the default.")
    ap.add_argument("--input-buffer", dest="no_input_buffer", action="store_false",
                    help="keep the issue->stage-0 staging register. Bypassing it is the "
                         "default; keep it if the combinational path from the core's "
                         "operand bus into ISAX stage 0 costs too much timing.")
    ap.add_argument("--ooo-result", action="store_true",
                    help="emit each result at the stage that produces it instead of "
                         "dragging it to the last stage: removes the 32-bit result "
                         "staging registers and retires an entry where it emits. Stages "
                         "arbitrate for the single result port, deepest (oldest) first, "
                         "and a loser stalls in place -- no result FIFO. Requires that "
                         "every instruction has a WrRD and none observes the interface "
                         "after it; falls back to in-order emission with a diagnostic "
                         "otherwise.")
    ap.add_argument("--no-input-buffer", action="store_true",   # now the default
                    help="speculative builds only: drop the issue->stage-0 staging "
                         "register and admit in the issue cycle. Saves ~125 register bits "
                         "and a cycle of latency, but withholds issue_ready while stage 0 "
                         "is occupied (blocking the core's ID stage, and anything behind "
                         "the ISAX instruction) and puts the core's operand bus straight "
                         "into ISAX stage 0. MEASURE TIMING before adopting.")
    ap.add_argument("--non-speculative", dest="speculative", action="store_false",
                    help="force commit-gated admission (the pre-2026 default): admit only "
                         "after the core marked the instruction non-speculative. Serialises "
                         "ISAX execution but needs no rollback, so it is what an ISAX with "
                         "custom registers gets -- automatically, without this flag.")
    ap.add_argument("--speculative", action="store_true",
                    help="(now the default; accepted for compatibility) "
                         "admit instructions at the issue handshake instead of "
                         "at the commit, holding results until they commit. "
                         "Overlaps execution on hosts whose issue runs ahead of "
                         "commit (CV32E40X does). Requires an ISAX with no "
                         "custom registers -- a killed instruction is dropped, "
                         "there is no rollback.")
    args = ap.parse_args(argv)

    try:
        written = generate(args.isax_yaml, args.sv, args.out_dir,
                           emit_wrapper=not args.no_wrapper,
                           emit_testbench=args.testbench,
                           speculative=args.speculative,
                           no_input_buffer=args.no_input_buffer,
                           ooo_result=args.ooo_result,
                           emit_cva6=args.cva6_wrapper,
                           emit_e40px=args.e40px_wrapper,
                           allow_custom_regs=args.allow_custom_regs)
    except GlueError as e:
        print(f"cvxif_glue_gen: error: {e}", file=sys.stderr)
        return 1
    for path in written:
        print(f"cvxif_glue_gen: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
