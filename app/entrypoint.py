"""
entrypoint.py — container start-up: drop root, then exec the server.

Render mounts the persistent disk owned by root, so the container has to start
as root to hand the writable paths to the unprivileged `app` user. This script
does exactly that and nothing else:

  1. give `app` the two writable directories (top level only — never a recursive
     walk of the disk) and check it can write to them;
  2. drop to `app` and confirm root cannot be regained;
  3. exec the real command (gunicorn), which therefore never runs as root.

The code under /srv/app stays root-owned and read-only to `app`, so even a bug
that lets a request write a file cannot overwrite the service's own modules.
"""

import os
import pwd
import sys

RUN_AS = "app"


def _writable_dirs():
    return [os.environ.get("WORK_ROOT", "/srv/_jobs"),
            os.environ.get("RENDER_TMPDIR", "/srv/.fftmp")]


def drop_privileges(user=RUN_AS):
    pw = pwd.getpwnam(user)
    for d in _writable_dirs():
        os.makedirs(d, exist_ok=True)
        os.chown(d, pw.pw_uid, pw.pw_gid)

    os.initgroups(user, pw.pw_gid)
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.environ.update(HOME=pw.pw_dir, USER=user, LOGNAME=user)

    try:
        os.setuid(0)
    except PermissionError:
        pass
    else:
        sys.exit("entrypoint: still able to regain root after dropping privileges")

    # Fail the deploy loudly here, not on the first customer job.
    for d in _writable_dirs():
        if not os.access(d, os.W_OK):
            sys.exit(f"entrypoint: {d} is not writable by {user}")


def main(argv):
    if not argv:
        sys.exit("entrypoint: no command given")
    if os.geteuid() == 0:
        drop_privileges()
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main(sys.argv[1:])
