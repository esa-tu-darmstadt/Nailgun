// Testbench: CV32E40PX + CV-X-IF coprocessor running a real RISC-V program.
//
// Transformed from tb_e40x.sv: same OBI memory and MMIO tap, but CV32E40PX
// exposes the eXtension interface as packed structs rather than a
// SystemVerilog interface, so the activity probes read observation outputs
// brought out of cvxif_e40px_top instead of reaching into a `xif` instance.
//
// Unified OBI memory (instruction port read-only, data port r/w) plus an MMIO
// tap: the program stores each computed result to RESULT_ADDR and finally
// writes a non-zero word to DONE_ADDR. The captured stream is compared against
// the golden values in golden.svh (generated alongside the program).
`timescale 1ns/1ps

module tb_e40px;

  localparam int unsigned MEM_WORDS   = 65536;          // 256 KiB: the characterisation image (375 kernels) is ~80 KiB; the generators place the stack at CVXIF_STACK_TOP
  localparam logic [31:0] RESULT_ADDR = 32'h8000_0000;
  localparam logic [31:0] DONE_ADDR   = 32'h8000_0004;
  localparam logic [31:0] TRACE_ADDR  = 32'h8000_0008;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic        instr_req, instr_gnt, instr_rvalid;
  logic [31:0] instr_addr, instr_rdata;
  logic        data_req, data_gnt, data_rvalid, data_we;
  logic [3:0]  data_be;
  logic [31:0] data_addr, data_wdata, data_rdata;
  logic        core_sleep;

  logic xif_issue_valid, xif_issue_ready, xif_issue_accept;
  logic xif_commit_valid, xif_commit_kill, xif_result_valid, xif_result_ready;

  cvxif_e40px_top dut (
    .clk_i(clk), .rst_ni(rst_n),
    .boot_addr_i(32'h0000_0080), .fetch_enable_i(1'b1),
    .instr_req_o(instr_req), .instr_gnt_i(instr_gnt),
    .instr_rvalid_i(instr_rvalid), .instr_addr_o(instr_addr),
    .instr_rdata_i(instr_rdata),
    .data_req_o(data_req), .data_gnt_i(data_gnt), .data_rvalid_i(data_rvalid),
    .data_addr_o(data_addr), .data_be_o(data_be), .data_we_o(data_we),
    .data_wdata_o(data_wdata), .data_rdata_i(data_rdata),
    .core_sleep_o(core_sleep),
    .xif_issue_valid_o(xif_issue_valid), .xif_issue_ready_o(xif_issue_ready),
    .xif_issue_accept_o(xif_issue_accept),
    .xif_commit_valid_o(xif_commit_valid), .xif_commit_kill_o(xif_commit_kill),
    .xif_result_valid_o(xif_result_valid), .xif_result_ready_o(xif_result_ready));

  // ---- memory ------------------------------------------------------------
  logic [31:0] mem [0:MEM_WORDS-1];

  initial begin
    for (int i = 0; i < MEM_WORDS; i++) mem[i] = 32'h0;
    $readmemh("mem.hex", mem);
  end

  // Instruction port: always grant, respond next cycle.
  assign instr_gnt = instr_req;
  logic [31:0] instr_rdata_q;
  logic        instr_rvalid_q;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      instr_rvalid_q <= 1'b0;
    end else begin
      instr_rvalid_q <= instr_req & instr_gnt;
      if (instr_req & instr_gnt)
        instr_rdata_q <= mem[instr_addr[31:2] % MEM_WORDS];
    end
  end
  assign instr_rvalid = instr_rvalid_q;
  assign instr_rdata  = instr_rdata_q;

  // Data port: always grant, respond next cycle. Writes with byte enables.
  assign data_gnt = data_req;
  logic [31:0] data_rdata_q;
  logic        data_rvalid_q;

  int          n_results = 0;
  bit          done = 0;
  int          errors = 0;

  `include "golden.svh"

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      data_rvalid_q <= 1'b0;
    end else begin
      data_rvalid_q <= data_req & data_gnt;
      if (data_req & data_gnt) begin
        if (data_addr == RESULT_ADDR && data_we && !RESULT_IN_MEM) begin
          if (n_results >= N_GOLDEN) begin
            errors++;
            $display("ERROR result #%0d %08x: more results than expected (%0d)",
                   n_results, data_wdata, N_GOLDEN);
          end else if (data_wdata !== GOLDEN[n_results]) begin
            errors++;
            $display("ERROR result #%0d = %08x, expected %08x",
                   n_results, data_wdata, GOLDEN[n_results]);
          end
          n_results++;
        end else if (data_addr == TRACE_ADDR && data_we) begin
          $display("[trace] %08x", data_wdata);
        end else if (data_addr == DONE_ADDR && data_we) begin
          done <= 1'b1;
        end else begin
          if (data_we) begin
            for (int b = 0; b < 4; b++)
              if (data_be[b])
                mem[data_addr[31:2] % MEM_WORDS][8*b +: 8] <= data_wdata[8*b +: 8];
          end else begin
            data_rdata_q <= mem[data_addr[31:2] % MEM_WORDS];
          end
        end
      end
    end
  end
  assign data_rvalid = data_rvalid_q;
  assign data_rdata  = data_rdata_q;


  // ---- XIF activity probes (proof the coprocessor is doing the work) -----
  int n_offload = 0, n_reject = 0, n_kill = 0, n_xresult = 0, n_stallcyc = 0;
  always @(posedge clk) if (rst_n) begin
    if (xif_issue_valid && xif_issue_ready)
      begin if (xif_issue_accept) n_offload++; else n_reject++; end
    if (xif_commit_valid && xif_commit_kill) n_kill++;
    if (xif_result_valid && xif_result_ready) n_xresult++;
    if (xif_issue_valid && !xif_issue_ready) n_stallcyc++;
  end

  // ---- run ---------------------------------------------------------------
  initial begin
    repeat (10) @(posedge clk);
    rst_n = 1;
    fork
      begin
        wait (done);
        repeat (20) @(posedge clk);
      end
      begin
        // +max_cycles=N raises the limit (the runners pass CVXIF_MAX_CYCLES); the
        // characterisation image runs 375 kernels and does not fit the default.
        int max_cycles = 200000;
        void'($value$plusargs("max_cycles=%d", max_cycles));
        repeat (max_cycles) @(posedge clk);
        $display("ERROR timeout: program did not signal completion");
        errors++;
      end
    join_any
    disable fork;

    // With RESULT_IN_MEM the program wrote its results to distinct addresses;
    // check the array now that it has finished.
    if (RESULT_IN_MEM) begin
      for (int i = 0; i < N_GOLDEN; i++) begin
        if (mem[(RESULT_BASE >> 2) + i] !== GOLDEN[i]) begin
          errors++;
          $display("ERROR result #%0d = %08x, expected %08x",
                 i, mem[(RESULT_BASE >> 2) + i], GOLDEN[i]);
        end else begin
          n_results++;
        end
      end
    end
    $display("results=%0d/%0d errors=%0d", n_results, N_GOLDEN, errors);
    $display("XIF: offloaded=%0d rejected=%0d killed=%0d results=%0d issue_stall_cycles=%0d",
             n_offload, n_reject, n_kill, n_xresult, n_stallcyc);
    if (n_offload == 0) begin errors++; $display("ERROR no instruction was ever offloaded!"); end
    if (n_kill == 0)    $display("NOTE commit_kill path never exercised");
    if (n_reject == 0)  begin errors++; $display("ERROR reject path never exercised!"); end
    if (errors != 0)          $fatal(1, "FAILED: %0d error(s)", errors);
    if (n_results != N_GOLDEN)
      $fatal(1, "FAILED: got %0d results, expected %0d", n_results, N_GOLDEN);
    $display("PASS");
    $finish;
  end

endmodule
