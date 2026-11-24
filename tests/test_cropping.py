"""Unit tests for the shared 16:9 crop window planner."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from turndesk import cropping
from turndesk.library import Library


def slot_frame(identifier, width, height, mark, slot=0, angle=0):
    return {
        "angle": angle, "locked": False,
        "frame": {"id": identifier, "name": identifier, "width": width, "height": height, "mark": list(mark)},
    }


def frames(pairs, width=400, height=300):
    return [
        slot_frame(f"f{i}", width, height, mark, slot=i, angle=i * 60)
        for i, mark in enumerate(pairs)
    ]


class AnchorPixelTest(unittest.TestCase):
    def test_half_pixel_rounding(self):
        # percent/100 * dim + 0.5 -> nearest, ties go up.
        self.assertEqual(cropping.anchor_pixel(0, 100), 0)
        self.assertEqual(cropping.anchor_pixel(100, 100), 99)
        self.assertEqual(cropping.anchor_pixel(50, 100), 50)
        self.assertEqual(cropping.anchor_pixel(25, 10), 3)  # 2.5 -> tie -> 3

    def test_band_clamps_to_crop_bounds(self):
        self.assertEqual(cropping._band_pixels(-5, 105, 100), (0, 99))
        # 10% of 200 -> center 20; band pixels with center in [10%, 30%] => 20..59
        self.assertEqual(cropping._band_pixels(10, 30, 200), (20, 59))


class PlanGeometryTest(unittest.TestCase):
    def test_largest_shared_window_and_same_crop_pixel(self):
        data = frames([(120, 200), (180, 210)], width=400, height=300)
        result = cropping.plan(data, 50, 50, 10)
        plan = result["plan"]
        # At 400x225 the two marks cannot share one crop anchor within +-10
        # points, so the planner shrinks to 288x162 (scale 18) and stays exact.
        self.assertEqual((plan["width"], plan["height"]), (288, 162))
        spots = set()
        for item in plan["frames"]:
            self.assertEqual((item["width"], item["height"]), (288, 162))
            self.assertTrue(0 <= item["x"] and item["x"] + 288 <= 400)
            self.assertTrue(0 <= item["y"] and item["y"] + 162 <= 300)
            frame = data[item["slot"]]["frame"]
            spots.add((frame["mark"][0] - item["x"], frame["mark"][1] - item["y"]))
        self.assertEqual(spots, {tuple(plan["anchor"])})

    def test_vertical_snap_to_nearest_pixel(self):
        data = frames([(100, 100), (100, 110)], width=320, height=240)
        plan = cropping.plan(data, 31.25, 25, 50)["plan"]
        # Largest fit is 320x180; 25% of 180 -> 45 exactly (nearest pixel).
        self.assertEqual((plan["width"], plan["height"]), (320, 180))
        self.assertEqual(plan["anchor"][1], 45)
        self.assertEqual(plan["frames"][0]["y"], 100 - 45)
        self.assertEqual(plan["frames"][1]["y"], 110 - 45)

    def test_tolerance_zero_blocks_when_marks_diverge(self):
        data = frames([(50, 100), (350, 100)], width=400, height=300)
        blocked = cropping.plan(data, 50, 50, 0)["blocked"]
        self.assertEqual(blocked["kind"], "no_window")
        # With a generous allowance the same pair becomes feasible at some size.
        plan = cropping.plan(data, 50, 50, 45)["plan"]
        self.assertEqual(plan["height"] * 16, plan["width"] * 9)

    def test_closest_anchor_wins_on_ties_of_size(self):
        # One frame pins the anchor to crop pixel 0; the request at 50% must
        # be pushed to the nearest feasible pixel rather than failing.
        data = frames([(0, 100), (200, 100)], width=400, height=300)
        plan = cropping.plan(data, 50, 50, 50)["plan"]
        self.assertEqual(plan["anchor"][0], 0)
        self.assertEqual(plan["frames"][0]["x"], 0)
        # The other frame's window stays inside its own source.
        self.assertTrue(plan["frames"][1]["x"] >= 0)
        self.assertTrue(plan["frames"][1]["x"] + plan["width"] <= 400)

    def test_anchor_is_nearest_to_request_inside_feasible_band(self):
        # At the chosen size both frames leave a wide feasible anchor band;
        # the planner must land on the pixel nearest the requested landing.
        data = frames([(120, 150), (280, 150)], width=400, height=300)
        for request_percent in (10.0, 50.0, 90.0):
            plan = cropping.plan(data, request_percent, 50, 50)["plan"]
            width = plan["width"]
            requested = cropping.anchor_pixel(request_percent, width)
            lows, highs = [], []
            for slot in data:
                mark_x = slot["frame"]["mark"][0]
                lows.append(max(0, width - 400 + mark_x))
                highs.append(min(width - 1, mark_x))
            band_low, band_high = cropping._band_pixels(0, 100, width)
            expect = min(min(highs + [band_high]), max(max(lows + [band_low]), requested))
            self.assertEqual(plan["anchor"][0], expect)
        # A request exactly inside the feasible band is honored pixel-exact.
        centered = cropping.plan(data, 50, 50, 50)["plan"]
        self.assertEqual(centered["anchor"][0],
                         cropping.anchor_pixel(50, centered["width"]))

    def test_size_shrinks_until_feasible(self):
        # Mark pinned at the left edge of a narrow frame forces a smaller window.
        narrow = slot_frame("n", 120, 300, (0, 150), slot=0, angle=0)
        wide = slot_frame("w", 400, 300, (200, 150), slot=1, angle=60)
        plan = cropping.plan([narrow, wide], 50, 50, 50)["plan"]
        self.assertEqual(plan["width"], 112)  # scale 7: 16*7=112 <= 120
        self.assertEqual(plan["height"], 63)
        for item in plan["frames"]:
            self.assertTrue(item["x"] >= 0 and item["x"] + item["width"] <=
                            (120 if item["slot"] == 0 else 400))

    def test_missing_mark_is_reported(self):
        good = slot_frame("g", 400, 300, (10, 10), slot=0)
        bare = {"angle": 60, "locked": False,
                "frame": {"id": "b", "name": "b", "width": 400, "height": 300, "mark": None}}
        blocked = cropping.plan([good, bare], 50, 50, 5)["blocked"]
        self.assertEqual(blocked["kind"], "incomplete")
        self.assertEqual(blocked["missing_marks"][0]["angle"], 60)
        self.assertEqual(blocked["missing_marks"][0]["capture"], "b")

    def test_missing_frame_is_reported(self):
        good = slot_frame("g", 400, 300, (10, 10), slot=0)
        empty = {"angle": 60, "locked": False, "frame": None}
        blocked = cropping.plan([good, empty], 50, 50, 5)["blocked"]
        self.assertEqual(blocked["missing_frames"], [60])

    def test_no_window_diagnostic_names_limiting_frames(self):
        data = frames([(10, 10), (390, 290)], width=400, height=300)
        blocked = cropping.plan(data, 50, 50, 0)["blocked"]
        self.assertEqual(blocked["kind"], "no_window")
        self.assertEqual(blocked["at_largest_window"]["window"], [400, 225])
        self.assertIsNone(blocked["at_largest_window"]["image_intersection"])
        details = blocked["at_largest_window"]["details"]
        self.assertEqual(len(details), 2)
        self.assertTrue(all(item["anchor_x_range"] for item in details))
        self.assertTrue(any(not item["within_tolerance"] for item in details))


class StalenessTest(unittest.TestCase):
    def test_plan_invalidates_when_mark_or_selection_changes(self):
        data = frames([(100, 100), (120, 110)], width=400, height=300)
        record = {
            "slots": [{"angle": 0, "selected": "f0", "locked": False},
                      {"angle": 60, "selected": "f1", "locked": False}],
            "captures": [item["frame"] for item in data],
        }
        plan = cropping.plan(data, 50, 50, 5)["plan"]
        self.assertTrue(cropping.is_current(plan, record))
        record["captures"][0]["mark"] = [101, 100]
        self.assertFalse(cropping.is_current(plan, record))
        record["captures"][0]["mark"] = [100, 100]
        self.assertTrue(cropping.is_current(plan, record))
        record["slots"][1]["selected"] = "f0"
        self.assertFalse(cropping.is_current(plan, record))


class LibraryFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = Library(Path(self.temp.name))
        self.project = self.library.create("裁切测试", 6)
        self.images = []
        colors = [(180, 90, 60), (60, 120, 180)]
        for index in range(6):
            image = Image.new("RGB", (320, 240), colors[index % 2])
            self.images.append(image)
            result = self.library.add(self.project["id"], self.project["revision"],
                                      index, image, f"TAKE {index}")
            self.project = result["project"]
            capture = result["capture"]
            self.project = self.library.edit_capture(
                self.project["id"], self.project["revision"], capture["id"],
                {"mark": [150 + index, 160]})

    def tearDown(self):
        self.temp.cleanup()

    def test_proposal_save_preview_and_invalidation(self):
        proposal = self.library.crop_proposal(self.project["id"], self.project["revision"], 50, 60, 8)
        self.assertIn("plan", proposal)
        saved = self.library.save_crop_plan(self.project["id"], self.project["revision"], proposal["plan"])
        self.project = saved
        self.assertIsNotNone(self.project["crop_plan"])
        first = self.library.crop_png(self.project["id"], 0)
        with Image.open(__import__("io").BytesIO(first)) as image:
            self.assertEqual(image.size, (saved["crop_plan"]["width"], saved["crop_plan"]["height"]))
        # Re-marking one base point clears the confirmed plan.
        capture_id = self.project["slots"][2]["selected"]
        self.project = self.library.edit_capture(
            self.project["id"], self.project["revision"], capture_id, {"mark": [170, 150]})
        self.assertIsNone(self.project["crop_plan"])

    def test_seal_bundle_matches_confirmed_crops(self):
        proposal = self.library.crop_proposal(self.project["id"], self.project["revision"], 50, 60, 8)
        self.project = self.library.save_crop_plan(
            self.project["id"], self.project["revision"], proposal["plan"])
        plan = self.project["crop_plan"]
        proof = self.library.create_proof(self.project["id"], self.project["revision"], "裁窗封存稿")
        self.assertEqual(proof["crop_plan"]["anchor"], plan["anchor"])
        folder = self.library.folder(self.project["id"]) / "proofs" / proof["id"]
        import io
        import zipfile
        with zipfile.ZipFile(folder / "spin.zip") as archive:
            names = archive.namelist()
            self.assertIn("spin.json", names)
            self.assertEqual(sum(name.startswith("frames/") for name in names), 6)
            self.assertEqual(sum(name.startswith("sources/") for name in names), 6)
            for entry in proof["frames"]:
                with Image.open(io.BytesIO(archive.read(entry["file"]))) as image:
                    self.assertEqual(image.size, (plan["width"], plan["height"]))
                # The delivered PNG must be byte-identical to the confirmed crop.
                self.assertEqual(
                    archive.read(entry["file"]),
                    self.library.crop_png(self.project["id"], proof["frames"].index(entry)))
        # On-disk sealed frame matches the ZIP member and the live crop.
        for index, entry in enumerate(proof["frames"]):
            self.assertEqual((folder / entry["file"]).read_bytes(),
                             self.library.crop_png(self.project["id"], index))


if __name__ == "__main__":
    unittest.main()
