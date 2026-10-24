import os

import pytest

from conftest import TOKEN, auth, job_state, new_gate, post_render, release, wait_for


# ---------------------------------------------------------------- auth ----

def test_health_check_is_open(make_server):
    _server, _fake, client = make_server()
    assert client.get("/").status_code == 200
    assert client.head("/").status_code == 200


@pytest.mark.parametrize("headers", [
    {},                                          # no credentials
    {"Authorization": "Bearer wrong-" + "x" * 30},
    {"Authorization": "Bearer "},
    {"Authorization": "Basic " + "x" * 30},      # wrong scheme
    {"Authorization": TOKEN},                    # token without the scheme
    {"X-Api-Key": TOKEN},                        # not a header we read
])
def test_render_and_status_reject_bad_credentials(make_server, headers):
    server, fake, client = make_server()
    assert post_render(client, headers=headers).status_code == 401
    assert client.get("/status/abc", headers=headers).status_code == 401
    assert fake.calls == []
    assert os.listdir(server.BASE) == []         # nothing was staged either


def test_unknown_paths_do_not_reveal_routes_without_a_token(make_server):
    _server, _fake, client = make_server()
    assert client.get("/admin").status_code == 401
    assert client.get("/status/../../etc/passwd").status_code == 401


def test_token_is_case_insensitive_on_scheme_only(make_server):
    _server, _fake, client = make_server()
    ok = client.get("/status/none", headers={"Authorization": f"bearer {TOKEN}"})
    assert ok.status_code == 404                 # authenticated, job just unknown
    bad = client.get("/status/none", headers={"Authorization": f"Bearer {TOKEN.upper()}"})
    assert bad.status_code == 401


@pytest.mark.parametrize("value", [None, "", "short-token"])
def test_fails_closed_when_token_is_missing_or_weak(make_server, value):
    server, fake, client = make_server(CRANE_API_TOKEN=value)
    for resp in (post_render(client, headers=auth(value or "x")),
                 client.get("/status/abc", headers=auth(value or "x"))):
        assert resp.status_code == 503
        assert resp.get_json() == {"error": "auth_not_configured"}
    assert client.get("/").status_code == 200    # health stays up for Render
    assert fake.calls == []


def test_valid_token_is_accepted(make_server):
    server, fake, client = make_server()
    resp = post_render(client)
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]
    assert wait_for(lambda: job_state(server, job_id) == "done")
    assert client.get(f"/status/{job_id}", headers=auth()).get_json()["status"] == "done"


def test_unauthenticated_oversize_upload_is_refused_before_it_is_read(make_server):
    _server, fake, client = make_server(MAX_UPLOAD_MB=1)
    resp = post_render(client, files={"video": ("clip.mp4", b"0" * 2_000_000)}, headers={})
    assert resp.status_code == 401               # not 413: the body was never parsed
    assert fake.calls == []


# ---------------------------------------------------- upload filenames ----

@pytest.mark.parametrize("evil", [
    "/srv/app/captions.py",
    "../../../srv/app/captions.py",
    "..\\..\\windows\\evil.exe",
    "/etc/passwd",
    "a/b/c.jpg",
    "photo.jpg\x00.py",
])
def test_client_filename_never_reaches_the_filesystem(make_server, tmp_path, evil):
    server, fake, client = make_server()
    sentinel = tmp_path / "captions.py"
    sentinel.write_text("original")
    evil_path = str(sentinel) if evil == "/srv/app/captions.py" else evil

    resp = post_render(client, files={"photo": (evil_path, b"x"), "video": (evil_path, b"x"),
                                      "voiceover": (evil_path, b"x")})
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]
    assert wait_for(lambda: job_state(server, job_id) == "done")

    assert sentinel.read_text() == "original"
    assets = os.path.join(server.BASE, job_id, "assets")
    saved = sorted(os.listdir(assets))
    assert saved == ["photo", "video", "voiceover"] or all(
        n.split(".")[0] in ("photo", "video", "voiceover") for n in saved)
    cfg = fake.calls[0][0]
    for field in ("photo", "video", "voiceover"):
        assert "/" not in cfg[field] and "\\" not in cfg[field] and ".." not in cfg[field]
    # nothing was created anywhere under the jobs root except this job's folder
    assert os.listdir(server.BASE) == [job_id]


def test_whitelisted_extensions_are_kept_others_dropped(make_server):
    server, fake, client = make_server()
    resp = post_render(client, files={"photo": ("Crane.JPG", b"x"), "video": ("clip.exe", b"x"),
                                      "voiceover": ("vo.MP3", b"x"),
                                      "photo_9x16": ("v.png", b"x")})
    job_id = resp.get_json()["job_id"]
    assert wait_for(lambda: job_state(server, job_id) == "done")
    cfg = fake.calls[0][0]
    assert (cfg["photo"], cfg["video"], cfg["voiceover"], cfg["photo_9x16"]) == (
        "photo.jpg", "video", "voiceover.mp3", "photo_9x16.png")


def test_missing_required_file_is_a_400_and_leaves_no_folder(make_server):
    server, _fake, client = make_server()
    resp = post_render(client, files={"video": None})
    assert resp.status_code == 400 and resp.get_json()["error"] == "missing file: video"
    assert os.listdir(server.BASE) == []
    empty_name = post_render(client, files={"photo": ("", b"x")})
    assert empty_name.status_code == 400
    assert os.listdir(server.BASE) == []


def test_voiceover_not_required_in_elevenlabs_mode(make_server):
    server, fake, client = make_server()
    resp = post_render(client, config={"id": "x1", "voiceover_source": "elevenlabs",
                                       "script": "Hello."}, files={"voiceover": None})
    assert resp.status_code == 200
    assert wait_for(lambda: job_state(server, resp.get_json()["job_id"]) == "done")
    assert "voiceover" not in fake.calls[0][0]


# ------------------------------------------------------ config hygiene ----

def test_client_cannot_point_the_pipeline_at_other_files(make_server):
    server, fake, client = make_server()
    resp = post_render(client, config={
        "id": "x2",
        "photo_9x16": "/etc/passwd", "photo_1x1": "../../other-job/assets/photo.jpg",
        "assets": "/srv", "_assets_dir": "/etc", "_photo_path_9x16": "/etc/passwd",
        "_photo_path": "/etc/shadow", "_comment": "kept in example configs"},
        files={"photo_9x16": None})
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]
    assert wait_for(lambda: job_state(server, job_id) == "done")
    cfg = fake.calls[0][0]
    assert "photo_9x16" not in cfg and "photo_1x1" not in cfg and "assets" not in cfg
    assert not any(k.startswith("_") and k != "_assets_dir" for k in cfg)
    assert cfg["_assets_dir"] == os.path.join(server.BASE, job_id, "assets")


@pytest.mark.parametrize("raw, expected", [
    ("hiab-425k-drywall-kenworth-t880", "hiab-425k-drywall-kenworth-t880"),
    ("../../etc/cron.d/x", "etc-cron.d-x"),
    ("/abs/path", "abs-path"),
    ("My Crane (2026)", "My-Crane-2026"),
    ("...", None), ("", None), (None, None), (1234, "1234"),
])
def test_id_is_made_filename_safe(make_server, raw, expected):
    server, fake, client = make_server()
    cfg = {"title": "t"} if raw is None else {"id": raw}
    resp = post_render(client, config=cfg)
    job_id = resp.get_json()["job_id"]
    assert wait_for(lambda: job_state(server, job_id) == "done")
    got = fake.calls[0][0]["id"]
    assert got == (expected or job_id)
    assert "/" not in got and "\\" not in got and not got.startswith(".")


@pytest.mark.parametrize("config, message", [
    ({"id": "a", "voice_id": "../v1/user"}, "invalid voice_id"),
    ({"id": "a", "voice_id": "abc"}, "invalid voice_id"),
    ({"id": "a", "voice_id": 123456789}, "invalid voice_id"),
    ({"id": "a", "script": "x" * 5001}, "script must be text of at most 5000 characters"),
    ({"id": "a", "script": ["not", "text"]}, "script must be text of at most 5000 characters"),
    ("{not json", "config is not valid JSON"),
    ("[1, 2]", "config must be a JSON object"),
])
def test_bad_config_is_a_400(make_server, config, message):
    server, fake, client = make_server()
    resp = post_render(client, config=config)
    assert resp.status_code == 400 and resp.get_json()["error"] == message
    assert fake.calls == [] and os.listdir(server.BASE) == []


def test_real_looking_voice_id_and_blank_values_are_accepted(make_server):
    server, fake, client = make_server()
    ok = post_render(client, config={"id": "v", "voice_id": "21m00Tcm4TlvDq8ikWAM",
                                     "photo_9x16": "", "photo_1x1": "", "tts_model": ""})
    assert ok.status_code == 200
    blank = post_render(client, config={"id": "w", "voice_id": ""})
    assert blank.status_code == 200


def test_oversize_config_is_a_413(make_server):
    server, fake, client = make_server(MAX_CONFIG_KB=1)
    resp = post_render(client, config={"id": "a", "specs_for_copy": "x" * 5000})
    assert resp.status_code == 413 and resp.get_json()["error"] == "config too large"
    assert fake.calls == [] and os.listdir(server.BASE) == []


# ---------------------------------------------------------- size limits ----

def test_oversize_upload_is_a_413_json(make_server):
    server, fake, client = make_server(MAX_UPLOAD_MB=1)
    resp = post_render(client, files={"video": ("clip.mp4", b"0" * 2_000_000)})
    assert resp.status_code == 413
    assert resp.get_json() == {"error": "upload_too_large", "max_mb": 1}
    assert fake.calls == []


# ------------------------------------------------------ job queue limits ----

def test_queue_is_bounded_and_slots_are_released(make_server):
    server, fake, client = make_server(MAX_ACTIVE_JOBS=1, MAX_PENDING_JOBS=2)
    gate = new_gate(fake)

    first = post_render(client)
    second = post_render(client)
    third = post_render(client)                   # no capacity left
    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 503
    assert third.headers["Retry-After"] == "60"
    assert third.get_json()["error"] == "busy"
    assert os.listdir(server.BASE) and len(os.listdir(server.BASE)) == 2

    # only one render runs at a time; the other is queued but visible to /status
    assert wait_for(lambda: len(fake.calls) == 1)
    queued = second.get_json()["job_id"]
    assert client.get(f"/status/{queued}", headers=auth()).get_json()["status"] == "rendering"

    release(fake)
    assert wait_for(lambda: all(job_state(server, r.get_json()["job_id"]) == "done"
                                for r in (first, second)))
    assert wait_for(lambda: post_render(client).status_code == 200)   # capacity is back
    del gate


def test_rejected_requests_do_not_leak_capacity(make_server):
    server, _fake, client = make_server(MAX_PENDING_JOBS=1)
    for _ in range(5):                            # 400s must give their slot back
        assert post_render(client, config="{bad").status_code == 400
        assert post_render(client, files={"photo": None}).status_code == 400
    assert post_render(client).status_code == 200


def test_pipeline_errors_are_reported_and_free_the_slot(make_server):
    server, fake, client = make_server(MAX_ACTIVE_JOBS=1, MAX_PENDING_JOBS=1)

    def boom(cfg, job_dir, **_kw):
        raise RuntimeError("ffmpeg failed")
    server.J.run_pipeline = boom
    job_id = post_render(client).get_json()["job_id"]
    assert wait_for(lambda: job_state(server, job_id) == "error")
    assert server.JOBS[job_id]["message"] == "ffmpeg failed"
    assert wait_for(lambda: post_render(client).status_code == 200)


def test_status_history_is_capped(make_server):
    server, _fake, _client = make_server()
    for i in range(server.MAX_JOBS_REMEMBERED + 25):
        server._remember(f"job{i}", {"status": "done"})
    assert len(server.JOBS) == server.MAX_JOBS_REMEMBERED
    assert "job0" not in server.JOBS and f"job{server.MAX_JOBS_REMEMBERED + 24}" in server.JOBS


@pytest.mark.parametrize("raw, default", [("", 5), ("abc", 5), ("0", 5), ("-3", 5), ("7", 7)])
def test_numeric_limits_fall_back_to_defaults_when_invalid(make_server, monkeypatch, raw, default):
    server, _fake, _client = make_server()
    monkeypatch.setenv("SOME_LIMIT", raw)
    assert server._int_env("SOME_LIMIT", 5) == (7 if raw == "7" else default)
