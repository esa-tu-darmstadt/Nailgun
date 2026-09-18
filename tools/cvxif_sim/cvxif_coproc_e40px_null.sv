// Negative control: a CV32E40PX CV-X-IF coprocessor that claims nothing.
//
// Same port shape as the generated cvxif_coproc_e40px_<name>, but it never
// accepts an instruction, so every custom encoding traps as illegal and the
// test must fail. If the run passes with this in place, the test is not
// actually exercising the ISAX.
module cvxif_coproc_e40px_null
  import cv32e40px_core_v_xif_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic               clk_i,
  input  logic               rst_ni,

  input  logic               x_compressed_valid_i,
  input  x_compressed_req_t  x_compressed_req_i,
  output logic               x_compressed_ready_o,
  output x_compressed_resp_t x_compressed_resp_o,

  input  logic               x_issue_valid_i,
  input  x_issue_req_t       x_issue_req_i,
  output logic               x_issue_ready_o,
  output x_issue_resp_t      x_issue_resp_o,

  input  logic               x_commit_valid_i,
  input  x_commit_t          x_commit_i,

  input  logic               x_mem_ready_i,
  input  x_mem_resp_t        x_mem_resp_i,
  output logic               x_mem_valid_o,
  output x_mem_req_t         x_mem_req_o,
  input  logic               x_mem_result_valid_i,
  input  x_mem_result_t      x_mem_result_i,

  input  logic               x_result_ready_i,
  /* verilator lint_on UNUSEDSIGNAL */
  output logic               x_result_valid_o,
  output x_result_t          x_result_o
);

  assign x_compressed_ready_o = 1'b1;   // answer immediately, accept nothing
  assign x_compressed_resp_o  = '0;
  assign x_issue_ready_o      = 1'b1;
  assign x_issue_resp_o       = '0;
  assign x_mem_valid_o        = 1'b0;
  assign x_mem_req_o          = '0;
  assign x_result_valid_o     = 1'b0;
  assign x_result_o           = '0;

endmodule
