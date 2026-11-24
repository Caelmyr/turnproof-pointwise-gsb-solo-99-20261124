"""End-to-end HTTP flow for the shared 16:9 crop delivery."""

import io
import json
import tempfile
import unittest
import zipfile
import hashlib
from pathlib import Path

from PIL import Image

from turndesk.web import create_app


class CropWebFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_full_crop_review_and_seal_flow(self):
        created = self.client.post("/turndesk/demo").get_json()
        project_id = created["id"]
        record = self.client.get(f"/turndesk/projects/{project_id}").get_json()
        # The synthetic sequence marks every adopted base point already.
        self.assertTrue(all(c["mark"] for c in record["captures"] if any(
            s["selected"] == c["id"] for s in record["slots"])))

        # 1. Proposal: the six demo base points share a window within tolerance.
        response = self.client.post(f"/turndesk/projects/{project_id}/crop-plan", json={
            "revision": record["revision"], "anchor_x": 50, "anchor_y": 68, "tolerance": 8})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn("plan", body)

        # 2. Persist the confirmed plan.
        saved = self.client.put(f"/turndesk/projects/{project_id}/crop-plan", json={
            "revision": record["revision"], "plan": body["plan"]})
        self.assertEqual(saved.status_code, 200)
        project = saved.get_json()
        plan = project["crop_plan"]
        self.assertEqual(plan["width"] * 9, plan["height"] * 16)

        # 3. Every live crop preview is the exact shared size and lies in-frame.
        for slot in range(len(record["slots"])):
            png = self.client.get(f"/turndesk/projects/{project_id}/slots/{slot}/crop.png")
            self.assertEqual(png.status_code, 200)
            with Image.open(io.BytesIO(png.data)) as image:
                self.assertEqual(image.size, (plan["width"], plan["height"]))

        # 4. Re-marking a base point invalidates the plan but keeps the photo.
        capture_id = record["slots"][0]["selected"]
        original_mark = next(c for c in record["captures"] if c["id"] == capture_id)["mark"]
        updated = self.client.patch(f"/turndesk/projects/{project_id}/captures/{capture_id}", json={
            "revision": project["revision"], "mark": [original_mark[0] + 1, original_mark[1]]})
        self.assertIsNone(updated.get_json()["crop_plan"])

        # Restore the mark and re-confirm the plan before sealing.
        project = updated.get_json()
        self.client.patch(f"/turndesk/projects/{project_id}/captures/{capture_id}", json={
            "revision": project["revision"], "mark": original_mark})
        project = self.client.get(f"/turndesk/projects/{project_id}").get_json()
        proposal = self.client.post(f"/turndesk/projects/{project_id}/crop-plan", json={
            "revision": project["revision"], "anchor_x": 50, "anchor_y": 68, "tolerance": 5}).get_json()
        project = self.client.put(f"/turndesk/projects/{project_id}/crop-plan", json={
            "revision": project["revision"], "plan": proposal["plan"]}).get_json()
        plan = project["crop_plan"]

        # 5. Seal: reopened proof carries the same crop geometry.
        proof = self.client.post(f"/turndesk/projects/{project_id}/proofs", json={
            "revision": project["revision"], "title": "16:9 交付稿"}).get_json()
        reopened = self.client.get(f"/turndesk/projects/{project_id}/proofs/{proof['id']}").get_json()
        self.assertEqual(reopened["crop_plan"]["anchor"], plan["anchor"])
        self.assertEqual(len(reopened["frames"]), len(record["slots"]))

        # 6. Sealed crop endpoint matches the live preview and the ZIP member.
        first_angle = reopened["frames"][0]["angle"]
        sealed_png = self.client.get(
            f"/turndesk/projects/{project_id}/proofs/{proof['id']}/frames/{first_angle}/crop.png").data
        live_png = self.client.get(f"/turndesk/projects/{project_id}/slots/0/crop.png").data
        self.assertEqual(sealed_png, live_png)

        bundle = self.client.get(f"/turndesk/projects/{project_id}/proofs/{proof['id']}/spin.zip")
        with zipfile.ZipFile(io.BytesIO(bundle.data)) as archive:
            spin = json.loads(archive.read("spin.json"))
            import hashlib
            for entry in spin["frames"]:
                delivered = archive.read(entry["file"])
                with Image.open(io.BytesIO(delivered)) as image:
                    self.assertEqual(image.size, (plan["width"], plan["height"]))
                self.assertTrue(entry["source_file"].startswith("sources/"))
                self.assertEqual(entry["png_sha256"], hashlib.sha256(delivered).hexdigest())
                # The original evidence is bundled alongside each crop.
                self.assertEqual(hashlib.sha256(archive.read(entry["source_file"])).hexdigest(),
                                 entry["source_sha256"])

        # 7. Source fallback endpoint serves the untouched original capture.
        source = self.client.get(
            f"/turndesk/projects/{project_id}/proofs/{proof['id']}/frames/{first_angle}/source.png")
        self.assertEqual(source.status_code, 200)
        with Image.open(io.BytesIO(source.data)) as image:
            self.assertEqual(image.size, tuple(reopened["frames"][0]["source_size"]))

    def test_missing_mark_blocks_without_touching_photos(self):
        created = self.client.post("/turndesk/demo").get_json()
        project_id = created["id"]
        record = self.client.get(f"/turndesk/projects/{project_id}").get_json()
        capture_id = record["slots"][3]["selected"]
        updated = self.client.patch(f"/turndesk/projects/{project_id}/captures/{capture_id}", json={
            "revision": record["revision"], "mark": None}).get_json()
        response = self.client.post(f"/turndesk/projects/{project_id}/crop-plan", json={
            "revision": updated["revision"], "anchor_x": 50, "anchor_y": 68, "tolerance": 5})
        blocked = response.get_json()["blocked"]
        self.assertEqual(blocked["kind"], "incomplete")
        self.assertEqual(blocked["missing_marks"][0]["angle"], record["slots"][3]["angle"])
        # The capture itself remains selected and available.
        again = self.client.get(f"/turndesk/projects/{project_id}").get_json()
        self.assertEqual(again["slots"][3]["selected"], capture_id)

    def test_revision_conflict_is_rejected(self):
        created = self.client.post("/turndesk/demo").get_json()
        response = self.client.post(f"/turndesk/projects/{created['id']}/crop-plan", json={
            "revision": created["revision"] + 99, "anchor_x": 50, "anchor_y": 68, "tolerance": 5})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
