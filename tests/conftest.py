"""
Shared fixtures. The render pipeline (cairosvg, Pillow, ffmpeg, Drive, the
Anthropic and ElevenLabs APIs) is replaced by a recording fake, so these tests
exercise the web layer only and need nothing but Flask and pytest.

    pip install flask pytest
    pytest
"""

import importlib
import io
import json
import pathlib
import sys
import threading
import time
import types

import pytest

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
TOKEN = "t0ken-" + "x" * 34  # 40 chars, above the 24-char minimum


class FakePipeline:
    """Stands in for run_job_lib. Records each config it was given; set .gate
    to a threading.Event to hold jobs 'rendering' until the test releases them."""

    def __init__(self):
        self.calls = []
        self.gate = None

    def run_pipeline(self, cfg, job_dir, **_kw):
        self.calls.append((dict(cfg), job_dir))
        if self.gate is not None:
            self.gate.wait(10)
        return {"outputs": {}, "message": "render complete"}


@pytest.fixture
def make_server(tmp_path, monkeypatch):
    """Returns build(**env) -> (server_module, FakePipeline, flask_test_client)."""

    def build(**env):
        monkeypatch.setenv("WORK_ROOT", str(tmp_path / "jobs"))
        monkeypatch.setenv("CRANE_API_TOKEN", TOKEN)
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, str(value))

        fake = FakePipeline()
        lib = types.ModuleType("run_job_lib")
        lib.run_pipeline = fake.run_pipeline
        monkeypatch.setitem(sys.modules, "run_job_lib", lib)
        monkeypatch.syspath_prepend(str(APP_DIR))
        sys.modules.pop("server", None)
        server = importlib.import_module("server")
        return server, fake, server.app.test_client()

    yield build
    sys.modules.pop("server", None)


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def post_render(client, *, config=None, files=None, headers=None):
    """POST /render with sensible defaults: photo + video + voiceover uploads."""
    cfg = {"id": "hiab-425k-test", "title": "Test"} if config is None else config
    data = {"config": cfg if isinstance(cfg, str) else json.dumps(cfg)}
    uploads = {"photo": ("crane.jpg", b"jpg"), "video": ("clip.mp4", b"mp4"),
               "voiceover": ("vo.mp3", b"mp3")}
    uploads.update(files or {})
    for field, spec in uploads.items():
        if spec is not None:
            name, body = spec
            data[field] = (io.BytesIO(body), name)
    return client.post("/render", data=data, content_type="multipart/form-data",
                       headers=auth() if headers is None else headers)


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def job_state(server, job_id):
    return server.JOBS.get(job_id, {}).get("status")


def release(fake):
    if fake.gate is not None:
        fake.gate.set()


def new_gate(fake):
    fake.gate = threading.Event()
    return fake.gate
