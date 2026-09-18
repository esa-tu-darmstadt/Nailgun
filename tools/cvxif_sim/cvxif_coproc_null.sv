// Negative control: a coprocessor that claims nothing.
module cvxif_coproc_null #(
  parameter int unsigned X_ID_WIDTH = 4, parameter int unsigned X_NUM_RS = 2,
  parameter int unsigned X_RFR_WIDTH = 32, parameter int unsigned X_RFW_WIDTH = 32
) (
  input logic clk_i, input logic rst_ni,
  cv32e40x_if_xif.coproc_compressed xif_compressed_if,
  cv32e40x_if_xif.coproc_issue      xif_issue_if,
  cv32e40x_if_xif.coproc_commit     xif_commit_if,
  cv32e40x_if_xif.coproc_mem        xif_mem_if,
  cv32e40x_if_xif.coproc_mem_result xif_mem_result_if,
  cv32e40x_if_xif.coproc_result     xif_result_if
);
  assign xif_compressed_if.compressed_ready = 1'b1;
  assign xif_compressed_if.compressed_resp  = '0;
  assign xif_issue_if.issue_ready = 1'b1;
  assign xif_issue_if.issue_resp  = '0;
  assign xif_mem_if.mem_valid = 1'b0;
  assign xif_mem_if.mem_req   = '0;
  assign xif_result_if.result_valid = 1'b0;
  assign xif_result_if.result       = '0;
endmodule
