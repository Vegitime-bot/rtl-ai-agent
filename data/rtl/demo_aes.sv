module demo_aes (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [127:0] in_block,
    input  logic         in_valid,
    output logic [127:0] out_block,
    output logic         out_valid
);

  logic [3:0] round_cnt;
  logic [127:0] state_reg;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      round_cnt <= '0;
      state_reg <= '0;
    end else if (in_valid) begin
      round_cnt <= 4'd0;
      state_reg <= in_block;
    end else if (round_cnt < 4'd10) begin
      round_cnt <= round_cnt + 1'b1;
      state_reg <= state_reg ^ 128'h1;
    end
  end

  assign out_block = state_reg;
  assign out_valid = (round_cnt == 4'd10);

endmodule
