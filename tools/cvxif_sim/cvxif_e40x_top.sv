// CV32E40X + CV-X-IF coprocessor top (simulation and synthesis).
//
// Builds against pristine upstream openhwgroup/cv32e40x (deps/cv32e40x), not
// the SCAIE-V fork: the ISAX reaches the core only through the standard
// cv32e40x_if_xif eXtension interface, and the core has no SCAIE-V hooks at
// all. The only core change is core_patches/cv32e40x_xif_sticky_issue_resp.patch,
// which resolves upstream's own `TODO:XIF` in the ID stage.
module top
  import cv32e40x_pkg::*;
#(
  parameter int unsigned X_ID_WIDTH  = 4,
  parameter int unsigned X_NUM_RS    = 2,
  parameter int unsigned X_RFR_WIDTH = 32,
  parameter int unsigned X_RFW_WIDTH = 32
)
// Port list of SCAIE-V's maketop top (cv32e40x_top_template.sv), so its
// cv32e40x_tb_wrapper.v drives this design as well.
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

  // ---- the eXtension interface -------------------------------------------
  cv32e40x_if_xif #(
    .X_NUM_RS    (X_NUM_RS),
    .X_ID_WIDTH  (X_ID_WIDTH),
    .X_MEM_WIDTH (32),
    .X_RFR_WIDTH (X_RFR_WIDTH),
    .X_RFW_WIDTH (X_RFW_WIDTH),
    .X_MISA      ('0),
    .X_ECS_XS    ('0)
  ) xif ();

  cv32e40x_core #(
    .X_EXT           (1'b1),
    .X_NUM_RS        (X_NUM_RS),
    .X_ID_WIDTH      (X_ID_WIDTH),
    .X_MEM_WIDTH     (32),
    .X_RFR_WIDTH     (X_RFR_WIDTH),
    .X_RFW_WIDTH     (X_RFW_WIDTH),
    .NUM_MHPMCOUNTERS(0)
  ) core_i (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .scan_cg_en_i        (scan_cg_en_i),

    .boot_addr_i         (boot_addr_i),
    .dm_exception_addr_i (dm_exception_addr_i),
    .dm_halt_addr_i      (dm_halt_addr_i),
    .mhartid_i           (mhartid_i),
    .mimpid_patch_i      (mimpid_patch_i),
    .mtvec_addr_i        (mtvec_addr_i),

    .instr_req_o         (instr_req_o),
    .instr_gnt_i         (instr_gnt_i),
    .instr_rvalid_i      (instr_rvalid_i),
    .instr_addr_o        (instr_addr_o),
    .instr_memtype_o     (instr_memtype_o),
    .instr_prot_o        (instr_prot_o),
    .instr_dbg_o         (instr_dbg_o),
    .instr_rdata_i       (instr_rdata_i),
    .instr_err_i         (instr_err_i),

    .data_req_o          (data_req_o),
    .data_gnt_i          (data_gnt_i),
    .data_rvalid_i       (data_rvalid_i),
    .data_addr_o         (data_addr_o),
    .data_be_o           (data_be_o),
    .data_we_o           (data_we_o),
    .data_wdata_o        (data_wdata_o),
    .data_memtype_o      (data_memtype_o),
    .data_prot_o         (data_prot_o),
    .data_dbg_o          (data_dbg_o),
    .data_atop_o         (data_atop_o),
    .data_rdata_i        (data_rdata_i),
    .data_err_i          (data_err_i),
    .data_exokay_i       (data_exokay_i),

    .mcycle_o            (mcycle_o),
    .time_i              (64'h0),

    .xif_compressed_if   (xif),
    .xif_issue_if        (xif),
    .xif_commit_if       (xif),
    .xif_mem_if          (xif),
    .xif_mem_result_if   (xif),
    .xif_result_if       (xif),

    .irq_i               (irq_i),
    .wu_wfe_i            (wu_wfe_i),

    .clic_irq_i          (clic_irq_i),
    .clic_irq_id_i       (clic_irq_id_i),
    .clic_irq_level_i    (clic_irq_level_i),
    .clic_irq_priv_i     (clic_irq_priv_i),
    .clic_irq_shv_i      (clic_irq_shv_i),

    .fencei_flush_req_o  (fencei_flush_req_o),
    .fencei_flush_ack_i  (fencei_flush_ack_i),

    .debug_req_i         (debug_req_i),
    .debug_havereset_o   (debug_havereset_o),
    .debug_running_o     (debug_running_o),
    .debug_halted_o      (debug_halted_o),
    .debug_pc_valid_o    (),
    .debug_pc_o          (),

    .fetch_enable_i      (fetch_enable_i),
    .core_sleep_o        (core_sleep_o)
  );

  // ---- the generated CV-X-IF coprocessor ----------------------------------
  // CVXIF_COPROC names its module (cvxif.run_cvxif puts the define into
  // filelist.f). Without it -- the NO_ISAX entry point -- nothing sits on the
  // interface: it is tied off to "answer immediately, accept nothing", so every
  // custom encoding traps as illegal. A CPU-only baseline.
  `ifdef CVXIF_COPROC
  `CVXIF_COPROC #(
    .X_ID_WIDTH  (X_ID_WIDTH),
    .X_NUM_RS    (X_NUM_RS),
    .X_RFR_WIDTH (X_RFR_WIDTH),
    .X_RFW_WIDTH (X_RFW_WIDTH)
  ) coproc_i (
    .clk_i             (clk_i),
    .rst_ni            (rst_ni),
    .xif_compressed_if (xif),
    .xif_issue_if      (xif),
    .xif_commit_if     (xif),
    .xif_mem_if        (xif),
    .xif_mem_result_if (xif),
    .xif_result_if     (xif)
  );
  `else
  assign xif.compressed_ready = 1'b1;
  assign xif.compressed_resp  = '0;
  assign xif.issue_ready      = 1'b1;
  assign xif.issue_resp       = '0;
  assign xif.mem_valid        = 1'b0;
  assign xif.mem_req          = '0;
  assign xif.result_valid     = 1'b0;
  assign xif.result           = '0;
  `endif

endmodule
