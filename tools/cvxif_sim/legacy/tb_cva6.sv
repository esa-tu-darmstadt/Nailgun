// Testbench: upstream CVA6 + CV-X-IF coprocessor running a real RISC-V program.
//
// CVA6 talks AXI4, not OBI, so this is a behavioural AXI4 slave (64-bit data,
// INCR bursts) backed by a doubleword array, plus an MMIO tap in the uncached
// region: the program stores each computed result to RESULT_ADDR and finally a
// non-zero word to DONE_ADDR. The captured stream is compared against the
// golden values in golden.svh, generated alongside the program.
//
// Memory map (cv32a60x: cached region is 0x8000_0000 + 0x4000_0000):
//   0x8000_0000  RAM, program image loaded here     -- cached
//   0x1000_0000  MMIO result port / done / trace    -- uncached
`timescale 1ns/1ps

module tb_cva6;

  localparam int unsigned MEM_DWORDS  = 1 << 16;        // 512 KiB
  localparam logic [63:0] MEM_BASE    = 64'h8000_0000;
  localparam logic [63:0] MMIO_BASE   = 64'h1000_0000;
  localparam logic [63:0] RESULT_ADDR = MMIO_BASE + 0;
  localparam logic [63:0] DONE_ADDR   = MMIO_BASE + 4;
  localparam logic [63:0] TRACE_ADDR  = MMIO_BASE + 8;

  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  ariane_axi::req_t  noc_req;
  ariane_axi::resp_t noc_resp;
  logic xif_accept, xif_result;

  cvxif_cva6_top dut (
    .clk_i      (clk),
    .rst_ni     (rst_n),
    .boot_addr_i(MEM_BASE[31:0]),
    .hart_id_i  (32'h0),
    .irq_i      (2'b00),
    .ipi_i      (1'b0),
    .time_irq_i (1'b0),
    .debug_req_i(1'b0),
    .noc_req_o  (noc_req),
    .noc_resp_i (noc_resp),
    .xif_issue_accept_o(xif_accept),
    .xif_result_valid_o(xif_result)
  );

  // ---- memory ------------------------------------------------------------
  logic [63:0] mem [0:MEM_DWORDS-1];

  initial begin
    for (int i = 0; i < MEM_DWORDS; i++) mem[i] = 64'h0;
    $readmemh("mem.hex", mem);
  end

  function automatic bit in_ram(input logic [63:0] a);
    return (a >= MEM_BASE) && (a < MEM_BASE + MEM_DWORDS * 8);
  endfunction
  function automatic int unsigned ram_idx(input logic [63:0] a);
    return int'((a - MEM_BASE) >> 3);
  endfunction

  int  n_results = 0;
  bit  done = 0;
  int  errors = 0;

  `include "golden.svh"

  // ---- AXI4 slave --------------------------------------------------------
  // Read and write channels run independently. Bursts are INCR only, which is
  // all CVA6 issues (cache line fills and single uncached accesses).
  typedef enum logic [1:0] {R_IDLE, R_BURST} rstate_e;
  typedef enum logic [1:0] {W_IDLE, W_DATA, W_RESP} wstate_e;

  rstate_e rstate = R_IDLE;
  wstate_e wstate = W_IDLE;

  logic [63:0] r_addr;
  logic [7:0]  r_len;
  logic [3:0]  r_id;
  logic [2:0]  r_size;

  logic [63:0] w_addr;
  logic [2:0]  w_size;
  logic [3:0]  w_id;

  // Combinational ready/valid, registered payload.
  assign noc_resp.ar_ready = (rstate == R_IDLE);
  assign noc_resp.aw_ready = (wstate == W_IDLE);
  assign noc_resp.w_ready  = (wstate == W_DATA);

  logic        r_valid_q, b_valid_q;
  logic [63:0] r_data_q;
  logic        r_last_q;
  logic [3:0]  r_id_q, b_id_q;

  assign noc_resp.r_valid = r_valid_q;
  assign noc_resp.r.data  = r_data_q;
  assign noc_resp.r.id    = r_id_q;
  assign noc_resp.r.last  = r_last_q;
  assign noc_resp.r.resp  = axi_pkg::RESP_OKAY;
  assign noc_resp.r.user  = '0;

  assign noc_resp.b_valid = b_valid_q;
  assign noc_resp.b.id    = b_id_q;
  assign noc_resp.b.resp  = axi_pkg::RESP_OKAY;
  assign noc_resp.b.user  = '0;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      rstate    <= R_IDLE;
      wstate    <= W_IDLE;
      r_valid_q <= 1'b0;
      b_valid_q <= 1'b0;
    end else begin
      // ---- read ----
      if (r_valid_q && noc_req.r_ready) begin
        r_valid_q <= 1'b0;
        if (r_last_q) rstate <= R_IDLE;
      end
      case (rstate)
        R_IDLE: if (noc_req.ar_valid) begin
          r_addr  <= noc_req.ar.addr;
          r_len   <= noc_req.ar.len;
          r_size  <= noc_req.ar.size;
          r_id    <= noc_req.ar.id;
          rstate  <= R_BURST;
        end
        R_BURST: if (!r_valid_q || noc_req.r_ready) begin
          if (!(r_valid_q && r_last_q)) begin
            r_data_q  <= in_ram(r_addr) ? mem[ram_idx(r_addr)] : 64'h0;
            r_id_q    <= r_id;
            r_last_q  <= (r_len == 8'h0);
            r_valid_q <= 1'b1;
            r_addr    <= r_addr + (64'h1 << r_size);
            r_len     <= r_len - 8'h1;
          end
        end
        default: ;
      endcase

      // ---- write ----
      if (b_valid_q && noc_req.b_ready) begin
        b_valid_q <= 1'b0;
        wstate    <= W_IDLE;
      end
      case (wstate)
        W_IDLE: if (noc_req.aw_valid) begin
          w_addr <= noc_req.aw.addr;
          w_size <= noc_req.aw.size;
          w_id   <= noc_req.aw.id;
          wstate <= W_DATA;
        end
        W_DATA: if (noc_req.w_valid) begin
          if (in_ram(w_addr)) begin
`ifdef CVXIF_DEBUG
            $display("[%0t] AXI W ram %012x strb %02x data %016x",
                     $time, w_addr, noc_req.w.strb, noc_req.w.data);
`endif
            for (int b = 0; b < 8; b++)
              if (noc_req.w.strb[b])
                mem[ram_idx(w_addr)][8*b +: 8] <= noc_req.w.data[8*b +: 8];
          end else begin
`ifdef CVXIF_DEBUG
            $display("[%0t] AXI W mmio %012x strb %02x data %016x",
                     $time, w_addr, noc_req.w.strb, noc_req.w.data);
`endif
            check_mmio(w_addr, noc_req.w.data, noc_req.w.strb);
          end
          w_addr <= w_addr + (64'h1 << w_size);
          if (noc_req.w.last) begin
            b_id_q    <= w_id;
            b_valid_q <= 1'b1;
            wstate    <= W_RESP;
          end
        end
        default: ;
      endcase
    end
  end

  // A 32-bit store lands in one half of the 64-bit beat; the byte strobes say
  // which, and that is what distinguishes the result port from `done`.
  task automatic check_mmio(input logic [63:0] a, input logic [63:0] d,
                            input logic [7:0] strb);
    logic [63:0] base = a & ~64'h7;
    logic [31:0] lo   = d[31:0];
    logic [31:0] hi   = d[63:32];
    if (base == (RESULT_ADDR & ~64'h7)) begin
      if (strb[0]) begin                       // +0: a result
        if (n_results >= N_GOLDEN) begin
          errors++;
          $display("ERROR result #%0d %08x: more results than expected (%0d)",
                 n_results, lo, N_GOLDEN);
        end else if (lo !== GOLDEN[n_results]) begin
          errors++;
          $display("ERROR result #%0d = %08x, expected %08x",
                 n_results, lo, GOLDEN[n_results]);
        end
        n_results++;
      end
      if (strb[4]) done <= 1'b1;               // +4: completion
    end else if (base == (TRACE_ADDR & ~64'h7) && strb[0]) begin
      $display("[trace] %08x", lo);
    end
  endtask

  // ---- XIF activity probes (proof the coprocessor is doing the work) -----
  int n_offload = 0, n_reject = 0, n_kill = 0, n_xresult = 0, n_stallcyc = 0;
  always @(posedge clk) if (rst_n) begin
    if (dut.cvxif_req.issue_valid && dut.cvxif_resp.issue_ready)
      begin if (dut.cvxif_resp.issue_resp.accept) n_offload++; else n_reject++; end
    if (dut.cvxif_req.commit_valid && dut.cvxif_req.commit.commit_kill) n_kill++;
    if (dut.cvxif_resp.result_valid && dut.cvxif_req.result_ready) n_xresult++;
    if (dut.cvxif_req.issue_valid && !dut.cvxif_resp.issue_ready) n_stallcyc++;
  end

  // ---- run ---------------------------------------------------------------
  logic [63:0] a;
  logic [31:0] got;

  initial begin
    repeat (10) @(posedge clk);
    rst_n = 1;
    fork
      begin
        wait (done);
        repeat (20) @(posedge clk);
      end
      begin
        repeat (500000) @(posedge clk);
        $display("ERROR timeout: program did not signal completion");
        errors++;
      end
    join_any
    disable fork;

    // With RESULT_IN_MEM the program wrote its results to an array in RAM
    // instead of streaming them through the MMIO port; check it now that it has
    // finished. RESULT_BASE must lie in RAM -- run_cva6.sh puts it there.
    if (RESULT_IN_MEM) begin
      if (!in_ram(RESULT_BASE)) begin
        errors++;
        $display("ERROR RESULT_BASE %08x is outside RAM", RESULT_BASE);
      end else begin
        // NOTE: declared here, assigned in the loop. A declaration *with an
        // initialiser* inside the loop body would be static-initialised once,
        // before time 0, with `i` still undefined -- every result would read
        // back as 0.
        for (int i = 0; i < N_GOLDEN; i++) begin
          a   = RESULT_BASE + 4 * i;
          got = a[2] ? mem[ram_idx(a)][63:32] : mem[ram_idx(a)][31:0];
          if (got !== GOLDEN[i]) begin
            errors++;
            $display("ERROR result #%0d = %08x, expected %08x", i, got, GOLDEN[i]);
          end else begin
            n_results++;
          end
        end
      end
    end

    $display("results=%0d/%0d errors=%0d", n_results, N_GOLDEN, errors);
    // CVA6 hardwires commit.commit_kill to 0, so unlike CV32E40X there is no
    // kill path to exercise here -- n_kill is reported, not required.
    $display("XIF: offloaded=%0d rejected=%0d killed=%0d results=%0d issue_stall_cycles=%0d",
             n_offload, n_reject, n_kill, n_xresult, n_stallcyc);
    if (n_offload == 0) begin errors++; $display("ERROR no instruction was ever offloaded!"); end
    if (n_reject == 0)  begin errors++; $display("ERROR reject path never exercised!"); end
    if (errors != 0)          $fatal(1, "FAILED: %0d error(s)", errors);
    if (n_results != N_GOLDEN)
      $fatal(1, "FAILED: got %0d results, expected %0d", n_results, N_GOLDEN);
    $display("PASS");
    $finish;
  end

endmodule
