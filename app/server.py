"""
server.py — minimal web service wrapper so the renderer can run on Render.

Endpoints:
  GET  /                health check
  POST /render          start a job. multipart/form-data:
                          - config: JSON file or string (the per-crane config)
                          - photo, video, voiceover: uploaded files
                        returns {job_id, status_url}
  GET  /status/<id>     poll job status; when done, includes drive_url + caption text

Rendering runs in a background thread so the HTTP request returns immediately —
this avoids Render's request timeout on multi-minute encodes. State is kept in
memory + on disk; for a single-instance service that's sufficient. If you scale
to multiple instances, move job state to a shared store.

Run locally:   python server.py
On Render:     gunicorn -w 1 -b 0.0.0.0:$PORT server:app   (1 worker; see notes)
"""

import json
import os
import threading
import traceback
import uuid

from flask import Flask, request, jsonify

import run_job_lib as J  # thin importable wrapper around the pipeline

app = Flask(__name__)

JOBS = {}  # job_id -> {status, message, drive_url, outputs}
BASE = os.environ.get("WORK_ROOT", os.path.join(os.getcwd(), "_jobs"))
os.makedirs(BASE, exist_ok=True)


def _run_async(job_id, job_dir, cfg):
    JOBS[job_id] = {"status": "rendering", "message": "Rendering slides and video"}
    try:
        result = J.run_pipeline(cfg, job_dir, do_captions=True, do_upload=True)
        JOBS[job_id] = {"status": "done", **result}
    except Exception as e:
        JOBS[job_id] = {
            "status": "error",
            "message": str(e),
            "trace": traceback.format_exc()[-1500:],
        }


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "crane-render"})


@app.post("/render")
def render():
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(BASE, job_id)
    os.makedirs(os.path.join(job_dir, "assets"), exist_ok=True)

    # config can arrive as a file or a string field
    if "config" in request.files:
        cfg = json.load(request.files["config"])
    elif "config" in request.form:
        cfg = json.loads(request.form["config"])
    else:
        return jsonify({"error": "missing config"}), 400

    # save uploaded assets — photo and video always required.
    for field in ("photo", "video"):
        if field not in request.files:
            return jsonify({"error": f"missing file: {field}"}), 400
        f = request.files[field]
        dest = os.path.join(job_dir, "assets", f.filename)
        f.save(dest)
        cfg[field] = f.filename

    # Voiceover is required only in "file" mode; in "elevenlabs" mode it's
    # generated from cfg["script"], so no upload is needed.
    if cfg.get("voiceover_source", "file") != "elevenlabs":
        if "voiceover" not in request.files:
            return jsonify({"error": "missing file: voiceover (or set voiceover_source=elevenlabs with a script)"}), 400
        f = request.files["voiceover"]
        dest = os.path.join(job_dir, "assets", f.filename)
        f.save(dest)
        cfg["voiceover"] = f.filename

    # optional per-ratio photos for better vertical/square framing
    for field in ("photo_9x16", "photo_1x1", "photo_16x9"):
        if field in request.files:
            f = request.files[field]
            dest = os.path.join(job_dir, "assets", f.filename)
            f.save(dest)
            cfg[field] = f.filename

    cfg["_assets_dir"] = os.path.join(job_dir, "assets")
    threading.Thread(target=_run_async, args=(job_id, job_dir, cfg),
                     daemon=True).start()

    return jsonify({
        "job_id": job_id,
        "status_url": f"/status/{job_id}",
    })


@app.get("/status/<job_id>")
def status(job_id):
    info = JOBS.get(job_id)
    if not info:
        return jsonify({"status": "unknown"}), 404
    return jsonify(info)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
