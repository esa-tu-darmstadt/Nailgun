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

module cva6_ariane_wrapper
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
    // memory side: flat AXI4, the port list of SCAIE-V's cva6_ariane_wrapper,
    // so its CVA6_tb_wrapper.v drives this design as well.
    //AXI Control Bus
    output wire         m_axi_ctrl_AWVALID,
    input  wire         m_axi_ctrl_AWREADY, //
    output wire [5:0]   m_axi_ctrl_AWID,
    output wire [63:0]  m_axi_ctrl_AWADDR,
    output wire [2:0]   m_axi_ctrl_AWSIZE,
    output wire [7:0]   m_axi_ctrl_AWLEN,
    output wire [1:0]   m_axi_ctrl_AWBURST,
    output wire         m_axi_ctrl_WVALID,
    input  wire         m_axi_ctrl_WREADY, //
    output wire [63:0]  m_axi_ctrl_WDATA,
    output wire [7:0]   m_axi_ctrl_WSTRB,
    output wire         m_axi_ctrl_WLAST,
    input  wire         m_axi_ctrl_BVALID, //
    output wire         m_axi_ctrl_BREADY,
    input  wire [5:0]   m_axi_ctrl_BID, //
    input  wire [1:0]   m_axi_ctrl_BRESP, //

    output wire         m_axi_ctrl_ARVALID,
    input  wire         m_axi_ctrl_ARREADY,//
    output wire [5:0]   m_axi_ctrl_ARID,
    output wire [63:0]  m_axi_ctrl_ARADDR,
    output wire [2:0]   m_axi_ctrl_ARSIZE,
    output wire [7:0]   m_axi_ctrl_ARLEN,
    output wire [1:0]   m_axi_ctrl_ARBURST,

    input  wire         m_axi_ctrl_RVALID, //
    output wire         m_axi_ctrl_RREADY,
    input  wire [5:0]   m_axi_ctrl_RID, //
    input  wire [63:0]  m_axi_ctrl_RDATA, //
    input  wire [1:0]   m_axi_ctrl_RRESP, //
    input  wire         m_axi_ctrl_RLAST //
);

  noc_req_t  noc_req;
  noc_resp_t noc_resp;

  assign noc_resp.aw_ready = m_axi_ctrl_AWREADY;
  assign noc_resp.ar_ready = m_axi_ctrl_ARREADY;
  assign noc_resp.w_ready  = m_axi_ctrl_WREADY;
  assign noc_resp.b_valid  = m_axi_ctrl_BVALID;
  assign noc_resp.b.id     = m_axi_ctrl_BID[3:0];
  assign noc_resp.b.resp   = m_axi_ctrl_BRESP;
  assign noc_resp.b.user   = '0;
  assign noc_resp.r_valid  = m_axi_ctrl_RVALID;
  assign noc_resp.r.id     = m_axi_ctrl_RID[3:0];
  assign noc_resp.r.data   = m_axi_ctrl_RDATA;
  assign noc_resp.r.resp   = m_axi_ctrl_RRESP;
  assign noc_resp.r.last   = m_axi_ctrl_RLAST;
  assign noc_resp.r.user   = '0;

  assign m_axi_ctrl_AWVALID = noc_req.aw_valid;
  assign m_axi_ctrl_AWID    = {2'b00, noc_req.aw.id};
  assign m_axi_ctrl_AWADDR  = noc_req.aw.addr;
  assign m_axi_ctrl_AWSIZE  = noc_req.aw.size;
  assign m_axi_ctrl_AWLEN   = noc_req.aw.len;
  assign m_axi_ctrl_AWBURST = noc_req.aw.burst;
  assign m_axi_ctrl_WVALID  = noc_req.w_valid;
  assign m_axi_ctrl_WDATA   = noc_req.w.data;
  assign m_axi_ctrl_WSTRB   = noc_req.w.strb;
  assign m_axi_ctrl_WLAST   = noc_req.w.last;
  assign m_axi_ctrl_BREADY  = noc_req.b_ready;
  assign m_axi_ctrl_ARVALID = noc_req.ar_valid;
  assign m_axi_ctrl_ARID    = {2'b00, noc_req.ar.id};
  assign m_axi_ctrl_ARADDR  = noc_req.ar.addr;
  assign m_axi_ctrl_ARSIZE  = noc_req.ar.size;
  assign m_axi_ctrl_ARLEN   = noc_req.ar.len;
  assign m_axi_ctrl_ARBURST = noc_req.ar.burst;
  assign m_axi_ctrl_RREADY  = noc_req.r_ready;


  cvxif_req_t   cvxif_req;
  cvxif_resp_t  cvxif_resp;
  rvfi_probes_t rvfi_probes;


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
      .noc_req_o    (noc_req),
      .noc_resp_i   (noc_resp)
  );

  // ---- the generated CV-X-IF coprocessor ----------------------------------
  // CVXIF_COPROC names its module (cvxif.run_cvxif puts the define into
  // filelist.f). Without it -- the NO_ISAX entry point -- nothing sits on the
  // interface: it is tied off to "answer immediately, accept nothing", so every
  // custom encoding traps as illegal. A CPU-only baseline.
  `ifdef CVXIF_COPROC
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
  `else
  always_comb begin
    cvxif_resp                  = '0;
    cvxif_resp.compressed_ready = 1'b1;
    cvxif_resp.issue_ready      = 1'b1;
    cvxif_resp.register_ready   = 1'b1;
  end
  `endif

endmodule
