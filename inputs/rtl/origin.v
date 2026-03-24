module original_rtl #(
    parameter H_ACTIVE = 16,
    parameter V_ACTIVE = 8,
    parameter PIXEL_W  = 8,
    parameter XW       = 8,
    parameter YW       = 8
)(
    input                       clk,
    input                       rst_n,

    input                       in_valid,
    input      [PIXEL_W-1:0]    in_pixel,

    input                       mirror_en,
    input                       crop_en,
    input      [XW-1:0]         crop_x_start,
    input      [XW-1:0]         crop_x_end,
    input      [YW-1:0]         crop_y_start,
    input      [YW-1:0]         crop_y_end,
    input                       testpat_en,
    input                       hsync_pol,
    input                       vsync_pol,

    output reg                  out_valid,
    output reg [PIXEL_W-1:0]    out_pixel,
    output reg                  de,
    output reg                  hsync,
    output reg                  vsync,
    output reg                  frame_start,
    output reg                  line_start,
    output reg                  line_done,
    output reg                  frame_done,

    output reg [15:0]           stat_in_pixels,
    output reg [15:0]           stat_out_pixels,
    output reg [PIXEL_W-1:0]    stat_line_avg,
    output reg [15:0]           stat_line_checksum,
    output reg                  stat_line_flat
);

    localparam ST_FILL = 3'd0;
    localparam ST_PREP = 3'd1;
    localparam ST_OUT  = 3'd2;

    reg [2:0] state;

    reg [PIXEL_W-1:0] line_buf [0:H_ACTIVE-1];

    reg [XW-1:0] fill_x;
    reg [YW-1:0] fill_y;

    reg [XW-1:0] out_x;
    reg [YW-1:0] out_y;

    reg [XW-1:0] rd_idx;

    reg [15:0] line_sum;
    reg [PIXEL_W-1:0] line_first_pixel;
    reg line_flat_accum;

    reg [PIXEL_W-1:0] raw_pixel;
    reg [PIXEL_W-1:0] crop_pixel;
    reg [PIXEL_W-1:0] final_pixel;

    reg in_crop_window;
    reg [PIXEL_W-1:0] test_pattern_pixel;

    integer i;

    always @(*) begin
        if (mirror_en) begin
            rd_idx = H_ACTIVE - 1 - out_x;
        end else begin
            rd_idx = out_x;
        end
    end

    always @(*) begin
        raw_pixel = line_buf[rd_idx];
    end

    always @(*) begin
        if (crop_en) begin
            if ((out_x >= crop_x_start) && (out_x <= crop_x_end) &&
                (out_y >= crop_y_start) && (out_y <= crop_y_end)) begin
                in_crop_window = 1'b1;
            end else begin
                in_crop_window = 1'b0;
            end
        end else begin
            in_crop_window = 1'b1;
        end
    end

    always @(*) begin
        if (in_crop_window) begin
            crop_pixel = raw_pixel;
        end else begin
            crop_pixel = {PIXEL_W{1'b0}};
        end
    end

    always @(*) begin
        test_pattern_pixel = {out_y[3:0], out_x[3:0]};
    end

    always @(*) begin
        if (testpat_en) begin
            final_pixel = test_pattern_pixel;
        end else begin
            final_pixel = crop_pixel;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state              <= ST_FILL;

            fill_x             <= 0;
            fill_y             <= 0;
            out_x              <= 0;
            out_y              <= 0;

            out_valid          <= 0;
            out_pixel          <= 0;
            de                 <= 0;
            hsync              <= 0;
            vsync              <= 0;
            frame_start        <= 0;
            line_start         <= 0;
            line_done          <= 0;
            frame_done         <= 0;

            stat_in_pixels     <= 0;
            stat_out_pixels    <= 0;
            stat_line_avg      <= 0;
            stat_line_checksum <= 0;
            stat_line_flat     <= 0;

            line_sum           <= 0;
            line_first_pixel   <= 0;
            line_flat_accum    <= 1'b1;

            for (i = 0; i < H_ACTIVE; i = i + 1) begin
                line_buf[i] <= 0;
            end
        end else begin
            out_valid   <= 1'b0;
            de          <= 1'b0;
            hsync       <= ~hsync_pol;
            vsync       <= ~vsync_pol;
            frame_start <= 1'b0;
            line_start  <= 1'b0;
            line_done   <= 1'b0;
            frame_done  <= 1'b0;

            case (state)
                ST_FILL: begin
                    if (in_valid) begin
                        line_buf[fill_x] <= in_pixel;
                        stat_in_pixels   <= stat_in_pixels + 1'b1;
                        line_sum         <= line_sum + in_pixel;

                        if (fill_x == 0) begin
                            line_first_pixel <= in_pixel;
                            line_flat_accum  <= 1'b1;
                        end else begin
                            if (in_pixel != line_first_pixel) begin
                                line_flat_accum <= 1'b0;
                            end
                        end

                        if (fill_x == H_ACTIVE - 1) begin
                            fill_x <= 0;
                            state  <= ST_PREP;
                        end else begin
                            fill_x <= fill_x + 1'b1;
                        end
                    end
                end

                ST_PREP: begin
                    stat_line_checksum <= line_sum;
                    stat_line_avg      <= line_sum / H_ACTIVE;
                    stat_line_flat     <= line_flat_accum;

                    out_x <= 0;
                    state <= ST_OUT;
                end

                ST_OUT: begin
                    out_valid       <= 1'b1;
                    de              <= 1'b1;
                    out_pixel       <= final_pixel;
                    stat_out_pixels <= stat_out_pixels + 1'b1;

                    if ((out_x == 0) && (out_y == 0)) begin
                        frame_start <= 1'b1;
                        vsync       <= vsync_pol;
                    end

                    if (out_x == 0) begin
                        line_start <= 1'b1;
                        hsync      <= hsync_pol;
                    end

                    if (out_x == H_ACTIVE - 1) begin
                        line_done <= 1'b1;
                    end

                    if ((out_x == H_ACTIVE - 1) && (out_y == V_ACTIVE - 1)) begin
                        frame_done <= 1'b1;
                    end

                    if (out_x == H_ACTIVE - 1) begin
                        out_x <= 0;

                        line_sum         <= 0;
                        line_first_pixel <= 0;
                        line_flat_accum  <= 1'b1;

                        if (out_y == V_ACTIVE - 1) begin
                            out_y  <= 0;
                            fill_y <= 0;
                            state  <= ST_FILL;
                        end else begin
                            out_y  <= out_y + 1'b1;
                            fill_y <= fill_y + 1'b1;
                            state  <= ST_FILL;
                        end
                    end else begin
                        out_x <= out_x + 1'b1;
                    end
                end

                default: begin
                    state <= ST_FILL;
                end
            endcase
        end
    end

endmodule