"""Freeze a manually reviewed spin and write a portable photography proof."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from PIL import Image, ImageDraw

from image_lab.exporting import json_bytes
from image_lab.validation import Invalid, timestamp

from .inspection import manual_frames, transition


def resolved(record):
    frames = manual_frames(record)
    if any(slot["frame"] is None for slot in frames):
        raise Invalid("每个台位都选好原片后才能封存。")
    return frames


def contact_sheet(slots, source):
    columns = min(len(slots), 4)
    width, height = 234, 174
    rows = (len(slots) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * height + 28), "#f1e9da")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 9), "TURNPROOF  /  CONTACT", fill="#25443e", font_size=12)
    for index, slot in enumerate(slots):
        x, y = index % columns * width, index // columns * height + 28
        frame = slot["frame"]
        draw.rectangle((x + 8, y + 4, x + width - 8, y + height - 7), fill="#e5dccb")
        if frame:
            with Image.open(source(frame["id"])) as image:
                image.thumbnail((width - 20, height - 30), Image.Resampling.LANCZOS)
                sheet.paste(image, (x + (width - image.width) // 2, y + 6 + (height - 30 - image.height) // 2))
        draw.text((x + 14, y + height - 25), f'{slot["angle"]:03}°' + ("   —" if not frame else ""),
                  fill="#25443e", font_size=13)
    stream = BytesIO()
    sheet.save(stream, "PNG")
    return stream.getvalue()


def write(folder: Path, identifier, title, record, source):
    slots = resolved(record)
    frames = []
    for index, slot in enumerate(slots):
        frame = slot["frame"]
        frames.append({
            "angle": slot["angle"],
            "locked": slot["locked"],
            "capture": frame,
            "file": f'frames/{slot["angle"]:03}.png',
            "movement_to_next": transition(frame, slots[(index + 1) % len(slots)]["frame"]),
        })
    proof = {
        "id": identifier, "title": title, "created": timestamp(), "project_id": record["id"],
        "project_title": record["title"], "source_revision": record["revision"], "frames": frames,
    }
    metadata = json_bytes(proof)
    contact = contact_sheet(slots, source)
    (folder / "proof.json").write_bytes(metadata)
    (folder / "contact.png").write_bytes(contact)
    with ZipFile(folder / "spin.zip", mode="w", compression=ZIP_STORED) as archive:
        archive.writestr("spin.json", metadata)
        archive.writestr("contact.png", contact)
        for frame in frames:
            archive.write(source(frame["capture"]["id"]), frame["file"])
    return proof
