"""Make a labeled synthetic contact sequence for practicing turntable review."""

from math import cos, radians, sin

from PIL import Image, ImageDraw, ImageFilter


# A rectangular ceramic package and three distinct glaze faces, viewed in a booth.
FACES = (
    ((0, 1), "#1c5450", "FORM"), ((1, 2), "#37624e", "STUDIO"),
    ((2, 3), "#596548", "07"), ((3, 0), "#2b5143", "GLAZE"),
)
CORNERS = ((-98, -73), (98, -73), (98, 73), (-98, 73))


def frame(angle, center, sharp, take):
    width, height = 640, 422
    pixels = Image.new("RGB", (width, height), "#d4c7b0")
    draw = ImageDraw.Draw(pixels)
    for y in range(height):
        shade = int(8 * y / height + 17 * (y / height) ** 3)
        draw.line((0, y, width, y), fill=(229 - shade, 218 - shade, 194 - shade))
    draw.rectangle((0, 371, width, height), fill="#d2c1a7")
    draw.ellipse((141, 251, 529, 347), fill="#b1a089")
    draw.ellipse((160, 229, 491, 327), fill="#938577")
    draw.ellipse((160, 211, 491, 308), fill="#c0ad90")
    draw.ellipse((172, 220, 479, 300), outline="#a08e73", width=2)

    theta = radians(angle + 22)
    footprint = [(x * cos(theta) - z * sin(theta), x * sin(theta) + z * cos(theta)) for x, z in CORNERS]

    def project(point, lift):
        x, z = point
        return (round(center + x * (1 + z / 650)), round(263 + 0.23 * z - lift * (1 + z / 760)))

    top = [project(point, 145) for point in footprint]
    floor = [project(point, 0) for point in footprint]
    draw.polygon(top, fill="#87a78d", outline="#627e66", width=2)
    for (left, right), color, label in sorted(FACES, key=lambda face: sum(footprint[i][1] for i in face[0])):
        points = [top[left], top[right], floor[right], floor[left]]
        # Outward-facing projection follows the clockwise footprint's screen winding.
        if top[right][0] <= top[left][0]:
            continue
        draw.polygon(points, fill=color, outline="#2a5244", width=2)
        usable = top[right][0] - top[left][0]
        mid_x = (top[left][0] + top[right][0]) // 2
        face_y = (top[left][1] + top[right][1]) // 2 + 69
        if usable >= 49:
            draw.text((mid_x, face_y), label, anchor="mm", fill="#f3dec1", font_size=min(22, usable // 4))
        if usable >= 70:
            for offset in (30, 35, 41, 52):
                draw.line((mid_x - usable * 0.26, face_y + offset,
                           mid_x + usable * 0.26, face_y + offset + 2), fill="#aebd9c", width=1)
    draw.line((center - 8, 286, center + 8, 286), fill="#554334", width=2)
    draw.line((center, 281, center, 291), fill="#554334", width=2)
    if not sharp:
        pixels = pixels.filter(ImageFilter.GaussianBlur(1.25))
    draw = ImageDraw.Draw(pixels)
    draw.text((26, 388), "FORM STUDY    /    SYNTHETIC CAPTURE", fill="#635342", font_size=14)
    draw.text((613, 388), f"{angle:03}° · {take}", anchor="ra", fill="#635342", font_size=14)
    return pixels


def sequence():
    selected = (307, 310, 329, 312, 311, 305)
    retakes = {1: 320, 2: 314, 3: 328, 4: 325}
    for slot, center in enumerate(selected):
        sharp = slot in (0, 2, 5)
        yield slot, "A", frame(slot * 60, center, sharp, "A"), [center, 286], sharp, slot in (0, 5)
        if slot in retakes:
            center = retakes[slot]
            sharp = slot != 2
            yield slot, "B", frame(slot * 60, center, sharp, "B"), [center, 286], sharp, False
