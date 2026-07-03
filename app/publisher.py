"""
publisher.py
Publish generated files to the web server over SFTP (paramiko) or plain FTP.

Locked posture: this performs LIVE writes to the production web root, so the
service NEVER activates it implicitly -- the Flask endpoint requires an explicit
publish=true and, in the recommended setup, Make only calls it after the human
applies the 'Ready to publish' label.

Two publisher implementations behind one interface:
  - SFTPPublisher (paramiko) -- preferred
  - LocalMockPublisher      -- writes to a local dir, for testing (mock FTP)

Interface:
  .exists(remote_rel_path) -> bool          # for slug-collision checks
  .put_bytes(data, remote_rel_path)         # write a file
  .put_file(local_path, remote_rel_path)    # upload a file
All remote paths are relative to a configured web root.
"""

from __future__ import annotations
import os
import posixpath


class PublishError(Exception):
    pass


class LocalMockPublisher:
    """Writes into a local directory instead of a real server. For tests/dry-run."""

    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _abs(self, rel):
        return os.path.join(self.root, rel.lstrip("/"))

    def exists(self, rel):
        return os.path.exists(self._abs(rel))

    def put_bytes(self, data, rel):
        path = self._abs(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
        with open(path, mode) as f:
            f.write(data)
        return path

    def put_file(self, local_path, rel):
        with open(local_path, "rb") as f:
            return self.put_bytes(f.read(), rel)


class SFTPPublisher:
    """
    SFTP publisher using paramiko. Credentials via constructor or env:
      SFTP_HOST, SFTP_PORT (default 22), SFTP_USER, SFTP_PASSWORD or SFTP_KEYFILE,
      SFTP_WEBROOT (remote absolute path to the site root).
    """

    def __init__(self, host=None, port=None, user=None, password=None,
                 keyfile=None, webroot=None):
        import paramiko  # imported lazily so tests don't require it
        self._paramiko = paramiko
        self.host = host or os.environ.get("SFTP_HOST")
        self.port = int(port or os.environ.get("SFTP_PORT", 22))
        self.user = user or os.environ.get("SFTP_USER")
        self.password = password or os.environ.get("SFTP_PASSWORD")
        self.keyfile = keyfile or os.environ.get("SFTP_KEYFILE")
        self.webroot = (webroot or os.environ.get("SFTP_WEBROOT", "")).rstrip("/")
        if not all([self.host, self.user, (self.password or self.keyfile)]):
            raise PublishError("Missing SFTP credentials.")
        self._client = None
        self._sftp = None

    def _connect(self):
        if self._sftp:
            return
        t = self._paramiko.Transport((self.host, self.port))
        if self.keyfile:
            pkey = self._paramiko.RSAKey.from_private_key_file(self.keyfile)
            t.connect(username=self.user, pkey=pkey)
        else:
            t.connect(username=self.user, password=self.password)
        self._client = t
        self._sftp = self._paramiko.SFTPClient.from_transport(t)

    def _remote(self, rel):
        return posixpath.join(self.webroot, rel.lstrip("/"))

    def _mkdirs(self, remote_dir):
        parts = remote_dir.strip("/").split("/")
        cur = "/" if remote_dir.startswith("/") else ""
        for p in parts:
            cur = posixpath.join(cur, p) if cur else p
            try:
                self._sftp.stat(cur)
            except IOError:
                self._sftp.mkdir(cur)

    def exists(self, rel):
        self._connect()
        try:
            self._sftp.stat(self._remote(rel))
            return True
        except IOError:
            return False

    def put_bytes(self, data, rel):
        self._connect()
        remote = self._remote(rel)
        self._mkdirs(posixpath.dirname(remote))
        if isinstance(data, str):
            data = data.encode("utf-8")
        with self._sftp.open(remote, "wb") as f:
            f.write(data)
        return remote

    def put_file(self, local_path, rel):
        self._connect()
        remote = self._remote(rel)
        self._mkdirs(posixpath.dirname(remote))
        self._sftp.put(local_path, remote)
        return remote

    def close(self):
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()
