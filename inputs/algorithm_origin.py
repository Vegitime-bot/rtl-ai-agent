def tcon_origin_timing(cfg):
    """Raster scan timing for 1080p60 panel (origin)."""
    for v in range(cfg.v_total):
        for h in range(cfg.h_total):
            if h == 0 and v == 0:
                start_of_frame()

            if h < cfg.h_active and v < cfg.v_active:
                drive_de(True)
                emit_pixel()
            else:
                drive_de(False)

            drive_hsync(not (cfg.h_active + cfg.h_front <= h < cfg.h_active + cfg.h_front + cfg.h_sync))
            drive_vsync(not (cfg.v_active + cfg.v_front <= v < cfg.v_active + cfg.v_front + cfg.v_sync))

        end_of_line()
    end_of_frame()
