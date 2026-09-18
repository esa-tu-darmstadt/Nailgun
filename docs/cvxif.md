# CV-X-IF flow (CV32E40X, no SCAIE-V)

An alternative back end for the ISAX flow: instead of patching a core's RTL with
SCAIE-V, the generated ISAX is attached to a host through the standard
**CORE-V-XIF** eXtension Interface. The core is used unmodified.

    CoreDSL --> Treenail --> Longnail (datasheet: CVXIF.yaml) --> ISAX_<n>.sv
                                                                      |
                                              tools/cvxif_glue_gen.py |
                                                                      v
                                  cvxif_glue_<n>.sv + cvxif_coproc_<n>.sv
                                                                      |
                                                            cv32e40x_if_xif
                                                                      v
                                                                 CV32E40X

Target: **CV32E40X**. CV32E40P has no X-interface, so it is not a candidate.
The core is pristine upstream `openhwgroup/cv32e40x` in `deps/cv32e40x` (master
HEAD `d952cd63`), *not* the SCAIE-V fork under `deps/scaie-v/CoresSrc/` — the
fork adds `scaiev_interface` hooks this flow has no use for, and building
against upstream keeps "unmodified core" literal. Its
`rtl/cv32e40x_if_xif.sv` implements XIF revision `458c8a73` (issue request
carries `rs`/`rs_valid`; a memory interface exists, which CV-X-IF v1.0 later
dropped).

## Two pieces

| Piece | Path |
|---|---|
| Virtual datasheet | `deps/longnail/datasheets/CVXIF.yaml` |
| Glue generator | `tools/cvxif_glue_gen.py` |
| Pipeline integration stage | `cvxif.py` (the sibling of `scaiev.py`) |

```bash
# one command: schedule against the interface, integrate (glue + core copy +
# top + filelist.f, under outputs/run_N/<core>/) AND simulate with cocotb
CORE=CV32E40X_UPSTREAM ISAXES=SPARKLE SIM_ENABLE=y \
  TB_PATH=custom_tbs/sparkle.cpp TB_EXPECTED_PATH=custom_tbs/sparkle_expected.txt make ci
```

`dispatch.py` branches on `CoreSupport.uses_cvxif()`: instead of SCAIE-V,
`cvxif.run_cvxif()` populates `out_dir/<core>/` with (1) a copy of the pristine
upstream checkout (`copy_blacklist()` honored; required patches — CV32E40X's
sticky-issue_resp fix — applied to the **copy**, so `deps/` stays clean),
(2) the glue + per-core coprocessor wrapper from `tools/cvxif_glue_gen.py`,
(3) the `cvxif_<flavor>_top` top, and (4) a `filelist.f` (`+define+`/`+incdir+`
+ sources; the `CVXIF_COPROC` define selects the coprocessor module). The three
CV-X-IF cores extend `cvxif.CVXIFCoreSupport`; its `get_core_srcs()` serves the
filelist to the synthesis plugins, so Cadence synthesis of the integrated
design (`cvxif_<flavor>_top`, ports `clk_i`/`rst_ni`) works like for any
SCAIE-V core. `SIM_ENABLE=y` runs the regular cocotb flow (see "Simulation"
below); `NO_ISAX=y` integrates the **null coprocessor** instead of glue — a
CPU-only baseline. Kconfig
(`configs/CVXIF_Kconfig`, all usable as `make ci` env vars):
`CVXIF_SPECULATIVE`, `CVXIF_ALLOW_CUSTOM_REGS` (CVA6 only),
`CVXIF_GEN_PROTOCOL_TB`. Glue-gen failures exit with `CVXIF` error codes
(240+).

`CORE_CV32E40X_UPSTREAM` (`cores/CV32E40X_upstream.py`) is pristine upstream
`deps/cv32e40x` with `CVXIF.yaml` as its datasheet. The datasheet always comes
from the selected core (`CoreSupport.get_longnail_datasheet_name()`), which also
decides between the CV-X-IF and the SCAIE-V integration stage — the two cannot
be mixed.

`LN_SHARING_EVAL.py` includes `CV32E40PX`, `CV32E40X_UPSTREAM` (both CV-X-IF)
and the SCAIE-V `CV32E40X` in its default `CORES`: baselines, schedules and
sharing variants build through `make ci` like every other core. For the
CV-X-IF pair, Cadence synthesis targets `cvxif_e40px_top` / `cvxif_e40x_top`
and verification is the same cocotb sim gate as for every other core (the
entry's `tb`/`tb_expected`). `cvxif_post_sim()` — the former post-dispatch gate
through the standalone runners — is kept only for job manifests written before
the switch. The `*_ISAX_MUL` entries use
`core_patches/cv32e40x_no_mul.patch` (one patch for both CV32E40X variants —
the M-path files are identical between upstream and the SCAIE-V fork; MUL*
made illegal in `cv32e40x_m_decoder.sv` + the ex-stage `no_mul` generate
branch forced, DIV/REM kept) and `core_patches/cv32e40px_no_mul.patch`
(decoder MUL* arms → `illegal_insn`, `cv32e40px_mult` tied off; DIV/REM run
on the ALU and are kept). `cvxif.run_cvxif()` honors `SCV_POST_PATCH`, so the
eval's `core_patches` field works uniformly across SCAIE-V and CV-X-IF cores.
On the SCAIE-V `CV32E40X`, `skip_cores` disables only the ANTDOTP entries
(custom registers, never exercised on that fork — CoreFeature.NONE). A second
issue was found and FIXED (2026-08-11, one line in the fork's
`cv32e40x_controller_bypass.sv`): the core forwards operands from EX, and for
an ISAX instruction the EX forward bus carries ALU passthrough garbage (the
ISAX's own rs1 operand) because the real result only materializes in WB via
SCAL's `WrRD` — so any consumer at RAW distance 1 read a poisoned value.
`is_isax` now joins `lsu_en`/`xif_en` in the load-use-hazard stall (ISAX
results are load-like), after which the WB forward carries `rf_wdata_wb`,
which the fork already muxes from `scaiev.WrRd`. Verified: SPARKLE,
XCoreVSimd and ZFINX flipped FAIL→PASS; `DOTPROD,RISCV_MUL` +
`cv32e40x_no_mul.patch` (whose TB happened to have no distance-1 consumer)
still PASSES.

## Why the datasheet describes an interface, not a pipeline

`CV32E40X.yaml` describes the core's IF/ID/EX/WB pipeline, because SCAIE-V
splices the ISAX *into* that pipeline: ISAX stage *n* is core stage *n*.

CV-X-IF is not like that. The coprocessor sits outside the core and meets it at
exactly three points:

| Point | Core stage | Carries | Back-pressure |
|---|---|---|---|
| issue | ID | instruction word, rs1/rs2, `id` | `issue_ready` |
| commit | EX | `commit_kill` (speculation resolved) | none (one cycle, must be sampled) |
| result | WB | rd data, `we` | `result_ready` |

Everything in between belongs to the glue. So `CVXIF.yaml`'s stages describe the
glue's **own** pipeline ("shadow pipeline"), which the glue then materialises.

### No decoupled mode

Longnail's decoupled ("spawn") writeback exists because under SCAIE-V an ISAX
that runs longer than the core is deep has nowhere to put its result but the
register file, out of band, with SCAL doing the hazard tracking.

CV-X-IF has no such limit: both ends are handshakes. `issue_ready` can stay low
indefinitely (the core stalls ID) and `result_valid` can come arbitrarily late
(the core stalls WB). An ISAX that needs 30 cycles just gets a 30-deep shadow
pipeline. Decoupling would not even buy throughput, because the core blocks at
WB for the result regardless.

`CVXIF.yaml` therefore describes an **open-ended** interface: its entries carry
no `latest`, which Longnail reads as "any stage >= `earliest`". Two things are
stated explicitly instead of through a bound:

- `WrRD` and `WrCustReg.data` are `spawn: false`. Without that key Longnail pins
  a write to the datasheet's last stage (the largest `latest`) and decouples
  anything scheduled later; with it the write is always coupled, from whatever
  stage the datapath ends in, and the decoupling indicator is not even created
  in the ILP.
- The values handed over at issue (`RdRS1`, `RdRS2`, `RdInstr`, `RdCustReg`)
  keep `costly: 1`. An open-ended read that states `costly` is clamped to its
  native window (stage 0 here); only a read whose operands cannot be there in
  time -- a custom-register read with a computed index -- is exempted and falls
  back to the open-ended bound.

This costs nothing: Longnail only materialises the stages a schedule uses, and
the glue sizes its shadow pipeline from the stages that appear in the generated
ISAX **ports**. The `last stage` entry of the ISAX YAML is the largest `latest`
of the datasheet, which here is just the `WrCustReg.addr` pin (0); the glue
generator ignores its value.

(The datasheet used to emulate this with `latest: 1000` / `costly: 1001` on
every entry. The open-ended form produces byte-identical ISAX and glue RTL --
checked on sbox, sparkle, ANTDOTP and a 34-stage sqrt -- without putting a
big-M coefficient of 1000 into the constraint matrix.)

`_spawn` ports can still appear — a CoreDSL `spawn { }` block forces them
independently of the schedule — and the glue serves them as one more in-order
stage.

### `costly: 1` on the value reads

CV-X-IF hands the operands over exactly once, at issue. Presenting `RdRS1` /
`RdRS2` / `RdInstr` at a stage > 0 costs the glue a full-width shadow register
per stage, which is precisely what `costly` prices in. Longnail's read clamp
therefore pulls the reads to stage 0 and lets its own datapath registers carry
the values onward. Reads that provably cannot happen that early (a
custom-register read with a computed index) are exempted automatically.

### Not expressible over CV-X-IF

| Interface | Why |
|---|---|
| `RdPC`, `WrPC` | `x_issue_req_t` has no PC; the spec excludes control-transfer instructions |
| `RdRD` | only rs1/rs2 are offered (CV32E40X wires `X_NUM_RS = 2`) |
| `RdMem`, `WrMem` | the memory interface was removed in CV-X-IF v1.0; supporting it means committing to the deprecated rev-`458c8a73` interface plus speculative-access, PMA-error and ordering handling |
| `RdX`/`WrX`, `MultiRdMem`/`MultiWrMem` | no counterpart |
| `always` blocks | CV-X-IF only ever hands over instructions |
| conditional `WrRD` | `result.we` must equal the `issue_resp.writeback` reported at decode time |

The generator rejects each of these with a diagnostic naming the offending port,
rather than emitting glue that silently drops the case.

## What the glue does

1. **Decode** — matches the offered instruction word against the ISAX encoding
   masks; drives `issue_resp.accept` and `issue_resp.writeback`. Unknown
   instructions are rejected in the same cycle (`issue_ready = 1`,
   `accept = 0`) so the core never waits on us.

2. **Issue → input buffer** — latches instruction word, rs1/rs2, `id` and
   `rd = instr[11:7]`. `issue_ready` is withheld while the buffer is occupied
   or while an operand the instruction needs is not yet `rs_valid`.

3. **Commit gate** — the buffered instruction enters the ISAX pipeline only
   once the core marked it non-speculative. Nothing inside the ISAX is ever
   speculative, so `RdFlush` is tied to 0 and custom registers need no
   rollback.

   A `commit_kill` is honoured **only for the buffered instruction's own id**.
   The spec also says a kill covers every *newer* instruction, but acting on
   that is unsafe against CV32E40X, which raises `commit_kill` for every
   instruction the coprocessor rejects (`kill_rejected`) — including legal CSR
   accesses, which it offers on the issue interface and then executes normally
   **without flushing the pipeline**:

   ```
   [issue] instr=305e1073 id=6 accept=0     <- csrw mtvec, rejected by us
   [commit] id=6 kill=1                     <- ... and execution continues
   ```

   Killing newer entries on such a commit would drop an ISAX instruction the
   core still expects a result for, and the core would then wait at WB forever.
   Exact-id matching is safe because the core marks every issue transaction
   individually — when it really does flush, the buffered instruction receives
   its own kill (observed: a rejected illegal instruction traps, and both its
   id and the speculatively accepted id behind it are killed by id).

4. **Shadow pipeline** — rigid, in-order, carrying valid / id / rd / we /
   decode-one-hot / result payload alongside the ISAX datapath. It drives every
   `RdIValid_*` and `RdStall_*` input and consumes every `WrStall_*` output:

   ```
   rdstall[LMAX] = result back-pressure
   rdstall[s]    = rdstall[s+1] | wrstall[s+1]      (s < LMAX)
   hold[s]       = rdstall[s]   | wrstall[s]
   ```

   `RdStall` excludes the same stage's `WrStall`, as SCAIE-V's core-interface
   contract requires. A sharing group with II > 1 back-pressures through its
   `WrStall` at stage 0, exactly as it would through SCAL.

5. **Result** — every accepted+committed instruction produces exactly one
   result transaction, including instructions that do not write rd (`we = 0`),
   which the interface requires.

6. **Custom registers** — SCAIE-V normally supplies the register files (the
   ISAX only gets `Rd<R>` / `Wr<R>` ports), so the glue does:

   - the register file and its initializer, read ports driven from it and
     indexed by `Rd<R>_addr_…` when `elements > 1`;
   - write enables `iv_<stage>[instr] & ~hold[stage] & <validReq>`, including
     `_spawn` writes; write addresses scheduled earlier than their data (the
     datasheet pins `WrCustReg.addr` to stage 0) are pipelined to the data
     stage;
   - `read only: 1` registers become a `localparam` ROM, not a bank of
     reset-loaded flops, and are exempt from the interlock below since a
     constant cannot conflict;
   - **hazards** via an admission interlock: an instruction touching register R
     is not admitted while an older in-flight instruction still has a pending
     access to R (`cr_busy_R` = OR of `iv_s[I]` over stages `s` before `I`'s
     access to R). Because the pipeline is rigid and in-order, that alone
     orders every access correctly — no forwarding network, no per-stage
     scoreboard. A `$onehot0` assertion over each register's write enables
     backs it up in simulation.

   Example (ANTDOTP): `ANTMAC` writes `macAcc` at stage 3, so
   `cr_busy_macAcc = iv_0[ANTMAC] | iv_1[ANTMAC] | iv_2[ANTMAC]`, and
   `cr_touch_macAcc` covers `ANTMAC` and `ANTMACR`.

### Deadlock

None. The glue may hold `issue_ready` low while its pipeline is full, but the
core's EX and WB stages advance independently of an ID stall, so a result the
glue is holding always eventually gets consumed, which drains the pipeline.

### Timing note

To sustain one instruction per cycle, `issue_ready` accounts for the input
buffer draining in the same cycle, which makes it depend combinationally on
`result_ready` through the stall chain
(`result_ready → out_stall → rdstall[0] → hold[0] → ib_pop → issue_ready`).
That is legal — CV-X-IF only forbids the coprocessor a combinational path from
`rs`/`rs_valid` to `result_valid`/`result`, and this is the allowed
"later instruction depends on earlier instruction" direction — but it is a real
path across the interface. If it ever closes badly, changing the generator's
`ib_free` from `~ib_valid_q | ib_pop` to `~ib_valid_q` breaks it, at the cost of
halving issue throughput.

## Generator

```
tools/cvxif_glue_gen.py <ISAX_name.yaml> [--sv <ISAX_name.sv>] [-o <dir>]
                                         [--testbench] [--no-wrapper]
```

The glue is generated against the **actual port list** of the Longnail-emitted
module (parsed out of `ISAX_<name>.sv`), with the YAML supplying encodings,
sharing groups and custom-register metadata. Any port that cannot be classified
is a hard error, so the generator cannot silently drift out of sync with
Longnail's port naming.

Outputs:

| File | Purpose |
|---|---|
| `cvxif_glue_<n>.sv` | the glue, instantiating `ISAX_<n>` |
| `cvxif_coproc_<n>.sv` | binds the flat glue ports to the `cv32e40x_if_xif` coproc modports |
| `tb_cvxif_glue_<n>.sv` | (`--testbench`) self-checking CV-X-IF host model |

The generated testbench models a CV32E40X-like host — issue in ID, one commit
per offloaded instruction in EX (occasionally a kill), randomised `result_ready`
back-pressure — and checks decode/accept, the writeback flag, and that every
accepted+committed instruction yields exactly one in-order result and killed
ones yield none. It also exercises the glue's inline assertions (encoding
exclusivity, custom-register write exclusivity, i.e. the interlock).

```bash
verilator --binary --timing --top-module tb_cvxif_glue_<n> \
    tb_cvxif_glue_<n>.sv cvxif_glue_<n>.sv ISAX_<n>.sv split*.sv splitop_*.sv
./obj_dir/Vtb_cvxif_glue_<n>
```

## Simulation

The CV-X-IF cores run in the regular cocotb flow — `SIM_ENABLE=y ... make ci`,
the `custom_tbs/` programs, picolibc, `tools/run_integration_tests.py`. Each
core provides a `testbench` wrapper around its top
(`CVXIFCoreSupport.get_tb_wrapper_files()`), with the port list of the
corresponding SCAIE-V core's wrapper, so `sim/` drives it with the same bus
model, memory map and linker script:

| Core | Wrapper (`tools/cvxif_sim/`) | Bus | Memory map / linker script of |
|---|---|---|---|
| `CV32E40X_UPSTREAM` | `cvxif_e40x_tb_wrapper.sv` | 2x OBI -> AXI4 (`obi_axi_adapter.sv`) | SCAIE-V CV32E40X |
| `CV32E40PX` | `cvxif_e40px_tb_wrapper.sv` | 2x OBI -> AXI4 | SCAIE-V CV32E40X |
| `CVA6_UPSTREAM` | `cvxif_cva6_tb_wrapper.sv` | AXI4 (`noc_req_t`/`noc_resp_t` flattened) | SCAIE-V CVA6 |

`EXCEPTION_BASE` is 0 for the two OBI cores (their tops tie `mtvec_addr_i` to
0). No interrupt is needed: a test ends with a write to the `CTRL_BASE` block.

In `tools/run_integration_tests.py` the interface rules out RdPC
(`CoreFeature.PC`), `always` blocks (`CoreFeature.Always`), memory access,
control flow and decoupled writeback for all three cores. `CV32E40X_UPSTREAM`
and `CV32E40PX` declare `CoreFeature.CustomRegs` (ANTDOTP passes on both);
`CVA6_UPSTREAM` stays at `CoreFeature.NONE` — custom registers are unsafe there
(`commit_kill = 0`). No current template needs `CustomRegs` without also
needing `Memory` or `Control`, so the flag adds no test yet.

ANTDOTP used to hang `CV32E40X_UPSTREAM`: the out-of-order result emitter bids
only at WrRD stages, so an instruction without a WrRD (SETUP, ANTMACR,
ANTDOTP8ACCR — they only write custom registers) never produced its result
transaction, and CV32E40X waits in WB for one per accepted offload regardless
of `issue_resp.writeback` (`CV32E40PX` only tracks pending writebacks, which hid
it). `cvxif_glue_gen.py` now keeps in-order emission for an ISAX with such an
instruction. The generated protocol testbench catches the old behaviour
("result id 4 != expected 1"). Verified: DOTPROD, SBOX,
SPARKLE, SQRT_STALL, SWITCHOP and both `NO_ISAX` baselines on all three cores
(21/21), plus XCOREV_DOTP and XCOREV_SIMD_ADD_SUB_AVG on `CV32E40X_UPSTREAM`
and ANTDOTP (`antdotp.cpp`, `antdotp_overlap.cpp`) on both CV32E40 cores.

What the cocotb flow does not cover is the generated protocol testbench
(`CVXIF_GEN_PROTOCOL_TB`): killing an entry mid-datapath and the
`result.rd`/`result.we` fields are reached by nothing else.

The standalone runners described in the rest of this document
(`run.sh`, `run_cva6.sh`, `run_e40px.sh`, their `tb_*.sv` and `gen_test*.py`)
are **retired** and live in `tools/cvxif_sim/legacy/` (see its README); read
`tools/cvxif_sim/<file>` below as `tools/cvxif_sim/legacy/<file>`. They still
run, and they are where the numbers quoted below come from.

## End-to-end simulation on CV32E40X (retired standalone runner)

`tools/cvxif_sim/run.sh <isax-output-dir> [name]` runs a real RISC-V program on
an **unmodified** CV32E40X (`deps/cv32e40x`, registered as
`CORE_CV32E40X_UPSTREAM` by `cores/CV32E40X_upstream.py`) with the generated
coprocessor on the X-interface:

```
tools/cvxif_sim/run.sh outputs/run_N sparkle
```

- `cvxif_e40x_top.sv` instantiates upstream `cv32e40x_core` directly. No SCAL,
  no SCAIE-V hooks — the ISAX reaches the core only through `cv32e40x_if_xif`.
  The one core change is `core_patches/cv32e40x_xif_sticky_issue_resp.patch`
  (see below).
- `gen_test.py` emits the test program (custom instructions as `.word`) and the
  golden result stream from the same model, then assembles and links it.
- `tb_e40x.sv` is a unified OBI memory plus an MMIO tap; the program stores each
  result, the testbench compares against the golden stream, and XIF probes
  assert that instructions were really offloaded, rejected and killed.
- The script then reruns with `cvxif_coproc_null` (a coprocessor that claims
  nothing) as a **negative control** and requires it to fail, so a pass cannot
  be vacuous.

Result for `sparkle`: `results=35/35 errors=0`, with
`offloaded=69 rejected=10 killed=13 results=66` — 3 of the offloads were
speculative instructions killed behind a trapping illegal instruction and
correctly re-executed afterwards.

### Gotchas found while bringing this up

- **`mtvec.base` is WARL and 128-byte aligned** (`CSR_BASIC_MTVEC_MASK =
  32'hFFFFFF80`). A trap handler that is merely 4-byte aligned silently vectors
  to the wrong address. `gen_test.py` uses `.balign 128`.
- **CSR instructions are offered on the issue interface**, not just illegal
  ones (`issue_valid = instr_valid && (illegal_insn || csr_en)`), because
  CV-X-IF lets a coprocessor implement custom CSRs. Rejecting them is correct,
  but every rejection produces a `commit_kill` — see the commit-gate note above.
- **A taken branch cannot strand an offloaded instruction**: the core drops
  `issue_valid` when it kills ID, so the handshake never completes. The kill
  path is reached via rejected instructions, not via branch shadows.
- **A handshake cannot be retracted.** A transaction is accepted on the edge
  where `issue_valid` and `issue_ready` are both high; deasserting
  `issue_valid` in that same cycle does not undo it. The generated testbench
  models this explicitly (it completes the handshake before applying a flush) —
  getting it wrong there produced a host model that leaked instructions.

### ANTDOTP: custom registers on the real core

```
tools/cvxif_sim/run.sh <antdotp-output-dir> ANTDOTP
```

`gen_test_antdotp.py` targets what sparkle cannot reach: four ISAX-private
custom registers and the admission interlock. It builds chains of back-to-back
`ANTMAC` / `ANTDOTP8ACC` (each reads its accumulator at stage 0 and writes it at
stage 2, i.e. exactly the read-after-write the interlock exists to order),
interleaves `SETUP` (which rewrites `signInfo`/`primInfo`, read by every other
instruction), interleaves accumulator resets, and puts a rejected illegal
instruction in the middle while custom-register state is live.

Golden values come from the CoreDSL → Python model that `-coredsl-to-python`
emits, which is produced by the CoreDSL frontend independently of the
hardware-generation path under test.

Result: `results=54/54 errors=0`, `offloaded=80 rejected=4 killed=5 results=79
issue_stall_cycles=43` — the non-zero stall count is the interlock actually
back-pressuring the core. Scheduled under `CVXIF.yaml`, ANTDOTP has **zero**
`_spawn` ports (the PicoRV32-scheduled version of the same ISAX has several),
confirming the no-decoupling design end to end.

### XCoreVSimd: CORE-V SIMD on a core that has no SIMD

```
tools/cvxif_sim/run.sh <xcorevsimd-output-dir> XCoreVSimd
```

The motivating case. CV32E40X ships only RV32I/E + M + A + B — its parameters
are `RV32`/`M_EXT`/`A_EXT`/`B_EXT`/`X_EXT`, its decoders are `i`/`m`/`a`/`b`,
and there is no `COREV_PULP` and no SIMD anywhere in its RTL. CV32E40P bakes
the PULP extensions (hardware loops, post-increment load/store, SIMD) into the
core instead; CV32E40X drops them in favour of CV-X-IF. So running the CORE-V
SIMD ISA as an ISAX over the X-interface is exactly what the interface is for.

`gen_test_xcorevsimd.py` covers all 21 instructions in their three encoding
shapes — vector-vector, vector-scalar (rs2 broadcast) and
vector-scalar-immediate — with random and lane-boundary operands
(`0x7FFF7FFF`, `0x80808080`, ...), bursts of four back-to-back offloads, RAW
consumption of an ISAX result by the next instruction, rejected illegal
instructions, and a loop carrying a dependency through the ISAX. Encodings
*and* golden values are taken from the model's own `decoder_table`, so nothing
is retyped from the ISAX description by hand.

Result: `results=94/94 errors=0`, `offloaded=106 rejected=10 killed=13
results=103 issue_stall_cycles=16`. Two shadow-pipeline stages, no custom
registers, zero `_spawn` ports.

### Summary of the three end-to-end runs

| ISAX | stages | cust. regs | results | offloaded / rejected / killed | issue stalls |
|---|---|---|---|---|---|
| sparkle | 0..2 | 0 | 35/35 | 69 / 10 / 13 | 0 |
| ANTDOTP | 0..3 | 4 | 54/54 | 80 / 4 / 5 | 43 |
| XCoreVSimd | 0..1 | 0 | 94/94 | 106 / 10 / 13 | 16 |

All three with a null-coprocessor negative control that fails as required.

### Concurrency: commit-gated vs speculative admission

CV-X-IF is designed for overlap — the `id` field, the id-uniqueness rules and
the permission for out-of-order results all exist so several offloaded
instructions can be in flight. Whether you get any depends on when the glue
admits an instruction, and `cvxif_glue_gen.py` supports both choices.

**Commit-gated (default).** An instruction enters the ISAX pipeline only after
the core marks it non-speculative. Nothing inside the ISAX is ever speculative,
so `RdFlush` ties to 0, custom registers need no rollback, and the admission
interlock is the whole hazard story. The cost is that admission cannot happen
until the *previous* result has been consumed, so execution serialises.

**Speculative (`--speculative`).** Admission happens at the issue handshake
instead; each in-flight entry carries a commit bit, updated by id as commits
arrive, and the *result* transaction is held until that bit is set. The spec
forbids only speculative result transactions, not speculative execution. A
killed entry is dropped in place — there is no rollback, so this requires an
ISAX with **no custom registers**; the generator refuses otherwise.

Measured on the real core, 64 back-to-back offloads with nothing in between:

| ISAX | stages | mode | cycles/offload | max in ISAX datapath | max outstanding |
|---|---|---|---|---|---|
| `CV_ADD_H` | 2 | commit-gated | 5.62 | 1 | 2 |
| `CV_ADD_H` | 2 | speculative | **2.33** | **2** | 3 |
| `sparkle_ell` | 3 | commit-gated | 6.62 | 1 | 2 |
| `sparkle_ell` | 3 | speculative | **2.67** | **3** | 3 |

Roughly **2.4-2.5x** throughput, and the datapath now fills to its full depth.
The decisive change is the scaling: commit-gated costs exactly +1.00 cycle of
throughput per ISAX stage (5.62 -> 6.62), which is the signature of
serialisation; speculative costs +0.34 (2.33 -> 2.67), i.e. depth buys latency
and no longer costs throughput. `issue_stall_cycles` drops from 63/64 to 0 —
the glue stops back-pressuring the core entirely.

This also corrects an earlier reading of these numbers: CV32E40X does *not*
cap concurrency at 2. It sustains **3** outstanding once the coprocessor stops
serialising; the cap of 2 was an artifact of commit-gated admission, not a
property of the core.

Two bugs specific to speculative admission, both found by the protocol
testbench and fixed:

- **Kill/admit race.** `ib_go` no longer requires `ib_commit_q`, so a
  `commit_kill` and an admission could fire in the same cycle: the buffer was
  cleared while the same entry was admitted into stage 0, leaving a zombie with
  no commit ever coming. `ib_go` now excludes `ib_kill`. Impossible in the
  commit-gated build, where `ib_go` needs `ib_commit_q` and `ib_kill` needs
  `~ib_commit_q`.
- **Testbench id allocation.** The host model allocated ids from a free-running
  counter, which violates the spec's "ids unique among in-flight instructions"
  once the coprocessor holds several at once. It now allocates the lowest id
  not currently live. (The model also dropped killed expectations by queue
  position rather than by id — latent in commit-gated mode, wrong as soon as a
  newer expectation could sit behind the killed one.)

So: keep the default for ISAXes with architectural state, use `--speculative`
for pure datapath ISAXes and get the pipelining back.

### What the CV32E40X runs do and do not cover

The end-to-end runs and the generated protocol testbench cover different
things, and the split is worth stating so the green core results are not read
as more than they are.

Measured kill coverage (speculative sparkle):

| `commit_kill` lands in | CV32E40X run | protocol testbench |
|---|---|---|
| input buffer | 3 of 13 | 71 |
| **ISAX datapath** | **0** | **1127** |
| result register | 0 | 0 |

**Not covered by the core runs:**

- *Killing an entry already executing in the ISAX datapath* (speculative mode
  only). Structural, not a weak test program: CV32E40X offloads exactly one
  instruction into a trap shadow and kills it the next cycle, while it is still
  in the input buffer. Widening the shadow to four offloads per trap and 25
  kills still yields zero datapath kills. The path is defensive code against
  hosts with more offload depth, and is verified only by the protocol
  testbench.
- *`result.rd` and `result.we`.* The core derives rd from `instr[11:7]` itself
  and ignores both fields (see the writeback section), so the core runs give
  them no coverage. The protocol testbench checks them.

**Covered by the core runs:** decode / accept / reject, issue back-pressure,
the commit gate, in-order result handover, the buffer-kill path with correct
re-execution after the trap, custom registers and their admission interlock
(ANTDOTP), operand staging, RAW through the core's forwarding, and the
speculative-mode throughput and datapath occupancy figures.

### Two CV32E40X issues this surfaced

Both are in the core, not the coprocessor: throughout, the XIF result
transactions carried the correct `id`/`rd`/`we`/`data` and the custom registers
chained correctly (`macAcc` 0 → 0x40 → 0x80 → 0xc0 → 0x100). Both are present
in pristine upstream master HEAD — neither is a SCAIE-V-fork regression (the
offending lines date from 2021 and 2021 respectively, per `git log -S`).

1. **Dropped register writeback** — `xif_insn_accept` is made sticky via
   `xif_accepted_q`, but the `issue_resp`-derived flags were not:

   ```systemverilog
   assign xif_we = xif_issue_if.issue_valid && xif_issue_if.issue_resp.writeback;
   ```

   `issue_valid` drops one cycle after the handshake, so an offloaded
   instruction still waiting in ID for a busy EX was sampled into `id_ex_pipe`
   with `rf_we = 0` and lost its writeback. Every offloaded instruction after
   the first in a burst was silently dropped.

   This is a genuine bug, not interface implementation freedom: the spec makes
   `issue_resp` valid only while `issue_valid` is 1, so the CPU must latch what
   it needs at the handshake — which it does for `accept` (`xif_accepted_q`) but
   not for `writeback`. A coprocessor cannot work around it (ours holds
   `writeback` stable, since it is combinational on the stable `issue_req.instr`;
   the core ANDs it with its own retracted `issue_valid`). Accepting an
   instruction, consuming its result transaction and then discarding the write
   is not a permitted reading of any part of the spec.

   **Known upstream and still unfixed** in master HEAD: issue
   [#941](https://github.com/openhwgroup/cv32e40x/issues/941) "[XIF] Coprocessor
   XIF Issue response not sampled by ID-EX pipeline registers" (open since
   2023-09, with waveforms showing the same lost writeback), and PR
   [#891](https://github.com/openhwgroup/cv32e40x/pull/891) "Fixed XIF Control
   Signals for Sticky Accept/Reject" (open since 2023-07) proposing the same
   fix. The core's own `TODO:XIF` names it too. Applied here as
   `core_patches/cv32e40x_xif_sticky_issue_resp.patch`, inert when
   `X_EXT = 0`.

2. **Duplicated store transactions** (not fixed; its deadlock is, see 3) — `lsu_valid_o = lsu_en_gated`
   is not qualified by the EX→WB handshake, so a store parked in EX re-issues
   its OBI transaction every time the LSU's outstanding counter drains. That
   happens constantly here because a slow coprocessor blocks WB (`xif_waiting`).
   The obvious remedy — halting EX while WB waits — would **deadlock**, since
   `commit_valid` requires `!halt_ex` and the coprocessor waits for commit
   before executing. Left alone: duplicate writes of the same value to the same
   address are architecturally harmless, so `gen_test_antdotp.py` writes results
   to distinct addresses in RAM and the testbench checks the array at the end,
   instead of using a non-idempotent streaming MMIO port. It would matter for a
   real write-sensitive peripheral.

   Measured on pristine upstream: **124 OBI write transactions for 54 store
   instructions**. Not an artifact of the always-grant memory model — with a
   one-cycle grant bubble it is still 96 for 54 (fewer only because the bubble
   halves the re-issue rate). Whether this is reachable without X_EXT was not
   tested; WB stalling for many cycles is what triggers it, and outside X_EXT
   that is rare. No upstream issue documents it, though
   [#653](https://github.com/openhwgroup/cv32e40x/issues/653) "[XIF] LSU may
   send mpu_status to WB too early" covers the same scenario (a load/store held
   in EX while WB awaits an XIF result), so the area is known-fragile. Left
   unfixed deliberately: it needs a change to the LSU/EX handshake, which is a
   bigger call than a lost-writeback latch.

3. **Result accepted while WB cannot advance -> deadlock** (fixed) — a
   consequence of 2 that the standalone testbench could not show. Once the
   parked store has transfers outstanding (`cnt_q != 0`), `lsu_ready_i`, and
   with it `wb_ready_o`, follows the bus response. `xif_result_if.result_ready`
   ignored that (`instr_valid && xif_en`), so the offloaded instruction in WB
   consumed its result in a cycle where it could not leave WB; from the next
   cycle on `xif_waiting` held forever — the coprocessor had delivered, the
   core waited for a second result — and the store re-issued its transaction
   endlessly. It takes a memory whose response needs more than one cycle:
   `tb_e40x.sv` answers in one, the cocotb flow's OBI->AXI4 adapter does not.
   First seen with `custom_tbs/sbox.cpp` (four dependent offloads, then four
   stores): the first store was written ~666k times until the cycle timeout.
   The timing decides whether it strikes — the same program passed with the
   commit-gated glue.

   Fix: `core_patches/cv32e40x_xif_result_ready_wb.patch` — `result_ready` is
   withheld unless WB can advance (`lsu_ready_i`, no halt; still asserted under
   `kill_wb`), and `xif_waiting` is keyed on the result *handshake* so a result
   that is merely offered does not retire the instruction. The coprocessor has
   to hold `result_valid` until `result_ready` anyway. Inert when `X_EXT = 0`;
   present in pristine upstream master d952cd63. CV32E40PX and CVA6 do not
   show it: the same programs pass there without an equivalent change (CV32E40PX
   has two result-path patches of its own, registered in `cores/CV32E40PX.py`).

## End-to-end simulation on CVA6

`tools/cvxif_sim/run_cva6.sh <isax-output-dir> [name]` is the CVA6 twin of
`run.sh`. It runs the same programs on **pristine upstream `openhwgroup/cva6`**
(`deps/cva6_upstream`, a worktree of the SCAIE-V fork's own base commit
`bcb0f7de`, verified to contain no `scaiev` files), in the `cv32a60x` config:
rv32, no MMU, and `CvxifEn = 1` already set upstream, so **the core needs no
patch and no config edit at all** — unlike CV32E40X, which needs
`cv32e40x_xif_sticky_issue_resp.patch`.

```
tools/cvxif_sim/run_cva6.sh outputs/run_N sparkle
```

- `cvxif_cva6_top.sv` is upstream `corev_apu/src/ariane.sv` with one change: the
  `gen_cvxif` block that instantiates `cvxif_example_coprocessor` is replaced by
  the generated `cvxif_coproc_cva6_<name>`.
- `tb_cva6.sv` is a behavioural AXI4 slave (64-bit, INCR bursts) plus an MMIO tap
  in the uncached region, since CVA6 talks AXI rather than OBI.
- The source list comes from CVA6's own `core/Flist.cva6`, expanded for
  `CVA6_REPO_DIR` / `HPDCACHE_DIR` / `TARGET_CFG` and nested `-F` includes (183
  files) — not a hand-maintained list.
- `cores/CVA6_upstream.py` registers the core as `CORE_CVA6_UPSTREAM` with
  `has_isax_support() = False` (nothing for SCAIE-V to splice into) and the
  CVXIF datasheet.

### Verified runs on upstream CVA6

| ISAX | instructions | results | offloads | outcome |
|---|---:|---:|---:|---|
| sparkle | 4 | 35/35 | 67 | PASS |
| XCoreVSimd (`XCOREV_SIMD_ADD_SUB_AVG`) | 30 | 121/121 | 131 | PASS |
| ANTDOTP (4 custom registers) | 8 | 53/54 | 80 for 79 | FAIL -- see below |

Each run ends with the null-coprocessor negative control, which must and does
fail. `XCOREV_SIMD_FULL` (51 instructions) fails on CVA6 *and* on CV32E40X at
the same stale value, so it is an ISAX/test-variant mismatch (14 encodings the
test emits that this build does not implement), not a CVA6 issue.

### CVA6 speaks CV-X-IF v1.0, the glue speaks rev 458c8a73

Three differences, and `cvxif_glue_gen.py --cva6-wrapper` is exactly the
translation between them:

| | rev 458c8a73 (CV32E40X) | v1.0 (CVA6) |
|---|---|---|
| Channels | separate SV interfaces | one `cvxif_req_t`/`cvxif_resp_t` struct pair |
| Source operands | in `issue_req` | own `register` channel |
| Which operands are needed | not expressible | `issue_resp.register_read` |
| Memory interface | present | removed |
| Result side-band | `exc`/`exccode`/`err`/`dbg`/ECS | none |

CVA6 builds with `X_ISSUE_REGISTER_SPLIT = 0`, so `register_valid == issue_valid`
and the operands still arrive in the issue cycle — which is what the glue
assumes. A core with the split enabled would need a buffer in the wrapper.
`register_read` is driven from the ISAX's own decode (`{dec_use_rs2,
dec_use_rs1}`, exposed as the new glue output `x_issue_resp_regread_o`) so CVA6
does not stall waiting for an rs2 field that a custom encoding uses as an
immediate.

CVA6 also raises `commit_valid` in the same cycle as the issue handshake, which
the glue's commit gate already handles (`new_commit_hit`), so commit-gated
admission costs nothing here — unlike CV32E40X, where commit lags issue and
serialises execution.

### CVA6 never kills, and that breaks stateful ISAXes

`cvxif_issue_register_commit_if_driver.sv` hardwires

```systemverilog
/* WARNING */
// Always commit since speculation in execute in not possible : TODO to be verified
assign commit_o.commit_kill = 1'b0;
```

The premise is false: an *older* instruction can still trap. Then the offloaded
instruction executes in the coprocessor, the trap flushes it, the handler skips
the faulting word, and the instruction is re-fetched and executed a **second**
time — with no kill in between to discard the first.

Measured, on the ANTDOTP program's "rejected illegal instruction between
accumulations" section: **80 offloads for 79 architectural ISAX instructions**,
exactly one double-execution, and result #52 wrong by exactly one extra MAC
(`ffffffdc` vs `ffffffee`). The same program passes 54/54 on CV32E40X, which
kills the speculative copy.

Consequences:

- **Stateless ISAXes are fine.** The orphaned result is simply never consumed by
  the core. sparkle passes 35/35.
- **ISAXes with custom registers are not.** `--cva6-wrapper` therefore refuses
  them with a diagnostic; `--allow-custom-regs` (or `ALLOW_CUSTOM_REGS=1` for
  `run_cva6.sh`) overrides it, and is only safe if no ISAX instruction is ever
  flushed.
- It is not fixable coprocessor-side: CVA6 offers no retirement signal over the
  interface (`cvxif_fu` even hardwires `result_ready_o = 1`). The fix belongs in
  the core — drive `commit_kill` on flush.

### The two cores side by side, same sparkle program

| | offloaded | rejected | killed | results | issue-stall cycles |
|---|---:|---:|---:|---:|---:|
| CV32E40X | 69 | 10 | 13 | 66 | 0 |
| CVA6 | 67 | 3 | 0 | 67 | 48 |

CVA6 offloads == results, because nothing is ever killed; CV32E40X produces
three fewer results than offloads for exactly that reason. CV32E40X's extra
rejects are the CSR instructions it also offers on the issue interface, which
CVA6 does not. The 48 stall cycles are CVA6's in-order issue back-pressuring
against the glue's single-entry input buffer, where CV32E40X simply retries.

## End-to-end simulation on CV32E40PX

`tools/cvxif_sim/run_e40px.sh <isax-output-dir> [name]` runs the same programs on
**pristine upstream `x-heep/cv32e40px`** (`deps/cv32e40px`, master HEAD
`1f75b23`; the repo was transferred from esl-epfl to the x-heep org — the old
GitHub URL redirects to the same repository).

Be careful which core this is — three similar names are in play:

| Core | Repo | X-interface |
|---|---|---|
| CV32E40P | openhwgroup/cv32e40p | none |
| CV32E40X | openhwgroup/cv32e40x | CV-X-IF as a SystemVerilog `interface` |
| **CV32E40PX** | x-heep/cv32e40px | CV-X-IF as packed structs (`cv32e40px_core_v_xif_pkg`) |

CV32E40PX is the CV32E40P derivative that adds CV-X-IF (plus RVB/RVP/RVK); it is
the core X-HEEP uses for coprocessor work. It implements the **same interface
revision as CV32E40X** — `issue_req` carries the operands, `issue_resp` has
dualwrite/dualread/loadstore/ecswrite/exc, the result carries the full
ecs/exc/err/dbg side-band — so `cvxif_glue_gen.py --e40px-wrapper` is a
field-for-field unpack with none of the semantic translation the CVA6 (v1.0)
wrapper needs. The memory map, testbench and test programs are CV32E40X's,
unchanged.

Two build notes: the package sets `X_NUM_RS = 3`, so `rs` is three words wide
(the glue is parameterised and reads rs1/rs2 only); and both of the repo's
manifests (`Bender.yml`, `src_files.yml`) are stale — they still list the
pre-rename `cv32e40p_*` files — so the runner globs `rtl/` instead, taking the
flop register file and skipping `cv32e40px_fp_wrapper.sv` (instantiated only
inside `generate if (FPU)`, and it would drag in the vendored FPU).

Verified: sparkle **35/35**, 66 offloads, 3 rejects, negative control failing as
required. `commit_kill` was never exercised — like CVA6, CV32E40PX did not kill
anything in this program.

### The result payload is now gated with `result_valid`

Bringing CV32E40PX up surfaced one real interaction, and it is worth
understanding because the glue changed for **all** cores as a result.

`cv32e40px_x_disp.sv` suppresses its RAW interlock like this:

```systemverilog
dep = ~x_illegal_insn_n & ((regs_used_i[0] & scoreboard_q[x_rs_addr_i[0]]
                            & (x_result_rd_i != x_rs_addr_i[0])) | ...);
```

There is no `& x_result_valid_i`. The glue used to drive `x_result_rd_o`
continuously from the last completed transaction, so between results the core saw
a stale `rd` — and whenever the *next* ISAX instruction wrote the same register,
the term `(x_result_rd_i != rs)` went false and cancelled the stall. A dependent
instruction then read the register one writeback too early. The symptom was
unmistakable once every mismatch was printed rather than just the first: **every
result shifted by one**, 25 of 35 wrong, with the correct ones exactly where an
unrelated instruction sat between the ISAX instruction and its consumer.

Strictly this is a core bug — the spec leaves the result fields undefined while
`result_valid` is 0, so a core must not read them. But defending against it costs
five gates, so the generator now emits

```systemverilog
assign x_result_rd_o = res_valid_q ? res_rd_q : 5'b0;
assign x_result_we_o = res_valid_q ? (X_RFW_WIDTH/32)'(res_we_q)
                                   : (X_RFW_WIDTH/32)'(1'b0);
```

CV32E40X (35/35) and CVA6 (35/35, and XCoreVSimd 121/121) are unaffected by the
change — they never read the fields while invalid — and CV32E40PX passes with it.

### Three cores, same sparkle program

| | offloaded | rejected | killed | results | issue-stall cycles |
|---|---:|---:|---:|---:|---:|
| CV32E40X | 69 | 10 | 13 | 66 | 0 |
| CV32E40PX | 66 | 3 | 0 | 66 | 64 |
| CVA6 | 67 | 3 | 0 | 67 | 48 |
