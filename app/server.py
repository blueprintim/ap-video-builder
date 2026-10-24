"""
server.py — minimal web service wrapper so the renderer can run on Render.

Endpoints:
  GET  /                health check (open: Render's probe carries no token)
  POST /render          start a job. multipart/form-data:
                          - config: JSON file or string (the per-crane config)
                          - photo, video, voiceover: uploaded files
                        returns {job_id, status_url}
  GET  /status/<id>     poll job status; when done, includes drive_url + caption text

Every route except GET / needs `Authorization: Bearer <CRANE_API_TOKEN>`. The
service spends money (ElevenLabs, Anthropic) and publishes to Drive, so it must
never be callable anonymously. With no token configured it refuses everything
(503) rather than running open.

Uploads are never saved under the client's filename. Each file is stored under a
fixed name for its field (photo.jpg, video.mp4, ...) and the config is stripped
of anything that could point the pipeline at another path.

Rendering runs in a background thread so the HTTP request returns immediately —
this avoids Render's request timeout on multi-minute encodes. State is kept in
memory + on disk; for a single-instance service that's sufficient. If you scale
to multiple instances, move job state to a shared store.

Limits (all overridable from the environment; see README):
  MAX_UPLOAD_MB      total request size            (default 400)
  MAX_CONFIG_KB      the config JSON               (default 256)
  MAX_SCRIPT_CHARS   the ElevenLabs script         (default 5000)
  MAX_ACTIVE_JOBS    renders running at once       (default 1)
  MAX_PENDING_JOBS   running + waiting in the queue (default 6); beyond this
                     POST /render answers 503 + Retry-After

Run locally:   python server.py
On Render:     see the Dockerfile CMD (1 worker process, a few threads)
"""

import hashlib
import hmac
import json
import os
import re
import shutil
import threading
import traceback
import uuid

from flask import Flask, request, jsonify

import run_job_lib as J  # thin importable wrapper around the pipeline

app = Flask(__name__)

JOBS = {}  # job_id -> {status, message, drive_url, outputs}
MAX_JOBS_REMEMBERED = 500
BASE = os.environ.get("WORK_ROOT", os.path.join(os.getcwd(), "_jobs"))
os.makedirs(BASE, exist_ok=True)


def _int_env(name, default):
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


MAX_UPLOAD_MB = _int_env("MAX_UPLOAD_MB", 400)
MAX_CONFIG_BYTES = _int_env("MAX_CONFIG_KB", 256) * 1024
MAX_SCRIPT_CHARS = _int_env("MAX_SCRIPT_CHARS", 5000)
MAX_ACTIVE_JOBS = _int_env("MAX_ACTIVE_JOBS", 1)
MAX_PENDING_JOBS = _int_env("MAX_PENDING_JOBS", 6)

# Werkzeug enforces this while it parses the body, so an oversize upload is cut
# off with a 413 instead of being buffered. (Auth runs first: see below.)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# --------------------------------------------------------------------------
# Auth — one shared bearer token on every route except the health check
# --------------------------------------------------------------------------

MIN_TOKEN_CHARS = 24  # a guessable token is no token; generate 32+ random chars


def _digest(value):
    return hashlib.sha256(value.encode()).digest()


@app.before_request
def _require_token():
    # Render's health probe is a plain GET / with no credentials.
    if request.path == "/" and request.method in ("GET", "HEAD"):
        return None

    expected = os.environ.get("CRANE_API_TOKEN", "").strip()
    if len(expected) < MIN_TOKEN_CHARS:
        app.logger.error(
            "CRANE_API_TOKEN is unset or shorter than %d characters — "
            "refusing every request until it is set", MIN_TOKEN_CHARS)
        return jsonify({"error": "auth_not_configured"}), 503

    m = re.match(r"^Bearer\s+(.+)$", request.headers.get("Authorization", ""), re.I)
    presented = m.group(1).strip() if m else ""
    # Hash both sides so the comparison is constant-time and length-blind.
    if not presented or not hmac.compare_digest(_digest(presented), _digest(expected)):
        resp = jsonify({"error": "unauthorized"})
        resp.status_code = 401
        resp.headers["WWW-Authenticate"] = "Bearer"
        return resp
    return None


@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"error": "upload_too_large", "max_mb": MAX_UPLOAD_MB}), 413


# --------------------------------------------------------------------------
# Upload and config hygiene
# --------------------------------------------------------------------------

# Extensions we keep (lower-cased) when naming a saved asset. Anything else is
# saved with no extension — Pillow and ffmpeg identify files by content, so the
# extension is a convenience, never something the client controls freely.
_ASSET_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
}

# Config keys that name files. Real values come only from the uploads below; a
# client-supplied value (an absolute path, "../x") would be read by the pipeline.
_ASSET_KEYS = ("photo", "video", "voiceover",
               "photo_9x16", "photo_1x1", "photo_16x9", "assets")

_VOICE_ID_RE = re.compile(r"[A-Za-z0-9]{8,64}")


class _BadRequest(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _asset_name(field, filename):
    """photo.jpg, video.mp4, ... — the client's filename is only consulted for
    a whitelisted extension; none of its path or name ever reaches the disk."""
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = os.path.splitext(base)[1].lower()
    return field + (ext if ext in _ASSET_EXTS else "")


def _save_asset(field, assets_dir):
    f = request.files.get(field)
    if f is None or not f.filename:
        return None
    name = _asset_name(field, f.filename)
    f.save(os.path.join(assets_dir, name))
    return name


def _safe_id(value, fallback):
    """The id becomes a Drive folder name and part of each output filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip(".-")[:80]
    return cleaned or fallback


def _load_config():
    if "config" in request.files:
        raw = request.files["config"].stream.read(MAX_CONFIG_BYTES + 1)
    elif "config" in request.form:
        raw = request.form["config"].encode()
    else:
        raise _BadRequest("missing config")
    if len(raw) > MAX_CONFIG_BYTES:
        raise _BadRequest("config too large", 413)
    try:
        cfg = json.loads(raw)
    except ValueError:
        raise _BadRequest("config is not valid JSON")
    if not isinstance(cfg, dict):
        raise _BadRequest("config must be a JSON object")
    return cfg


def _clean_config(cfg, job_id):
    # "_"-prefixed keys are the pipeline's own (_photo_path_9x16, _assets_dir,
    # ...); a client that sets them could redirect a file read. The shipped
    # example config only uses them for notes (_comment), which are safe to drop.
    for key in [k for k in cfg if k.startswith("_")]:
        del cfg[key]
    for key in _ASSET_KEYS:
        cfg.pop(key, None)

    cfg["id"] = _safe_id(cfg.get("id"), job_id)

    voice_id = cfg.get("voice_id")
    if voice_id not in (None, "") and not (
            isinstance(voice_id, str) and _VOICE_ID_RE.fullmatch(voice_id)):
        raise _BadRequest("invalid voice_id")  # it is placed in an API URL path

    script = cfg.get("script")
    if script is not None and (not isinstance(script, str) or len(script) > MAX_SCRIPT_CHARS):
        raise _BadRequest(f"script must be text of at most {MAX_SCRIPT_CHARS} characters")
    return cfg


def _prepare_job(job_id, job_dir):
    """Validate the request and stage its files. Returns the pipeline config."""
    cfg = _clean_config(_load_config(), job_id)

    assets_dir = os.path.join(job_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # photo and video are always required.
    for field in ("photo", "video"):
        name = _save_asset(field, assets_dir)
        if name is None:
            raise _BadRequest(f"missing file: {field}")
        cfg[field] = name

    # Voiceover is required only in "file" mode; in "elevenlabs" mode it's
    # generated from cfg["script"], so no upload is needed.
    if cfg.get("voiceover_source", "file") != "elevenlabs":
        name = _save_asset("voiceover", assets_dir)
        if name is None:
            raise _BadRequest(
                "missing file: voiceover (or set voiceover_source=elevenlabs with a script)")
        cfg["voiceover"] = name

    # optional per-ratio photos for better vertical/square framing
    for field in ("photo_9x16", "photo_1x1", "photo_16x9"):
        name = _save_asset(field, assets_dir)
        if name is not None:
            cfg[field] = name

    cfg["_assets_dir"] = assets_dir
    return cfg


# --------------------------------------------------------------------------
# Job queue — bounded, so a burst can't exhaust memory, CPU or the disk
# --------------------------------------------------------------------------

_render_slots = threading.BoundedSemaphore(MAX_ACTIVE_JOBS)
_pending = 0  # jobs running or waiting for a slot
_pending_lock = threading.Lock()


def _reserve_slot():
    global _pending
    with _pending_lock:
        if _pending >= MAX_PENDING_JOBS:
            return False
        _pending += 1
        return True


def _release_slot():
    global _pending
    with _pending_lock:
        _pending -= 1


def _remember(job_id, info):
    JOBS[job_id] = info
    while len(JOBS) > MAX_JOBS_REMEMBERED:
        JOBS.pop(next(iter(JOBS)), None)  # drop the oldest status entry


def _run_async(job_id, job_dir, cfg):
    try:
        with _render_slots:
            _remember(job_id, {"status": "rendering", "message": "Rendering slides and video"})
            try:
                result = J.run_pipeline(cfg, job_dir, do_captions=True, do_upload=True)
                _remember(job_id, {"status": "done", **result})
            except Exception as e:
                _remember(job_id, {
                    "status": "error",
                    "message": str(e),
                    "trace": traceback.format_exc()[-1500:],
                })
    finally:
        _release_slot()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/")
def health():
    return jsonify({"ok": True, "service": "crane-render"})


@app.post("/render")
def render():
    # Check capacity before reading the upload, so a full queue costs nothing.
    if not _reserve_slot():
        resp = jsonify({"error": "busy", "message": "Too many renders queued; retry shortly."})
        resp.status_code = 503
        resp.headers["Retry-After"] = "60"
        return resp

    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(BASE, job_id)
    try:
        cfg = _prepare_job(job_id, job_dir)
    except _BadRequest as e:
        _release_slot()
        shutil.rmtree(job_dir, ignore_errors=True)  # the empty dir this request just made
        return jsonify({"error": e.message}), e.status
    except BaseException:
        _release_slot()
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    # Visible to /status straight away, even while it waits for a free slot.
    _remember(job_id, {"status": "rendering", "message": "Queued: waiting for a free render slot"})
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
