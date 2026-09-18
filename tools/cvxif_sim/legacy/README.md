# Retired standalone CV-X-IF simulation runners

Retired 2026-09-18. The CV-X-IF cores (`CV32E40X_UPSTREAM`, `CV32E40PX`,
`CVA6_UPSTREAM`) are now simulated by the regular cocotb flow
(`SIM_ENABLE=y ... make ci`, and `tools/run_integration_tests.py`) through the
`cvxif_*_tb_wrapper.sv` wrappers one directory up. Nothing in the pipeline
calls the files in here any more; they are kept as a backup.

| File | What it was |
|---|---|
| `run.sh`, `run_e40px.sh`, `run_cva6.sh` | End-to-end runners: glue generation, test program, Verilator build, run, plus a null-coprocessor negative control that must fail |
| `tb_e40x.sv`, `tb_e40px.sv`, `tb_cva6.sv` | Self-checking SystemVerilog testbenches (zero-latency memory, result/done MMIO taps) |
| `gen_test*.py`, `testgen_common.py` | Test-program generators with golden values from the CoreDSL->Python model; `gen_test_merged.py` is the ~375-kernel characterisation image |

They still run from here (`tools/cvxif_sim/legacy/run.sh <isax-output-dir> [name]`;
the hooks `CVXIF_TESTGEN`, `MODEL_DIR`, `GLUE_FLAGS`, `SPECULATIVE`,
`CVXIF_MAX_CYCLES` are unchanged). Two things they do that the cocotb flow does
not:

* the negative control -- under cocotb, `NO_ISAX=y` runs the null coprocessor
  as a CPU-only baseline instead, and the `*_expected.txt` comparison is what
  proves the ISAX executed;
* coverage of kill-mid-datapath and the `result.rd`/`result.we` fields, which
  only the generated protocol testbench reaches (`CVXIF_GEN_PROTOCOL_TB`,
  unaffected by this move).

Caveat: `tb_e40x.sv`'s memory answers in one cycle, which is why it never
showed the CV32E40X deadlock fixed by
`core_patches/cv32e40x_xif_result_ready_wb.patch`. `run.sh` builds against
`deps/cv32e40x` in place and does not apply that patch.
