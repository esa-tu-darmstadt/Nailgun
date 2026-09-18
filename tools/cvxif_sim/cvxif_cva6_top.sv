// CVA6 + CV-X-IF coprocessor top for simulation.
//
// Builds against pristine upstream openhwgroup/cva6 (deps/cva6_upstream), not
// the SCAIE-V fork: the ISAX reaches the core only through the standard
// CV-X-IF `cvxif_req_o` / `cvxif_resp_i` port pair, and the core carries no
// SCAIE-V hooks and no patches at all.
//
// This is upstream `corev_apu/src/ariane.sv` with one thing changed: instead of
// the `gen_cvxif` block that instantiates `cvxif_example_coprocessor`, the
// generated `cvxif_coproc_cva6_<name>` goes on the interface. Everything else --
// the type construction from CVA6Cfg, the cva6 instantiation, the AXI ports --
// is upstream's own wiring.
//
// The target config is cv32a60x: rv32, no MMU, CvxifEn = 1 already upstream, so
// no config edit is needed either.

`include "rvfi_types.svh"
`include "cvxif_types.svh"

module cvxif_cva6_top
  import ariane_pkg::*;
#(
    parameter config_pkg::cva6_cfg_t CVA6Cfg = build_config_pkg::build_config(
        cva6_config_pkg::cva6_cfg
    ),
    // RVFI probe types -- built exactly as ariane_testharness.sv does. The
    // probes themselves are left unconnected; cva6 needs the types regardless.
    localparam type rvfi_probes_instr_t = `RVFI_PROBES_INSTR_T(CVA6Cfg),
    localparam type rvfi_probes_csr_t   = `RVFI_PROBES_CSR_T(CVA6Cfg),
    localparam type rvfi_probes_t = struct packed {
      rvfi_probes_csr_t   csr;
      rvfi_probes_instr_t instr;
    },
    // CV-X-IF v1.0 types, from the same macros the core uses.
    localparam type readregflags_t      = `READREGFLAGS_T(CVA6Cfg),
    localparam type writeregflags_t     = `WRITEREGFLAGS_T(CVA6Cfg),
    localparam type id_t                = `ID_T(CVA6Cfg),
    localparam type hartid_t            = `HARTID_T(CVA6Cfg),
    localparam type x_compressed_req_t  = `X_COMPRESSED_REQ_T(CVA6Cfg, hartid_t),
    localparam type x_compressed_resp_t = `X_COMPRESSED_RESP_T(CVA6Cfg),
    localparam type x_issue_req_t       = `X_ISSUE_REQ_T(CVA6Cfg, hartid_t, id_t),
    localparam type x_issue_resp_t      = `X_ISSUE_RESP_T(CVA6Cfg, writeregflags_t, readregflags_t),
    localparam type x_register_t        = `X_REGISTER_T(CVA6Cfg, hartid_t, id_t, readregflags_t),
    localparam type x_commit_t          = `X_COMMIT_T(CVA6Cfg, hartid_t, id_t),
    localparam type x_result_t          = `X_RESULT_T(CVA6Cfg, hartid_t, id_t, writeregflags_t),
    localparam type cvxif_req_t         = `CVXIF_REQ_T(CVA6Cfg, x_compressed_req_t, x_issue_req_t, x_register_t, x_commit_t),
    localparam type cvxif_resp_t        = `CVXIF_RESP_T(CVA6Cfg, x_compressed_resp_t, x_issue_resp_t, x_result_t),
    // AXI
    parameter type axi_ar_chan_t = ariane_axi::ar_chan_t,
    parameter type axi_aw_chan_t = ariane_axi::aw_chan_t,
    parameter type axi_w_chan_t  = ariane_axi::w_chan_t,
    parameter type noc_req_t     = ariane_axi::req_t,
    parameter type noc_resp_t    = ariane_axi::resp_t
) (
    input  logic                     clk_i,
    input  logic                     rst_ni,
    input  logic [CVA6Cfg.VLEN-1:0]  boot_addr_i,
    input  logic [CVA6Cfg.XLEN-1:0]  hart_id_i,
    input  logic [1:0]               irq_i,
    input  logic                     ipi_i,
    input  logic                     time_irq_i,
    input  logic                     debug_req_i,
    // memory side
    output noc_req_t                 noc_req_o,
    input  noc_resp_t                noc_resp_i,
    // observation: did anything actually get offloaded?
    output logic                     xif_issue_accept_o,
    output logic                     xif_result_valid_o
);

  cvxif_req_t   cvxif_req;
  cvxif_resp_t  cvxif_resp;
  rvfi_probes_t rvfi_probes;

  assign xif_issue_accept_o = cvxif_req.issue_valid & cvxif_resp.issue_ready
                            & cvxif_resp.issue_resp.accept;
  assign xif_result_valid_o = cvxif_resp.result_valid;

  cva6 #(
      .CVA6Cfg             (CVA6Cfg),
      .rvfi_probes_instr_t (rvfi_probes_instr_t),
      .rvfi_probes_csr_t   (rvfi_probes_csr_t),
      .rvfi_probes_t       (rvfi_probes_t),
      .axi_ar_chan_t       (axi_ar_chan_t),
      .axi_aw_chan_t       (axi_aw_chan_t),
      .axi_w_chan_t        (axi_w_chan_t),
      .noc_req_t           (noc_req_t),
      .noc_resp_t          (noc_resp_t),
      .readregflags_t      (readregflags_t),
      .writeregflags_t     (writeregflags_t),
      .id_t                (id_t),
      .hartid_t            (hartid_t),
      .x_compressed_req_t  (x_compressed_req_t),
      .x_compressed_resp_t (x_compressed_resp_t),
      .x_issue_req_t       (x_issue_req_t),
      .x_issue_resp_t      (x_issue_resp_t),
      .x_register_t        (x_register_t),
      .x_commit_t          (x_commit_t),
      .x_result_t          (x_result_t),
      .cvxif_req_t         (cvxif_req_t),
      .cvxif_resp_t        (cvxif_resp_t)
  ) i_cva6 (
      .clk_i        (clk_i),
      .rst_ni       (rst_ni),
      .boot_addr_i  (boot_addr_i),
      .hart_id_i    (hart_id_i),
      .irq_i        (irq_i),
      .ipi_i        (ipi_i),
      .time_irq_i   (time_irq_i),
      .debug_req_i  (debug_req_i),
      .rvfi_probes_o(rvfi_probes),
      .cvxif_req_o  (cvxif_req),
      .cvxif_resp_i (cvxif_resp),
      .noc_req_o    (noc_req_o),
      .noc_resp_i   (noc_resp_i)
  );

  // ---- the generated CV-X-IF coprocessor ----------------------------------
  `ifndef CVXIF_COPROC
    `define CVXIF_COPROC cvxif_coproc_cva6_sparkle
  `endif
  `CVXIF_COPROC #(
      .X_ID_WIDTH  (CVA6Cfg.X_ID_WIDTH),
      .X_NUM_RS    (CVA6Cfg.X_NUM_RS),
      .X_RFR_WIDTH (CVA6Cfg.X_RFR_WIDTH),
      .X_RFW_WIDTH (CVA6Cfg.X_RFW_WIDTH),
      .cvxif_req_t (cvxif_req_t),
      .cvxif_resp_t(cvxif_resp_t)
  ) i_coproc (
      .clk_i       (clk_i),
      .rst_ni      (rst_ni),
      .cvxif_req_i (cvxif_req),
      .cvxif_resp_o(cvxif_resp)
  );

endmodule
