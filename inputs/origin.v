// Display Timing Controller (origin) – 1080p60 RGB parallel output
module tcon_basic (
    input  logic clk_pixel,
    input  logic rst_n,
    input  logic enable,
    output logic hsync,
    output logic vsync,
    output logic de,
    output logic frame_done
);

  localparam int H_ACTIVE = 1920;
  localparam int H_FRONT  = 88;
  localparam int H_SYNC   = 44;
  localparam int H_BACK   = 148;
  localparam int V_ACTIVE = 1080;
  localparam int V_FRONT  = 4;
  localparam int V_SYNC   = 5;
  localparam int V_BACK   = 36;

  localparam int H_TOTAL = H_ACTIVE + H_FRONT + H_SYNC + H_BACK;
  localparam int V_TOTAL = V_ACTIVE + V_FRONT + V_SYNC + V_BACK;

  logic [$clog2(H_TOTAL)-1:0] h_cnt;
  logic [$clog2(V_TOTAL)-1:0] v_cnt;

  always_ff @(posedge clk_pixel or negedge rst_n) begin
    if (!rst_n) begin
      h_cnt      <= '0;
      v_cnt      <= '0;
      frame_done <= 1'b0;
    end else if (!enable) begin
      h_cnt      <= '0;
      v_cnt      <= '0;
      frame_done <= 1'b0;
    end else begin
      frame_done <= 1'b0;
      if (h_cnt == H_TOTAL-1) begin
        h_cnt <= '0;
        if (v_cnt == V_TOTAL-1) begin
          v_cnt      <= '0;
          frame_done <= 1'b1;
        end else begin
          v_cnt <= v_cnt + 1'b1;
        end
      end else begin
        h_cnt <= h_cnt + 1'b1;
      end
    end
  end

  always_comb begin
    de    = enable &&
            (h_cnt < H_ACTIVE) &&
            (v_cnt < V_ACTIVE);

    hsync = !((h_cnt >= H_ACTIVE + H_FRONT) &&
              (h_cnt <  H_ACTIVE + H_FRONT + H_SYNC));
    vsync = !((v_cnt >= V_ACTIVE + V_FRONT) &&
              (v_cnt <  V_ACTIVE + V_FRONT + V_SYNC));
  end

endmodule
