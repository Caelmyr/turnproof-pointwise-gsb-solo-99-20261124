"""Describe source positions and compare two adopted booth captures."""

from math import hypot

from image_lab.validation import number, vector


def checked_mark(value, frame):
    if value is None:
        return None
    x, y = vector(value, "原片定位点", 2)
    return [
        number(x, "定位横像素", 0, frame["width"] - 1),
        number(y, "定位纵像素", 0, frame["height"] - 1),
    ]


def normalized(frame):
    x, y = frame["mark"]
    return x / (frame["width"] - 1), y / (frame["height"] - 1)


def transition(left, right):
    if left is None or right is None or left["mark"] is None or right["mark"] is None:
        return None
    x1, y1 = normalized(left)
    x2, y2 = normalized(right)
    dx, dy = (x2 - x1) * 100, (y2 - y1) * 100
    return {"dx": dx, "dy": dy, "drift": hypot(dx, dy)}


def manual_frames(record):
    captures = {capture["id"]: capture for capture in record["captures"]}
    return [
        {"angle": slot["angle"], "locked": slot["locked"], "frame": captures.get(slot["selected"])}
        for slot in record["slots"]
    ]


def manual_transition(record, slot):
    frames = manual_frames(record)
    left, right = frames[slot], frames[(slot + 1) % len(frames)]
    return {"left": left, "right": right, "movement": transition(left["frame"], right["frame"])}
