# NailGun — Custom ISAX Integration Flow

NailGun configures and drives an end-to-end flow for custom RISC-V ISA
extensions (ISAXes):

```
CoreDSL → Treenail → Longnail → SCAIE-V → extended RISC-V core
                                        → cocotb simulation
                                        → LibreLane (synthesis)
```

It is a Python orchestration wrapper: [`dispatch.py`](dispatch.py) loads a
[Kconfig](https://github.com/zephyrproject-rtos/Kconfiglib)-based
configuration, resolves an entry point, and runs an iterative
HLS / integration / simulation / synthesis loop until the synthesis
plugin reports no further critical-path feedback.

> **Heads up.** Two pieces of the flow — `longnail` (HLS scheduler) and
> `splitop-gen` (split-datapath operator generator) — are closed-source
> and not distributed publicly. The CoreDSL-driven HLS path therefore
> cannot run from this repository alone. Everything else is fully
> usable: hand-written SystemVerilog ISAXes (`SV_ENTRY_POINT`), the
> baseline-core flow (`NO_ISAX_ENTRY_POINT`), the dynamic-ISAX clang
> patcher (`ONLY_PATCH_CC`), and any standalone Treenail / Shortnail /
> SCAIE-V work — all of it runs on the open components.

---

## Setup

### Standalone (recommended for external users)

```sh
git clone https://github.com/esa-tu-darmstadt/Nailgun.git
cd Nailgun
./setup.sh
```

`setup.sh` replaces the `deps` symlink (used inside the meta-repo) with
a real directory and clones the open-sourced tools into `deps/`:

| Path                       | Source                                          |
| -------------------------- | ----------------------------------------------- |
| `deps/treenail`            | github.com/esa-tu-darmstadt/Treenail            |
| `deps/shortnail`           | github.com/esa-tu-darmstadt/Shortnail           |
| `deps/scaie-v`             | github.com/esa-tu-darmstadt/SCAIE-V-2.0         |
| `deps/llvm_dynamic_isax`   | github.com/esa-tu-darmstadt/llvm_dynamic_isax   |
| `deps/yosys-slang`         | github.com/povik/yosys-slang                    |

By default `setup.sh` also runs each tool's build (`gradle` for
treenail, `make` for yosys-slang, the CIRCT/LLVM build for shortnail —
this last one needs ~100 GB of disk and pulls a multi-hour compile).
For a fast clone-only pass:

```sh
BUILD=0 ./setup.sh
```

Other knobs:

| Variable             | Effect                                           |
| -------------------- | ------------------------------------------------ |
| `BUILD=0`            | Clone and submodule-init only; skip every build. |
| `SKIP_YOSYS_SLANG=1` | Don't clone or build yosys-slang.                |

`llvm_dynamic_isax` is *not* built by `setup.sh`;
[`toolchain.py`](toolchain.py) configures and builds it lazily on first
pipeline run.

### Toolchain prerequisites

The full set of host packages needed to clone, build, and simulate is
the source-of-truth list in [`flake.nix`](flake.nix) (see
`env_packages` and the `devShell` block). With Nix + flakes enabled,

```sh
nix develop
```

drops you into a shell with everything pinned to the same versions
upstream CI uses. If you'd rather install dependencies through your
distro's package manager, mirror that list — it's the canonical
inventory of what the pipeline expects.

---

## Basic usage

Generate the Kconfig menu (scans `isaxes/` and `cores/`) and pick a
core + ISAXes interactively:

```sh
make            # equivalent to: make menuconfig
```

Run the pipeline against the saved `.config`:

```sh
make build
```

Outputs land under `outputs/run_<N>/`, including the patched RISC-V
core, generated ISAX SystemVerilog, and a copy of the `.config` used.

`make clean` removes `build/`; `make mrproper` also clears `outputs/`
and `test_results/`.

### Available entry points

`dispatch.py` routes through one of six mutually exclusive entry points
(plus the orthogonal `ONLY_PATCH_CC` toggle). Each one fixes where the
pipeline starts; the downstream stages (SCAIE-V integration,
simulation, synthesis) are shared. The Kconfig source for all of them
lives in [`configs/advanced_Kconfig`](configs/advanced_Kconfig) under
*menu "Advanced Options"*.

| Kconfig entry point             | Input                                          | Runs without longnail?  |
| ------------------------------- | ---------------------------------------------- | :---------------------: |
| `DEFAULT_ENTRY_POINT`           | CoreDSL `.core_desc` → Treenail → Longnail HLS | ❌ needs `longnail`     |
| `COREDSL_MLIR_ENTRY_POINT`      | Pre-compiled CoreDSL MLIR                      | ❌ needs `longnail`     |
| `PREPARED_MLIR_ENTRY_POINT`     | MLIR after `prepare-schedule-lil`              | ❌ needs `longnail`     |
| `SOLUTION_MLIR_ENTRY_POINT`     | MLIR with a fixed scheduling solution          | ❌ needs `longnail`     |
| `SV_ENTRY_POINT`                | Hand-written ISAX SystemVerilog + SCAIE-V YAML | ✅                      |
| `NO_ISAX_ENTRY_POINT`           | None — baseline core only                      | ✅                      |

In addition, the `ONLY_PATCH_CC` toggle (also in *Advanced Options*)
short-circuits the flow at the dynamic-ISAX clang build (skips HLS
scheduling, HW-gen, SCAIE-V, RTL, and simulation). It only needs the
ShortNail passes (`-merge-multiple-isaxes`, `-analyze-isax`), which are
provided by the open `shortnail-opt` binary, so this mode also runs
without longnail.

#### How to select one

Both selection paths set the same Kconfig symbols — interactive
menuconfig and CI env-var driven — pick whichever fits your workflow.

| Entry point                 | `make menuconfig` path                                                  | `make ci` env vars                                                            |
| --------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `DEFAULT_ENTRY_POINT`       | *Advanced Options → Alternate Entrypoint → None*                        | (default — nothing to set)                                                    |
| `NO_ISAX_ENTRY_POINT`       | *Advanced Options → Alternate Entrypoint → No ISAX*                     | `NO_ISAX=y`                                                                   |
| `SV_ENTRY_POINT`            | *Advanced Options → Alternate Entrypoint → Use (System-)Verilog ISAX as entrypoint*, then *SV entrypoint settings* | `SV_ENTRY_POINT_PATH=…` and `SV_ENTRY_POINT_ISAX_YAML_PATH=…`                  |
| `COREDSL_MLIR_ENTRY_POINT`  | *Advanced Options → Alternate Entrypoint → Use a CoreDSL MLIR file as entrypoint*, then *Path to mlir file* | `COREDSL_MLIR_ENTRY_POINT=y` + `MLIR_ENTRY_POINT_PATH=…`                       |
| `PREPARED_MLIR_ENTRY_POINT` | *Advanced Options → Alternate Entrypoint → Use a for scheduling prepared MLIR file as entrypoint* | `PREPARED_MLIR_ENTRY_POINT=y` + `MLIR_ENTRY_POINT_PATH=…`                       |
| `SOLUTION_MLIR_ENTRY_POINT` | *Advanced Options → Alternate Entrypoint → Use a MLIR file containing the scheduling solutions as entrypoint* | `SOLUTION_MLIR_ENTRY_POINT=y` + `MLIR_ENTRY_POINT_PATH=…`                       |
| `ONLY_PATCH_CC` (modifier)  | *Advanced Options → ONLY run HLS and add compiler support for the ISAXes* | `ONLY_PATCH_CC=y`                                                             |

The CI side is handled by [`gen_ci_config.py`](gen_ci_config.py): a
handful of vars are translated explicitly (the `SV_ENTRY_POINT_*` /
`NO_ISAX` cases above), and any other variable whose name matches a
Kconfig symbol is passed through 1:1 — that's why
`COREDSL_MLIR_ENTRY_POINT=y`, `MLIR_ENTRY_POINT_PATH=…`, and
`ONLY_PATCH_CC=y` work directly.

The open Shortnail passes (`-coredsl-to-python`,
`-merge-multiple-isaxes`, `-emit-isax-encodings`, `-analyze-isax`) can
also be invoked directly outside the pipeline if you just want to
experiment with CoreDSL → MLIR.

### CI / scripted usage

For non-interactive runs, set environment variables that map to
Kconfig symbols and use `make ci`:

```sh
CORE="CVA5" \
ISAXES="SBOX" \
SIM_ENABLE="y" \
TB_PATH="custom_tbs/sbox.cpp" \
TB_EXPECTED_PATH="custom_tbs/sbox_expected.txt" \
make ci
```

The full mapping lives in [`gen_ci_config.py`](gen_ci_config.py); any
variable whose name matches a Kconfig symbol is also passed through
1:1. [`tools/run_integration_tests.py`](tools/run_integration_tests.py)
contains a much wider set of `make ci` invocations across cores and
ISAXes.

### HDL-based ISAXes (`SV_ENTRY_POINT`)

This is the recommended ISAX entry point in the open distribution. If
you already have a hand-written ISAX top module plus a SCAIE-V YAML,
you can bypass the CoreDSL → MLIR → HLS stages:

1. `make menuconfig`
2. *Advanced Options → Alternate Entrypoint*
3. *Use (System-)Verilog ISAX as entrypoint*, then ESC
4. *SV entrypoint settings* — set the path to your ISAX top module and
   the ISAX YAML
5. Save and exit, then `make build`

Your files are copied into `outputs/run_<N>/<core>/`, alongside
`CommonLogicModule.sv` and the patched core sources.

> NailGun assumes the ISAX module name matches the YAML filename. If
> they differ, fix the instantiation in the generated top module
> (e.g. `Vex_top.sv` for VexRiscv).

---

## Simulation testbench YAML

NailGun supports complex test cases described by a YAML file. In the
simplest form the YAML lists the source files; compilation always uses
the dynamic-ISAX clang.

```yaml
# custom_tbs/dotprod.yaml
files:
  - dotprod.cpp
  - dotprod_helpers.cpp
```

Without further configuration, simulation memory is fully managed by
cocotb.

### Custom memory configuration

For ASIC-flow evaluation you'll often want SRAM-compiler memories,
which are typically smaller than the 1 MB allocated by the default
testbench (`sim/test_default.py`). Move closer to hardware
incrementally by adding a `memory` block to the YAML:

```yaml
memory:
  linker_script: imem_dmem_16K.ld
```

The linker script must sit next to the YAML. Once you start customising
memory you may also need to adjust the testbench (input/output data
handling).

### Pre-loading memories from hex files

To initialise SRAM models with program content, add a `convert_to_hex`
sub-block. Each entry names a hex file and supplies its size,
word width (bytes), and the ELF sections to dump:

```yaml
memory:
  linker_script: imem_dmem_16K.ld
  convert_to_hex:
    imem.hex:
      instance_parameter: /top_module/some_instance/memory_instance/parameter_name
      size: 0x4000
      word_width: 4
      sections:
        - .text.init
        - .text
    dmem.hex:
      instance_parameter: /top_module/other_instance/some_other_memory_instance/parameter_name
      size: 0x4000
      word_width: 4
      sections:
        - .input_data
        - .sdata
```

`instance_parameter` is the hierarchical path of a memory parameter
that should receive the hex file path for pre-loading. *This option is
currently Questa-only.*

### Gate-level simulation

> *Currently Questa-only.*

For netlist verification or power analysis, add a `gls` block:

```yaml
gls:
  netlist: /path/to/netlist.v
  sdf:     /path/to/file.sdf      # optional; enables SDF-annotated GLS
  cells:
    - /path/to/cells_a.v
    - /path/to/cells_b.v
```

If `SDF_FILE` is non-empty in the cocotb Makefile, GLS runs SDF-
annotated; otherwise it runs unit-delay. SDF defaults to `-sdfmax`;
override with `SDFTYPE=-sdfmin` or `SDFTYPE=-sdftyp` on the `make`
command line.

---

## Plugins

NailGun supports a rudimentary plugin mechanism: `dispatch.py` walks
`plugins/*/` for files matching the active entry point name (e.g.
`synthesis_plugin.py`). LibreLane ships as the reference synthesis
plugin and feeds critical-path chains back into the optimisation
loop — use it as a template for further plugins.

---

## Gurobi

Some Longnail configurations use the commercial ILP solver
[Gurobi](https://www.gurobi.com/). Point the `GRB_LICENSE_FILE`
environment variable at your `gurobi.lic`, or fall back to the open
solvers selectable via `LN_ILP_SOLVER` / the Kconfig
*Longnail HLS settings* menu.

## Questa

To use Questa instead of Verilator, set:

- `MGLS_LICENSE_FILE` — path to your Mentor license
- `PATH` — include `…/questasim/bin/`

Defaults assumed by the integration tests:

```sh
export MGLS_LICENSE_FILE=/opt/cad/keys/mentor
export PATH=/opt/cad/mentor/questa/latest/questasim/bin:$PATH
```

Override either to point at a specific Questa installation.

---

## Repository layout

| Path                                  | Purpose                                                         |
| ------------------------------------- | --------------------------------------------------------------- |
| [`dispatch.py`](dispatch.py)          | Main orchestrator — runs the iterative pipeline                 |
| [`entrypoint.py`](entrypoint.py)      | Picks the entry point (CoreDSL / MLIR / SV / no-ISAX)           |
| [`treenail.py`](treenail.py), [`longnail.py`](longnail.py), [`scaiev.py`](scaiev.py), [`simulation.py`](simulation.py), [`toolchain.py`](toolchain.py) | Per-stage drivers |
| [`cores/`](cores)                     | `CoreSupport` modules per RISC-V core (CVA5, CVA6, Vex, Nax, …) |
| [`isaxes/`](isaxes)                   | CoreDSL ISAX definitions (`*.core_desc`); see [its README](isaxes/README.md) for the encoding table |
| [`custom_tbs/`](custom_tbs)           | Assembly / C++ / YAML testbenches with expected outputs         |
| [`sim/`](sim)                         | cocotb harness, peripherals, ISS, trace utilities               |
| [`plugins/`](plugins)                 | Plugin entry points (LibreLane is the reference)                |
| [`patches/`](patches)                 | Patches applied to cores / dependencies                         |
| [`configs/`](configs)                 | Kconfig fragments (Longnail, simulation, SCAIE-V, advanced)     |
| [`tools/`](tools)                     | Helper scripts, including `run_integration_tests.py`            |
| `deps/`                               | Populated by [`setup.sh`](setup.sh) (or the meta-repo symlink)  |

---

## License

[Apache License 2.0](LICENSE).
