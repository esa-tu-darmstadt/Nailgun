// Negative control: a CV-X-IF coprocessor that claims nothing.
//
// Same port shape as the generated cvxif_coproc_cva6_<name>, but it never
// accepts an instruction, so every custom encoding traps as illegal and the
// test must fail. If the run passes with this in place, the test is not
// actually exercising the ISAX.
module cvxif_coproc_cva6_null #(
  parameter int unsigned X_ID_WIDTH  = 4,
  parameter int unsigned X_NUM_RS    = 2,
  parameter int unsigned X_RFR_WIDTH = 32,
  parameter int unsigned X_RFW_WIDTH = 32,
  parameter type         cvxif_req_t  = logic,
  parameter type         cvxif_resp_t = logic
) (
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic        clk_i,
  input  logic        rst_ni,
  input  cvxif_req_t  cvxif_req_i,
  /* verilator lint_on UNUSEDSIGNAL */
  output cvxif_resp_t cvxif_resp_o
);

  cvxif_resp_t resp;
  always_comb begin
    resp                   = '0;
    resp.compressed_ready  = 1'b1;   // answer immediately, accept nothing
    resp.issue_ready       = 1'b1;
    resp.register_ready    = 1'b1;
  end
  assign cvxif_resp_o = resp;

endmodule
