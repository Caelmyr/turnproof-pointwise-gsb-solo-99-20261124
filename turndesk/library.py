"""Store editable turntables, immutable captures, and sealed proofs."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from shutil import rmtree
from threading import RLock
from uuid import uuid4

from werkzeug.exceptions import NotFound

from image_lab.validation import Conflict, Invalid, boolean, integer, text, timestamp

from . import demo, inspection, photos, proofs


KEY = re.compile(r"[0-9a-f]{16}")
ANGLE_COUNTS = (6, 8, 12, 18, 24)
MAX_PER_SLOT = 3
MAX_CAPTURE_BYTES = 160 * 1024 * 1024


def key(value):
    if not isinstance(value, str) or KEY.fullmatch(value) is None:
        raise NotFound("找不到该工程、照片或封存稿。")
    return value


def save(path, obj):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read(path):
    try:
        return json.loads(path.read_bytes())
    except FileNotFoundError:
        raise NotFound("找不到该工程、照片或封存稿。") from None


def revision(record, value):
    if integer(value, "修订号", 1) != record["revision"]:
        raise Conflict("工作台已在另一处更新，请重新打开。")


def slot_at(record, index):
    return record["slots"][integer(index, "台位", 0, len(record["slots"]) - 1)]


def find_capture(record, identifier):
    key(identifier)
    for capture in record["captures"]:
        if capture["id"] == identifier:
            return capture
    raise NotFound("这张照片不在该工程中。")


class Library:
    def __init__(self, root):
        self.root = Path(root) / "turntables"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def folder(self, identifier):
        return self.root / key(identifier)

    def record(self, identifier):
        return read(self.folder(identifier) / "project.json")

    def list(self):
        entries = []
        for path in self.root.glob("[0-9a-f]*/project.json"):
            record = read(path)
            entries.append({name: record[name] for name in ("id", "title", "created", "synthetic")})
        return sorted(entries, key=lambda item: item["created"], reverse=True)

    def create(self, title, count, synthetic=False):
        count = integer(count, "台位数量")
        if count not in ANGLE_COUNTS:
            raise Invalid("台位数请选择 6、8、12、18 或 24。")
        identifier = uuid4().hex[:16]
        target = self.folder(identifier)
        staging = self.root / ("." + identifier)
        staging.mkdir()
        try:
            (staging / "captures").mkdir()
            (staging / "proofs").mkdir()
            record = {
                "id": identifier, "title": text(title, "工程名称", 95, empty=False), "created": timestamp(),
                "synthetic": synthetic, "revision": 1,
                "slots": [{"angle": index * 360 // count, "selected": None, "locked": False} for index in range(count)],
                "captures": [],
            }
            if synthetic:
                for index, label, image, mark, preferred, locked in demo.sequence():
                    capture = self._add(staging, record, index, image, f"TAKE {label}", origin={"synthetic": True})
                    capture.update(mark=mark, preferred=preferred)
                    if locked:
                        record["slots"][index]["locked"] = True
            save(staging / "project.json", record)
            staging.rename(target)
        finally:
            if staging.exists():
                rmtree(staging)
        return record

    def _add(self, folder, record, index, image, label, origin):
        slot = slot_at(record, index)
        count = Counter(capture["slot"] for capture in record["captures"])
        if count[index] >= MAX_PER_SLOT:
            raise Invalid("每个台位最多保留三张原片或补拍。")
        raw = photos.png(image)
        if sum(capture["bytes"] for capture in record["captures"]) + len(raw) > MAX_CAPTURE_BYTES:
            raise Invalid("工程正向 PNG 总量超过 160 MiB。")
        identifier = uuid4().hex[:16]
        original = folder / "captures" / (identifier + ".png")
        preview = folder / "captures" / (identifier + ".jpg")
        temporary_preview = photos.thumbnail(image)
        try:
            original.write_bytes(raw)
            preview.write_bytes(temporary_preview)
        except OSError:
            original.unlink(missing_ok=True)
            preview.unlink(missing_ok=True)
            raise
        capture = {
            "id": identifier, "slot": index, "name": label, "width": image.width, "height": image.height,
            "sha256": sha256(raw).hexdigest(), "bytes": len(raw), "mark": None, "preferred": False, "origin": origin,
        }
        record["captures"].append(capture)
        if slot["selected"] is None:
            slot["selected"] = identifier
        return capture

    def add(self, identifier, expected, index, image, label, origin=None):
        with self.lock:
            record = self.record(identifier)
            revision(record, expected)
            index = integer(index, "台位", 0, len(record["slots"]) - 1)
            name = (label.strip()[:94] or "原片") if isinstance(label, str) else "原片"
            folder = self.folder(identifier)
            capture = self._add(folder, record, index, image, name, origin)
            try:
                self._update(folder, record)
            except OSError:
                for suffix in (".png", ".jpg"):
                    (folder / "captures" / (capture["id"] + suffix)).unlink(missing_ok=True)
                raise
        return {"project": record, "capture": capture}

    def _update(self, folder, record):
        record["revision"] += 1
        save(folder / "project.json", record)
        return record

    def edit_capture(self, identifier, expected, capture_key, patch):
        with self.lock:
            record = self.record(identifier)
            revision(record, expected)
            capture = find_capture(record, capture_key)
            if "mark" in patch:
                capture["mark"] = inspection.checked_mark(patch["mark"], capture)
            if "preferred" in patch:
                capture["preferred"] = boolean(patch["preferred"], "细节首选")
            return self._update(self.folder(identifier), record)

    def edit_slot(self, identifier, expected, index, patch):
        with self.lock:
            record = self.record(identifier)
            revision(record, expected)
            slot = slot_at(record, index)
            if "selected" in patch:
                capture = find_capture(record, patch["selected"])
                if capture["slot"] != index:
                    raise Invalid("只能采用同一台位的原片。")
                if slot["locked"] and slot["selected"] != capture["id"]:
                    raise Invalid("先解锁这个台位再替换原片。")
                slot["selected"] = capture["id"]
            if "locked" in patch:
                locked = boolean(patch["locked"], "锁定台位")
                if locked and not slot["selected"]:
                    raise Invalid("台位有已采用原片时才能锁定。")
                slot["locked"] = locked
            return self._update(self.folder(identifier), record)

    def capture_path(self, identifier, capture, thumbnail=False):
        find_capture(self.record(identifier), capture)
        return self.folder(identifier) / "captures" / (capture + (".jpg" if thumbnail else ".png"))

    def contact(self, identifier):
        record = self.record(identifier)
        folder = self.folder(identifier)
        return proofs.contact_sheet(inspection.manual_frames(record), lambda photo: folder / "captures" / (photo + ".png"))

    def proof_list(self, identifier):
        self.record(identifier)
        items = []
        for path in self.folder(identifier).glob("proofs/[0-9a-f]*/proof.json"):
            proof = read(path)
            items.append({name: proof[name] for name in ("id", "title", "created", "source_revision")})
        return sorted(items, key=lambda item: item["created"], reverse=True)

    def proof(self, identifier, proof):
        self.record(identifier)
        folder = self.folder(identifier) / "proofs" / key(proof)
        return folder, read(folder / "proof.json")

    def create_proof(self, identifier, expected, label):
        with self.lock:
            record = self.record(identifier)
            revision(record, expected)
            folder = self.folder(identifier)
            proof = uuid4().hex[:16]
            title = text(label or "旋转检查稿", "封存名称", 95, empty=False)
            root = folder / "proofs"
            staging = root / ("." + proof)
            staging.mkdir()
            try:
                result = proofs.write(staging, proof, title, record, lambda photo: folder / "captures" / (photo + ".png"))
                staging.rename(root / proof)
            finally:
                if staging.exists():
                    rmtree(staging)
            return result
