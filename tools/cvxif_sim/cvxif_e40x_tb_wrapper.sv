// cocotb testbench wrapper for the CV-X-IF CV32E40X top (cvxif_e40x_top):
// pristine upstream core + the generated coprocessor on the eXtension
// interface. Same `testbench` port list as SCAIE-V's cv32e40x_tb_wrapper.v
// (two OBI->AXI4 adapters, m_axi_instr / m_axi_data), so sim/ drives it with
// the bus models and memory map of the SCAIE-V CV32E40X. irq_i is unused: the
// top ties the core's interrupts off.
module testbench(
	input clk,
	input rst,
	input [31:0] irq_i,

	//AXI Instruction Bus
	output        m_axi_instr_AWVALID,
	input         m_axi_instr_AWREADY,
	output [31:0] m_axi_instr_AWADDR,
	output [2:0]  m_axi_instr_AWSIZE,

	output        m_axi_instr_WVALID,
	input         m_axi_instr_WREADY,
	output [31:0] m_axi_instr_WDATA,
	output [3:0]  m_axi_instr_WSTRB,

	input         m_axi_instr_BVALID,
	output        m_axi_instr_BREADY,
	input  [1:0]  m_axi_instr_BRESP,
	
	output        m_axi_instr_ARVALID,
	input         m_axi_instr_ARREADY,
	output [31:0] m_axi_instr_ARADDR,
	output [2:0]  m_axi_instr_ARSIZE,
	
	input         m_axi_instr_RVALID,
	output        m_axi_instr_RREADY,
	input  [31:0] m_axi_instr_RDATA,
	input  [1:0]  m_axi_instr_RRESP,

	//AXI Data Bus
	output        m_axi_data_AWVALID,
	input         m_axi_data_AWREADY,
	output [31:0] m_axi_data_AWADDR,
	output [2:0]  m_axi_data_AWSIZE,
    output [3:0]  m_axi_data_AWCACHE,
    output [2:0]  m_axi_data_AWPROT,

	output        m_axi_data_WVALID,
	input         m_axi_data_WREADY,
	output [31:0] m_axi_data_WDATA,
	output [3:0]  m_axi_data_WSTRB,
	
	input         m_axi_data_BVALID,
	output        m_axi_data_BREADY,
	input  [1:0]  m_axi_data_BRESP,
	
	output        m_axi_data_ARVALID,
	input         m_axi_data_ARREADY,
	output [31:0] m_axi_data_ARADDR,
	output [2:0]  m_axi_data_ARSIZE,
    output [3:0]  m_axi_data_ARCACHE,
    output [2:0]  m_axi_data_ARPROT,
	
	input         m_axi_data_RVALID,
	output        m_axi_data_RREADY,
	input  [31:0] m_axi_data_RDATA,
	input  [1:0]  m_axi_data_RRESP
);

wire        obi_instr_req;
wire        obi_instr_gnt;
wire        obi_instr_rvalid;
wire [31:0] obi_instr_addr;
wire [1:0]  obi_instr_memtype;
wire [2:0]  obi_instr_prot;
wire        obi_instr_dbg;
wire [31:0] obi_instr_rdata;
wire        obi_instr_err;

wire        obi_data_req;
wire        obi_data_gnt;
wire        obi_data_rvalid;
wire        obi_data_we;
wire [3:0]  obi_data_be;
wire [31:0] obi_data_addr;
wire [1:0]  obi_data_memtype;
wire [2:0]  obi_data_prot;
wire        obi_data_dbg;
wire [31:0] obi_data_wdata;
wire [31:0] obi_data_rdata;
wire        obi_data_err;
wire [5:0]  obi_data_atop;
wire        obi_data_exokay;

// The CV-X-IF top exposes only the OBI signals a memory needs; the adapters'
// side-band inputs are tied off (the core ties instr/data_err_i and
// data_exokay_i itself, see cvxif_e40x_top.sv).
assign obi_instr_memtype = 2'b00;
assign obi_instr_prot    = 3'b000;
assign obi_instr_dbg     = 1'b0;
assign obi_data_memtype  = 2'b00;
assign obi_data_prot     = 3'b000;
assign obi_data_dbg      = 1'b0;
assign obi_data_atop     = 6'd0;

cvxif_e40x_top top_inst(
    .clk_i(clk),
    .rst_ni(~rst),
    // sim/linker_scripts/CV32E40X_link.ld: imem at 0x80000000.
    .boot_addr_i(32'h80000000),
    .fetch_enable_i(1'b1),

    .instr_req_o(obi_instr_req),
    .instr_gnt_i(obi_instr_gnt),
    .instr_rvalid_i(obi_instr_rvalid),
    .instr_addr_o(obi_instr_addr),
    .instr_rdata_i(obi_instr_rdata),

    .data_req_o(obi_data_req),
    .data_gnt_i(obi_data_gnt),
    .data_rvalid_i(obi_data_rvalid),
    .data_addr_o(obi_data_addr),
    .data_be_o(obi_data_be),
    .data_we_o(obi_data_we),
    .data_wdata_o(obi_data_wdata),
    .data_rdata_i(obi_data_rdata),

    .core_sleep_o(),
    .retire_valid_o(),
    .retire_pc_o()
);

obi_axi_adapter#(.DATA_WIDTH(32),.ADDR_WIDTH(32),.COMB_GNT(0)) obi_adapter_instr_inst (
    .s_obi_req(obi_instr_req),
    .s_obi_gnt(obi_instr_gnt),
    .s_obi_we(0),
    .s_obi_be(4'hF),
    .s_obi_addr(obi_instr_addr),
    .s_obi_memtype(obi_instr_memtype),
    .s_obi_prot(obi_instr_prot),
    .s_obi_dbg(obi_instr_dbg),
    .s_obi_wdata(32'dX),
    .s_obi_atop(6'd0),
    .s_obi_rvalid(obi_instr_rvalid),
    .s_obi_rdata(obi_instr_rdata),
    .s_obi_err(obi_instr_err),
    .s_obi_exokay(),

    .m_axi_AWVALID(m_axi_instr_AWVALID),
    .m_axi_AWREADY(m_axi_instr_AWREADY),
    .m_axi_AWADDR(m_axi_instr_AWADDR),
    .m_axi_AWSIZE(m_axi_instr_AWSIZE),
    .m_axi_AWCACHE(),
    .m_axi_AWPROT(),
    .m_axi_WVALID(m_axi_instr_WVALID),
    .m_axi_WREADY(m_axi_instr_WREADY),
    .m_axi_WDATA(m_axi_instr_WDATA),
    .m_axi_WSTRB(m_axi_instr_WSTRB),
    .m_axi_BVALID(m_axi_instr_BVALID),
    .m_axi_BREADY(m_axi_instr_BREADY),
    .m_axi_BRESP(m_axi_instr_BRESP),
    .m_axi_ARVALID(m_axi_instr_ARVALID),
    .m_axi_ARREADY(m_axi_instr_ARREADY),
    .m_axi_ARADDR(m_axi_instr_ARADDR),
    .m_axi_ARSIZE(m_axi_instr_ARSIZE),
    .m_axi_ARCACHE(),
    .m_axi_ARPROT(),
    .m_axi_RVALID(m_axi_instr_RVALID),
    .m_axi_RREADY(m_axi_instr_RREADY),
    .m_axi_RDATA(m_axi_instr_RDATA),
    .m_axi_RRESP(m_axi_instr_RRESP),

    .clk(clk),
    .rst(rst)
);

obi_axi_adapter#(.DATA_WIDTH(32),.ADDR_WIDTH(32),.COMB_GNT(0)) obi_adapter_data_inst (
    .s_obi_req(obi_data_req),
    .s_obi_gnt(obi_data_gnt),
    .s_obi_we(obi_data_we),
    .s_obi_be(obi_data_be),
    .s_obi_addr(obi_data_addr),
    .s_obi_memtype(obi_data_memtype),
    .s_obi_prot(obi_data_prot),
    .s_obi_dbg(obi_data_dbg),
    .s_obi_wdata(obi_data_wdata),
    .s_obi_atop(obi_data_atop),
    .s_obi_rvalid(obi_data_rvalid),
    .s_obi_rdata(obi_data_rdata),
    .s_obi_err(obi_data_err),
    .s_obi_exokay(obi_data_exokay),

    .m_axi_AWVALID(m_axi_data_AWVALID),
    .m_axi_AWREADY(m_axi_data_AWREADY),
    .m_axi_AWADDR(m_axi_data_AWADDR),
    .m_axi_AWSIZE(m_axi_data_AWSIZE),
    .m_axi_AWCACHE(m_axi_data_AWCACHE),
    .m_axi_AWPROT(m_axi_data_AWPROT),
    .m_axi_WVALID(m_axi_data_WVALID),
    .m_axi_WREADY(m_axi_data_WREADY),
    .m_axi_WDATA(m_axi_data_WDATA),
    .m_axi_WSTRB(m_axi_data_WSTRB),
    .m_axi_BVALID(m_axi_data_BVALID),
    .m_axi_BREADY(m_axi_data_BREADY),
    .m_axi_BRESP(m_axi_data_BRESP),
    .m_axi_ARVALID(m_axi_data_ARVALID),
    .m_axi_ARREADY(m_axi_data_ARREADY),
    .m_axi_ARADDR(m_axi_data_ARADDR),
    .m_axi_ARSIZE(m_axi_data_ARSIZE),
    .m_axi_ARCACHE(m_axi_data_ARCACHE),
    .m_axi_ARPROT(m_axi_data_ARPROT),
    .m_axi_RVALID(m_axi_data_RVALID),
    .m_axi_RREADY(m_axi_data_RREADY),
    .m_axi_RDATA(m_axi_data_RDATA),
    .m_axi_RRESP(m_axi_data_RRESP),

    .clk(clk),
    .rst(rst)
);

endmodule