"""Freeze a manually reviewed spin and write a portable photography proof."""

from io import BytesIO
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from PIL import Image, ImageDraw

from image_lab.exporting import json_bytes
from image_lab.validation import Invalid, timestamp

from . import cropping
from .inspection import manual_frames, transition


def resolved(record):
    frames = manual_frames(record)
    if any(slot["frame"] is None for slot in frames):
        raise Invalid("每个台位都选好原片后才能封存。")
    return frames


def contact_sheet(slots, source, plan=None):
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
            window = cropping.window_for(plan, index) if plan else None
            with Image.open(source(frame["id"])) as image:
                if window:
                    image = cropping.crop_image(image, window)
                image.thumbnail((width - 20, height - 30), Image.Resampling.LANCZOS)
                sheet.paste(image, (x + (width - image.width) // 2, y + 6 + (height - 30 - image.height) // 2))
        draw.text((x + 14, y + height - 25), f'{slot["angle"]:03}°' + ("   —" if not frame else ""),
                  fill="#25443e", font_size=13)
    stream = BytesIO()
    sheet.save(stream, "PNG")
    return stream.getvalue()


def write(folder: Path, identifier, title, record, source, plan=None):
    slots = resolved(record)
    if plan and not cropping.is_current(plan, record):
        plan = None
    frames = []
    (folder / "frames").mkdir(exist_ok=True)
    for index, slot in enumerate(slots):
        frame = slot["frame"]
        window = cropping.window_for(plan, index) if plan else None
        angle = slot["angle"]
        source_path = source(frame["id"])
        target = folder / "frames" / f"{angle:03}.png"
        if window:
            with Image.open(source_path) as image:
                cropping.crop_image(image, window).save(target, format="PNG")
            source_file = f"sources/{angle:03}.png"
            source_bytes = source_path.read_bytes()
        else:
            # Legacy seal: the delivered frame is the original capture itself.
            target.write_bytes(source_path.read_bytes())
            source_file = None
            source_bytes = None
        crop_bytes = target.read_bytes()
        with Image.open(source_path) as image:
            source_size = list(image.size)
        frames.append({
            "angle": angle,
            "locked": slot["locked"],
            "capture": frame,
            "file": f"frames/{angle:03}.png",
            "source_file": source_file,
            "source_size": source_size,
            "crop": window,
            "png_sha256": sha256(crop_bytes).hexdigest(),
            "source_sha256": sha256(source_bytes).hexdigest() if source_bytes else frame.get("sha256"),
            "movement_to_next": transition(frame, slots[(index + 1) % len(slots)]["frame"]),
        })
    proof = {
        "id": identifier, "title": title, "created": timestamp(), "project_id": record["id"],
        "project_title": record["title"], "source_revision": record["revision"], "frames": frames,
        "crop_plan": plan,
    }
    metadata = json_bytes(proof)
    contact = contact_sheet(slots, source, plan)
    (folder / "proof.json").write_bytes(metadata)
    (folder / "contact.png").write_bytes(contact)
    with ZipFile(folder / "spin.zip", mode="w", compression=ZIP_STORED) as archive:
        archive.writestr("spin.json", metadata)
        archive.writestr("contact.png", contact)
        for entry, frame_entry in zip(frames, slots):
            archive.write(folder / entry["file"], entry["file"])
            if entry["source_file"]:
                archive.writestr(entry["source_file"],
                                 source(frame_entry["frame"]["id"]).read_bytes())
    return proof
