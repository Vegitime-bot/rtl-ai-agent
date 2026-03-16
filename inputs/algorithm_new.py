def tcon_partial_update(cfg, roi, te_signal):
    """New timing controller algorithm with ROI updates + adaptive porch."""
    active_cfg = cfg.shadow.commit()
    frac_accum = 0

    for v in range(active_cfg.v_total()):
        line_portion = derive_active_window(v, roi, active_cfg)
        for h in range(active_cfg.h_total()):
            inside_roi = line_portion.x0 <= h < line_portion.x1

            if inside_roi:
                emit_pixel(fetch_roi_pixel(h, v))
            else:
                emit_pixel(active_cfg.idle_color)

            drive_de(inside_roi)
            drive_hsync(compute_dynamic_hsync(h, active_cfg))
            drive_vsync(compute_dynamic_vsync(v, active_cfg))

            frac_accum += active_cfg.frac_step
            if frac_accum >= 16:
                insert_extra_clk()
                frac_accum -= 16

        align_to_te(te_signal)  # wait for panel tearing effect feedback
    signal_end_of_frame()
