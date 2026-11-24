"""Decode product photographs into their upright review coordinates."""

from io import BytesIO

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid

MAX_UPLOAD = 12 * 1024 * 1024
MAX_PIXELS = 3_200_000


def decode(data):
    if len(data) > MAX_UPLOAD:
        raise Invalid("单张原片至多 12 MiB。")
    try:
        with Image.open(BytesIO(data)) as source:
            width, height = source.size
            if source.format not in {"PNG", "JPEG", "TIFF"} or getattr(source, "n_frames", 1) != 1:
                raise Invalid("请选择单帧 PNG、JPEG 或 TIFF。")
            if min(width, height) < 20 or width * height > MAX_PIXELS or max(width, height) > 8192:
                raise Invalid("原片短边至少 20 像素，长边至多 8192 像素，总量至多 320 万像素。")
            source = ImageOps.exif_transpose(source)
            if "A" in source.getbands() or "transparency" in source.info:
                flattened = Image.new("RGBA", source.size, "white")
                flattened.alpha_composite(source.convert("RGBA"))
                return flattened.convert("RGB")
            if source.mode.startswith("I;16"):
                raster = np.asarray(source, dtype=np.uint16)
                return Image.fromarray((raster // 257).astype(np.uint8)).convert("RGB")
            return source.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise Invalid("读不到这张原片。") from error


def png(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()




def thumbnail(image):
    preview = image.copy()
    preview.thumbnail((360, 270), Image.Resampling.LANCZOS)
    stream = BytesIO()
    preview.save(stream, "JPEG", quality=86)
    return stream.getvalue()


def exposure(path):
    with Image.open(path) as source:
        raster = np.asarray(source)
        height, width = raster.shape[:2]
        gray = np.rint(raster @ np.array([0.2126, 0.7152, 0.0722])).astype(np.uint8)
        histogram = np.bincount(gray.ravel(), minlength=256).reshape(16, 16).sum(axis=1)
        total = height * width
        bright = int(np.count_nonzero(np.all(raster >= 250, axis=2)))
        dark = int(np.count_nonzero(np.all(raster <= 5, axis=2)))
    return {"histogram": histogram.tolist(), "bright": 100 * bright / total, "dark": 100 * dark / total}
