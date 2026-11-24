"""Serve booth capture reviews and the integrated photo preparation workspace."""

from io import BytesIO
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file

from image_lab import create_app as create_preparation
from image_lab.validation import Invalid, object_value

from . import inspection, photos
from .library import Library, slot_at


def body():
    return object_value(request.get_json(silent=True), "转台操作")


def create_app(root):
    app = create_preparation(root / "prepare")
    library = Library(root)
    desk = Blueprint("turndesk", __name__, url_prefix="/turndesk")

    @app.get("/")
    def home():
        return render_template("turnproof.html")

    @desk.get("/health")
    def health():
        return jsonify(status="ready", service="turnproof")

    @desk.get("/projects")
    def projects():
        return jsonify(library.list())

    @desk.post("/projects")
    def create():
        value = body()
        return jsonify(library.create(value.get("title"), value.get("count"))), 201

    @desk.post("/demo")
    def demo():
        return jsonify(library.create("合成样片 · 陶瓷包装六面", 6, synthetic=True)), 201

    @desk.get("/projects/<project>")
    def open_project(project):
        return jsonify(library.record(project))

    @desk.post("/projects/<project>/captures")
    def upload(project):
        source = request.files.get("image")
        if source is None or not source.filename:
            raise Invalid("请选择原片或补拍。")
        photo = photos.decode(source.stream.read(photos.MAX_UPLOAD + 1))
        title = Path(source.filename).stem
        return jsonify(library.add(project, request.form.get("revision"), request.form.get("slot"), photo, title)), 201

    @desk.post("/projects/<project>/prepared")
    def prepared(project):
        value = body()
        prep_project, result = value.get("project"), value.get("result")
        if not isinstance(prep_project, str) or not isinstance(result, str):
            raise Invalid("请选择已生成的照片准备结果。")
        preparation = app.extensions["results"]
        if preparation.metadata(prep_project, result)["stale"]:
            raise Invalid("请重新计算照片准备结果。")
        with preparation.image_path(prep_project, "image", result).open("rb") as source:
            photo = photos.decode(source.read(photos.MAX_UPLOAD + 1))
        origin = {"preparation_project": prep_project, "preparation_result": result}
        return jsonify(library.add(project, value.get("revision"), value.get("slot"), photo, "照片准备结果", origin)), 201

    @desk.patch("/projects/<project>/captures/<capture>")
    def edit_capture(project, capture):
        value = body()
        return jsonify(library.edit_capture(project, value.get("revision"), capture, value))

    @desk.patch("/projects/<project>/slots/<int:index>")
    def edit_slot(project, index):
        value = body()
        return jsonify(library.edit_slot(project, value.get("revision"), index, value))

    @desk.get("/projects/<project>/captures/<capture>/source.png")
    def source(project, capture):
        return send_file(library.capture_path(project, capture), mimetype="image/png",
                         download_name=capture + ".png", as_attachment="download" in request.args)

    @desk.get("/projects/<project>/captures/<capture>/thumb.jpg")
    def thumb(project, capture):
        return send_file(library.capture_path(project, capture, thumbnail=True), mimetype="image/jpeg")

    @desk.get("/projects/<project>/captures/<capture>/exposure")
    def exposure(project, capture):
        return jsonify(photos.exposure(library.capture_path(project, capture)))

    @desk.get("/projects/<project>/slots/<int:index>/transition")
    def transition(project, index):
        record = library.record(project)
        slot_at(record, index)
        return jsonify(inspection.manual_transition(record, index))

    @desk.get("/projects/<project>/contact.png")
    def contact(project):
        return send_file(BytesIO(library.contact(project)), mimetype="image/png", max_age=0,
                         download_name="turnproof-contact.png", as_attachment="download" in request.args)

    @desk.route("/projects/<project>/proofs", methods=["GET", "POST"])
    def proofs(project):
        if request.method == "GET":
            return jsonify(library.proof_list(project))
        value = body()
        return jsonify(library.create_proof(project, value.get("revision"), value.get("title"))), 201

    @desk.get("/projects/<project>/proofs/<proof>")
    def open_proof(project, proof):
        return jsonify(library.proof(project, proof)[1])

    @desk.get("/projects/<project>/proofs/<proof>/contact.png")
    def proof_contact(project, proof):
        folder, _ = library.proof(project, proof)
        return send_file(folder / "contact.png", mimetype="image/png",
                         download_name="turnproof-contact.png", as_attachment="download" in request.args)

    @desk.get("/projects/<project>/proofs/<proof>/spin.zip")
    def proof_bundle(project, proof):
        folder, _ = library.proof(project, proof)
        return send_file(folder / "spin.zip", mimetype="application/zip",
                         download_name="turnproof-spin.zip", as_attachment=True)

    app.register_blueprint(desk)
    return app
