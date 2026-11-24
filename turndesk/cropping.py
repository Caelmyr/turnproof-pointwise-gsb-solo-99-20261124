"""Plan one shared 16:9 crop window across a manually reviewed spin.

Every crop is a pure integer pixel window taken from its own source frame:
no resizing, no padding.  The user supplies a composition landing point in
percent of the crop and a horizontal allowance in percentage points.  The
vertical landing is snapped to the nearest crop pixel; the horizontal landing
may drift inside the allowance.  All crops share one size, so the marked base
point lands on the same crop pixel in every output frame.
"""

import math

from image_lab.validation import Invalid, number


RATIO_WIDTH = 16
RATIO_HEIGHT = 9


def anchor_pixel(percent, dimension):
    """Nearest crop pixel whose pixel-center sits at ``percent`` of the side."""
    pixel = math.floor(percent / 100.0 * dimension + 0.5)
    return max(0, min(dimension - 1, pixel))


def _band_pixels(low_percent, high_percent, dimension):
    """Crop pixels whose pixel-center fraction lies inside the percent band."""
    low = math.ceil(low_percent / 100.0 * dimension - 0.5)
    high = math.floor(high_percent / 100.0 * dimension - 0.5)
    return max(0, low), min(dimension - 1, high)


def plan(frames, anchor_x, anchor_y, tolerance):
    """Return ``{"plan": ...}`` or ``{"blocked": ...}`` for the adopted spin.

    ``frames`` is the output of :func:`turndesk.inspection.manual_frames`.
    Window sizes are searched from the largest 16:9 rectangle the smallest
    source can hold downwards; the first feasible size keeps the most source
    pixels.  At one size the horizontal anchor closest to the requested
    landing wins, ties breaking toward the smaller pixel.
    """
    anchor_x = number(anchor_x, "横向构图落点", 0, 100)
    anchor_y = number(anchor_y, "纵向构图落点", 0, 100)
    tolerance = number(tolerance, "横向容许偏离", 0, 100)

    prepared, missing_frames, missing_marks = [], [], []
    for index, slot in enumerate(frames):
        frame = slot["frame"]
        if frame is None:
            missing_frames.append(slot["angle"])
        elif not frame.get("mark"):
            missing_marks.append({"angle": slot["angle"], "capture": frame["id"], "name": frame["name"]})
        else:
            prepared.append((index, slot, frame))

    if missing_frames or missing_marks:
        return {"blocked": {
            "kind": "incomplete",
            "missing_frames": missing_frames,
            "missing_marks": missing_marks,
        }}

    max_scale = min(
        min(frame["width"] for _, _, frame in prepared) // RATIO_WIDTH,
        min(frame["height"] for _, _, frame in prepared) // RATIO_HEIGHT,
    )
    if max_scale < 1:
        raise Invalid("原片尺寸放不下最小的 16:9 裁窗。")

    last_diagnostic = None
    for scale in range(max_scale, 0, -1):
        width, height = RATIO_WIDTH * scale, RATIO_HEIGHT * scale
        anchor_y_px = anchor_pixel(anchor_y, height)
        vertical_blockers = []
        horizontal_ranges = []
        for index, slot, frame in prepared:
            mark_x, mark_y = frame["mark"]
            vertical_ok = mark_y >= anchor_y_px and frame["height"] - 1 - mark_y >= anchor_y_px
            if not vertical_ok:
                vertical_blockers.append(index)
            low = max(0, width - frame["width"] + mark_x)
            high = min(width - 1, mark_x)
            horizontal_ranges.append((index, low, high))

        image_low = max(low for _, low, _ in horizontal_ranges)
        image_high = min(high for _, _, high in horizontal_ranges)
        band_low, band_high = _band_pixels(anchor_x - tolerance, anchor_x + tolerance, width)
        feasible_low = max(image_low, band_low)
        feasible_high = min(image_high, band_high)

        if not vertical_blockers and feasible_low <= feasible_high:
            requested_x = anchor_pixel(anchor_x, width)
            if requested_x < feasible_low:
                anchor_x_px = feasible_low
            elif requested_x > feasible_high:
                anchor_x_px = feasible_high
            else:
                anchor_x_px = requested_x
            window_frames = []
            for index, slot, frame in prepared:
                mark_x, mark_y = frame["mark"]
                window_frames.append({
                    "slot": index,
                    "angle": slot["angle"],
                    "capture": frame["id"],
                    "mark": [mark_x, mark_y],
                    "x": mark_x - anchor_x_px,
                    "y": mark_y - anchor_y_px,
                    "width": width,
                    "height": height,
                })
            return {"plan": {
                "width": width,
                "height": height,
                "anchor": [anchor_x_px, anchor_y_px],
                "anchor_pct": [
                    round((anchor_x_px + 0.5) / width * 100, 4),
                    round((anchor_y_px + 0.5) / height * 100, 4),
                ],
                "anchor_request": [anchor_x, anchor_y],
                "tolerance": tolerance,
                "frames": window_frames,
            }}

        diagnostic = _diagnostic(
            prepared, horizontal_ranges, width, height, anchor_y_px,
            vertical_blockers, image_low, image_high, band_low, band_high,
        )
        if last_diagnostic is None:
            largest_diagnostic = diagnostic
        last_diagnostic = diagnostic

    return {"blocked": {
        "kind": "no_window",
        "scale_tried": [max_scale, 1],
        "at_largest_window": largest_diagnostic,
        "at_smallest_window": last_diagnostic,
    }}


def _diagnostic(prepared, horizontal_ranges, width, height, anchor_y_px,
                vertical_blockers, image_low, image_high, band_low, band_high):
    details = []
    for (index, slot, frame), (_, range_low, range_high) in zip(prepared, horizontal_ranges):
        mark_x, mark_y = frame["mark"]
        details.append({
            "angle": slot["angle"],
            "capture": frame["id"],
            "name": frame["name"],
            "source": [frame["width"], frame["height"]],
            "mark": [mark_x, mark_y],
            "vertical_ok": index not in vertical_blockers,
            "anchor_x_range": [range_low, range_high],
            "within_tolerance": range_high >= band_low and range_low <= band_high,
        })
    return {
        "window": [width, height],
        "anchor_y_px": anchor_y_px,
        "image_intersection": [image_low, image_high] if image_low <= image_high else None,
        "tolerance_band": [band_low, band_high],
        "details": details,
    }


def window_for(plan, slot):
    """Return the stored crop window dict for a slot, or ``None``."""
    if not plan:
        return None
    for item in plan["frames"]:
        if item["slot"] == slot:
            return item
    return None


def is_current(plan, record):
    """A plan stays valid only while every adopted capture and mark is unchanged."""
    if not plan:
        return False
    slots = record["slots"]
    captures = {capture["id"]: capture for capture in record["captures"]}
    if len(plan["frames"]) != len(slots):
        return False
    for item in plan["frames"]:
        slot = slots[item["slot"]]
        frame = captures.get(slot["selected"])
        if frame is None or frame["id"] != item["capture"] or frame.get("mark") != item["mark"]:
            return False
        if item["width"] != plan["width"] or item["height"] != plan["height"]:
            return False
    return True


def crop_image(image, window):
    """Crop without resampling; the window is guaranteed to lie inside."""
    x, y, width, height = window["x"], window["y"], window["width"], window["height"]
    cropped = image.crop((x, y, x + width, y + height))
    if cropped.size != (width, height):
        raise Invalid("裁窗超出原片范围。")
    return cropped
