// CV32E40PX + CV-X-IF coprocessor top for simulation.
//
// Builds against pristine upstream esl-epfl/cv32e40px (deps/cv32e40px). Note
// which core this is: **not** CV32E40P (no X-interface at all) and **not**
// CV32E40X (a different core, with the interface as a SystemVerilog interface).
// CV32E40PX is the CV32E40P derivative that adds CV-X-IF, and it packages the
// same interface revision as packed structs in `cv32e40px_core_v_xif_pkg`.
//
module top
  import cv32e40px_core_v_xif_pkg::*;
// Port list of SCAIE-V's maketop top (cv32e40x_top_template.sv, shared by its
// CV32E40P), so its cv32e40x_tb_wrapper.v drives this design as well. Pins
// CV32E40PX has no counterpart for are ignored / tied off below.
(
  input                 clk,
  input                 rst,

  //Ports copied from cv32e40x repository (Copyright 2018 ETH Zurich and University of Bologna, Solderpad Hardware License Version 0.51)

  input  logic        scan_cg_en_i,                     // Enable all clock gates for testing

  // Core ID, Cluster ID, debug mode halt address and boot address are considered more or less static
  input  logic [31:0] boot_addr_i,
  input  logic [31:0] mtvec_addr_i,
  input  logic [31:0] dm_halt_addr_i,
  input  logic [31:0] mhartid_i,
  input  logic  [3:0] mimpid_patch_i,
  input  logic [31:0] dm_exception_addr_i,

  // Instruction memory interface
  output logic        instr_req_o,
  input  logic        instr_gnt_i,
  input  logic        instr_rvalid_i,
  output logic [31:0] instr_addr_o,
  output logic [1:0]  instr_memtype_o,
  output logic [2:0]  instr_prot_o,
  output logic        instr_dbg_o,
  input  logic [31:0] instr_rdata_i,
  input  logic        instr_err_i,

  // Data memory interface
  output logic        data_req_o,
  input  logic        data_gnt_i,
  input  logic        data_rvalid_i,
  output logic        data_we_o,
  output logic [3:0]  data_be_o,
  output logic [31:0] data_addr_o,
  output logic [1:0]  data_memtype_o,
  output logic [2:0]  data_prot_o,
  output logic        data_dbg_o,
  output logic [31:0] data_wdata_o,
  input  logic [31:0] data_rdata_i,
  input  logic        data_err_i,
  output logic [5:0]  data_atop_o,
  input  logic        data_exokay_i,

  // Cycle Count
  output logic [63:0] mcycle_o,

  // Interrupt inputs
  input  logic [31:0] irq_i,                    // CLINT interrupts + CLINT extension interrupts

  // WFE input
  input  logic        wu_wfe_i,

  // CLIC Interface
  input  logic                       clic_irq_i,
  input  logic [5-1:0] clic_irq_id_i,
  input  logic [ 7:0]                clic_irq_level_i,
  input  logic [ 1:0]                clic_irq_priv_i,
  input  logic                       clic_irq_shv_i,


  // Fencei flush handshake
  output logic        fencei_flush_req_o,
  input logic         fencei_flush_ack_i,
  // Debug Interface
  input  logic        debug_req_i,
  output logic        debug_havereset_o,
  output logic        debug_running_o,
  output logic        debug_halted_o,

  // CPU Control Signals
  input  logic        fetch_enable_i,
  output logic        core_sleep_o

);

  wire clk_i  = clk;
  wire rst_ni = ~rst;

  // No counterpart on CV32E40PX: OBI side-band, mcycle, fence.i handshake.
  assign instr_memtype_o    = '0;
  assign instr_prot_o       = '0;
  assign instr_dbg_o        = 1'b0;
  assign data_memtype_o     = '0;
  assign data_prot_o        = '0;
  assign data_dbg_o         = 1'b0;
  assign data_atop_o        = '0;
  assign mcycle_o           = '0;
  assign fencei_flush_req_o = 1'b0;

  // ---- the eXtension interface (structs, not an SV interface) -------------
  logic               x_compressed_valid, x_compressed_ready;
  x_compressed_req_t  x_compressed_req;
  x_compressed_resp_t x_compressed_resp;

  logic               x_issue_valid, x_issue_ready;
  x_issue_req_t       x_issue_req;
  x_issue_resp_t      x_issue_resp;

  logic               x_commit_valid;
  x_commit_t          x_commit;

  logic               x_mem_valid, x_mem_ready;
  x_mem_req_t         x_mem_req;
  x_mem_resp_t        x_mem_resp;
  logic               x_mem_result_valid;
  x_mem_result_t      x_mem_result;

  logic               x_result_valid, x_result_ready;
  x_result_t          x_result;


  cv32e40px_top #(
    .COREV_X_IF      (1),
    .COREV_PULP      (0),
    .COREV_CLUSTER   (0),
    .FPU             (0),
    .ZFINX           (0),
    .NUM_MHPMCOUNTERS(1)
  ) core_i (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .pulp_clock_en_i     (1'b0),
    .scan_cg_en_i        (scan_cg_en_i),

    .boot_addr_i         (boot_addr_i),
    .mtvec_addr_i        (mtvec_addr_i),
    .dm_halt_addr_i      (dm_halt_addr_i),
    .hart_id_i           (mhartid_i),
    .dm_exception_addr_i (dm_exception_addr_i),

    .instr_req_o         (instr_req_o),
    .instr_gnt_i         (instr_gnt_i),
    .instr_rvalid_i      (instr_rvalid_i),
    .instr_addr_o        (instr_addr_o),
    .instr_rdata_i       (instr_rdata_i),

    .data_req_o          (data_req_o),
    .data_gnt_i          (data_gnt_i),
    .data_rvalid_i       (data_rvalid_i),
    .data_we_o           (data_we_o),
    .data_be_o           (data_be_o),
    .data_addr_o         (data_addr_o),
    .data_wdata_o        (data_wdata_o),
    .data_rdata_i        (data_rdata_i),

    .x_compressed_valid_o(x_compressed_valid),
    .x_compressed_ready_i(x_compressed_ready),
    .x_compressed_req_o  (x_compressed_req),
    .x_compressed_resp_i (x_compressed_resp),

    .x_issue_valid_o     (x_issue_valid),
    .x_issue_ready_i     (x_issue_ready),
    .x_issue_req_o       (x_issue_req),
    .x_issue_resp_i      (x_issue_resp),

    .x_commit_valid_o    (x_commit_valid),
    .x_commit_o          (x_commit),

    .x_mem_valid_i       (x_mem_valid),
    .x_mem_ready_o       (x_mem_ready),
    .x_mem_req_i         (x_mem_req),
    .x_mem_resp_o        (x_mem_resp),

    .x_mem_result_valid_o(x_mem_result_valid),
    .x_mem_result_o      (x_mem_result),

    .x_result_valid_i    (x_result_valid),
    .x_result_ready_o    (x_result_ready),
    .x_result_i          (x_result),

    .irq_i               (irq_i),
    .irq_ack_o           (),
    .irq_id_o            (),

    .debug_req_i         (debug_req_i),
    .debug_havereset_o   (debug_havereset_o),
    .debug_running_o     (debug_running_o),
    .debug_halted_o      (debug_halted_o),

    .fetch_enable_i      (fetch_enable_i),
    .core_sleep_o        (core_sleep_o)
  );

  // ---- the generated CV-X-IF coprocessor ----------------------------------
  // CVXIF_COPROC names its module (cvxif.run_cvxif puts the define into
  // filelist.f). Without it -- the NO_ISAX entry point -- nothing sits on the
  // interface: it is tied off to "answer immediately, accept nothing", so every
  // custom encoding traps as illegal. A CPU-only baseline.
  `ifdef CVXIF_COPROC
  `CVXIF_COPROC coproc_i (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),

    .x_compressed_valid_i (x_compressed_valid),
    .x_compressed_ready_o (x_compressed_ready),
    .x_compressed_req_i   (x_compressed_req),
    .x_compressed_resp_o  (x_compressed_resp),

    .x_issue_valid_i      (x_issue_valid),
    .x_issue_ready_o      (x_issue_ready),
    .x_issue_req_i        (x_issue_req),
    .x_issue_resp_o       (x_issue_resp),

    .x_commit_valid_i     (x_commit_valid),
    .x_commit_i           (x_commit),

    .x_mem_valid_o        (x_mem_valid),
    .x_mem_ready_i        (x_mem_ready),
    .x_mem_req_o          (x_mem_req),
    .x_mem_resp_i         (x_mem_resp),

    .x_mem_result_valid_i (x_mem_result_valid),
    .x_mem_result_i       (x_mem_result),

    .x_result_valid_o     (x_result_valid),
    .x_result_ready_i     (x_result_ready),
    .x_result_o           (x_result)
  );
  `else
  assign x_compressed_ready = 1'b1;
  assign x_compressed_resp  = '0;
  assign x_issue_ready      = 1'b1;
  assign x_issue_resp       = '0;
  assign x_mem_valid        = 1'b0;
  assign x_mem_req          = '0;
  assign x_result_valid     = 1'b0;
  assign x_result           = '0;
  `endif

endmodule
