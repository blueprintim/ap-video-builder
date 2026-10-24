import importlib
import os
import shutil
import sys
import types

import pytest

APP_DIR = os.path.join(os.path.dirname(__file__), "..", "app")


def load(name, monkeypatch, **env):
    monkeypatch.syspath_prepend(APP_DIR)
    # drop_privileges() rewrites these; setenv registers them for restoration
    for key in ("HOME", "USER", "LOGNAME"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop(name, None)
    return importlib.import_module(name)


# ------------------------------------------------------------ entrypoint ----

class Recorder:
    """Replaces the os / pwd calls so the root path can be tested without root."""

    def __init__(self, monkeypatch, entrypoint, regain_root=False, writable=True):
        self.calls = []
        pw = types.SimpleNamespace(pw_uid=10001, pw_gid=10001, pw_dir="/home/app")
        monkeypatch.setattr(entrypoint.pwd, "getpwnam", lambda u: pw)
        monkeypatch.setattr(entrypoint.os, "makedirs", lambda d, exist_ok=False: self.calls.append(("makedirs", d)))
        monkeypatch.setattr(entrypoint.os, "chown", lambda d, u, g: self.calls.append(("chown", d, u, g)))
        monkeypatch.setattr(entrypoint.os, "initgroups", lambda n, g: self.calls.append(("initgroups", n, g)))
        monkeypatch.setattr(entrypoint.os, "setgid", lambda g: self.calls.append(("setgid", g)))
        monkeypatch.setattr(entrypoint.os, "access", lambda d, mode: writable)

        def setuid(uid):
            self.calls.append(("setuid", uid))
            if uid == 0 and not regain_root:
                raise PermissionError
        monkeypatch.setattr(entrypoint.os, "setuid", setuid)


def test_drops_root_after_handing_over_the_writable_dirs(monkeypatch):
    ep = load("entrypoint", monkeypatch, WORK_ROOT="/srv/_jobs", RENDER_TMPDIR="/srv/.fftmp")
    rec = Recorder(monkeypatch, ep)
    ep.drop_privileges()

    names = [c[0] for c in rec.calls]
    assert ("chown", "/srv/_jobs", 10001, 10001) in rec.calls
    assert ("chown", "/srv/.fftmp", 10001, 10001) in rec.calls
    # chown needs root, so it must come first; then groups, gid, uid — in that order
    assert names.index("chown") < names.index("initgroups") < names.index("setgid") < names.index("setuid")
    assert ("setuid", 10001) in rec.calls
    assert (os.environ["HOME"], os.environ["USER"]) == ("/home/app", "app")


def test_refuses_to_start_if_root_can_be_regained(monkeypatch):
    ep = load("entrypoint", monkeypatch)
    Recorder(monkeypatch, ep, regain_root=True)
    with pytest.raises(SystemExit, match="regain root"):
        ep.drop_privileges()


def test_fails_the_deploy_if_a_work_dir_is_not_writable(monkeypatch):
    ep = load("entrypoint", monkeypatch, WORK_ROOT="/srv/_jobs")
    Recorder(monkeypatch, ep, writable=False)
    with pytest.raises(SystemExit, match="not writable"):
        ep.drop_privileges()


def test_main_drops_privileges_only_when_root_and_then_execs(monkeypatch):
    ep = load("entrypoint", monkeypatch)
    executed, dropped = [], []
    monkeypatch.setattr(ep.os, "execvp", lambda cmd, argv: executed.append((cmd, argv)))
    monkeypatch.setattr(ep, "drop_privileges", lambda: dropped.append(True))

    monkeypatch.setattr(ep.os, "geteuid", lambda: 0)
    ep.main(["gunicorn", "server:app"])
    assert dropped == [True] and executed == [("gunicorn", ["gunicorn", "server:app"])]

    monkeypatch.setattr(ep.os, "geteuid", lambda: 10001)   # already unprivileged
    ep.main(["gunicorn", "server:app"])
    assert dropped == [True]
    with pytest.raises(SystemExit):
        ep.main([])


# ------------------------------------------------------- ffmpeg time limit ----

@pytest.mark.skipif(shutil.which("sleep") is None, reason="needs a sleep binary")
def test_hung_subprocess_is_killed_with_a_clear_error(monkeypatch, tmp_path):
    av = load("assemble_video", monkeypatch, FFMPEG_TIMEOUT_SEC="1", RENDER_TMPDIR=str(tmp_path))
    assert av.FFMPEG_TIMEOUT_SEC == 1
    with pytest.raises(RuntimeError, match="timed out after 1s"):
        av._run(["sleep", "30"])


def test_normal_subprocess_still_works_and_failures_still_report(monkeypatch, tmp_path):
    av = load("assemble_video", monkeypatch, RENDER_TMPDIR=str(tmp_path))
    assert av.FFMPEG_TIMEOUT_SEC == 1800
    assert av._run([sys.executable, "-c", "print('ok')"]).stdout.strip() == "ok"
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        av._run([sys.executable, "-c", "import sys; sys.exit(3)"])
