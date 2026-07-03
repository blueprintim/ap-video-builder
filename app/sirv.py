"""
sirv.py
Upload the concatenated video to Sirv and return its public URL.

Sirv's API is OAuth2 client-credentials: POST /v2/token to get a bearer token,
then POST /v2/files/upload?filename=<path> with the raw bytes. Public delivery
URL is https://<account>.sirv.com/<path>.

NOTE: This mirrors the standard Sirv REST flow. If your existing crane_render
already has a working Sirv client, replace `SirvClient` with that one -- the
rest of the service only depends on `.upload(local_path, remote_path) -> url`.

Credentials come from env: SIRV_CLIENT_ID, SIRV_CLIENT_SECRET, SIRV_ACCOUNT
(the subdomain, e.g. 'blueprint' for blueprint.sirv.com).
"""

from __future__ import annotations
import os
import requests

SIRV_API = "https://api.sirv.com/v2"


class SirvError(Exception):
    pass


class SirvClient:
    def __init__(self, client_id=None, client_secret=None, account=None, session=None):
        self.client_id = client_id or os.environ.get("SIRV_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SIRV_CLIENT_SECRET")
        self.account = account or os.environ.get("SIRV_ACCOUNT")
        self._sess = session or requests.Session()
        self._token = None
        if not all([self.client_id, self.client_secret, self.account]):
            raise SirvError("Missing Sirv credentials (SIRV_CLIENT_ID/SECRET/ACCOUNT).")

    def _auth(self):
        r = self._sess.post(
            f"{SIRV_API}/token",
            json={"clientId": self.client_id, "clientSecret": self.client_secret},
            timeout=30,
        )
        if r.status_code != 200:
            raise SirvError(f"Sirv token request failed: {r.status_code} {r.text[:200]}")
        self._token = r.json().get("token")
        if not self._token:
            raise SirvError("Sirv token response had no token.")

    def upload(self, local_path, remote_path) -> str:
        """Upload local_path to remote_path (leading-slash path). Return public URL."""
        if self._token is None:
            self._auth()
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path
        with open(local_path, "rb") as f:
            data = f.read()
        r = self._sess.post(
            f"{SIRV_API}/files/upload",
            params={"filename": remote_path},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/octet-stream",
            },
            data=data,
            timeout=300,
        )
        if r.status_code not in (200, 201):
            raise SirvError(f"Sirv upload failed: {r.status_code} {r.text[:200]}")
        return f"https://{self.account}.sirv.com{remote_path}"
