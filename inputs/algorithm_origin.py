from typing import List, Dict


def clip_u8(v: int) -> int:
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def original_tcon_model(
    frame: List[List[int]],
    mirror_en: bool = False,
    crop_en: bool = False,
    crop_x_start: int = 0,
    crop_x_end: int = 0,
    crop_y_start: int = 0,
    crop_y_end: int = 0,
    testpat_en: bool = False,
) -> Dict[str, object]:
    if not frame:
        return {
            "out_frame": [],
            "line_avg": [],
            "line_checksum": [],
            "line_flat": [],
        }

    height = len(frame)
    width = len(frame[0])

    for row in frame:
        if len(row) != width:
            raise ValueError("All rows must have the same width")

    out_frame: List[List[int]] = []
    line_avg: List[int] = []
    line_checksum: List[int] = []
    line_flat: List[bool] = []

    for y in range(height):
        in_line = [clip_u8(p) for p in frame[y]]

        checksum = sum(in_line)
        avg = checksum // width
        flat = all(p == in_line[0] for p in in_line) if width > 0 else True

        line_avg.append(avg)
        line_checksum.append(checksum)
        line_flat.append(flat)

        out_line: List[int] = []

        for x in range(width):
            src_x = width - 1 - x if mirror_en else x

            if testpat_en:
                pix = ((y & 0xF) << 4) | (x & 0xF)
            else:
                pix = in_line[src_x]

                if crop_en:
                    in_crop = (
                        crop_x_start <= x <= crop_x_end and
                        crop_y_start <= y <= crop_y_end
                    )
                    if not in_crop:
                        pix = 0

            out_line.append(clip_u8(pix))

        out_frame.append(out_line)

    return {
        "out_frame": out_frame,
        "line_avg": line_avg,
        "line_checksum": line_checksum,
        "line_flat": line_flat,
    }