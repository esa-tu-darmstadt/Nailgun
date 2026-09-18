// cocotb testbench wrapper for the CV-X-IF CVA6 top (cvxif_cva6_top): pristine
// upstream CVA6 (cv32a60x) + the generated coprocessor on the CV-X-IF v1.0
// interface. Same `testbench` AXI4 port list as SCAIE-V's CVA6_tb_wrapper.v
// (m_axi_ctrl, minus the RVFI taps), so sim/ drives it with the bus model and
// memory map of the SCAIE-V CVA6. The noc_req_t/noc_resp_t structs are
// flattened as SCAIE-V's cva6_ariane_wrapper does.
module testbench(
    input wire clk,
    input wire rst,
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

    ariane_axi::req_t  noc_req;
    ariane_axi::resp_t noc_resp;

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

    cvxif_cva6_top top_inst (
        .clk_i      (clk),
        .rst_ni     (~rst),
        // sim/linker_scripts/CVA6_link.ld: imem at 0x80000000.
        .boot_addr_i(32'h8000_0000),
        .hart_id_i  ('0),
        .irq_i      (2'b00),
        .ipi_i      (1'b0),
        .time_irq_i (1'b0),
        .debug_req_i(1'b0),
        .noc_req_o  (noc_req),
        .noc_resp_i (noc_resp)
    );

endmodule
