"""
drive_upload.py — uploads a finished job folder to Google Drive and returns a
shareable link. Designed so the storage backend is swappable.

Auth: uses a Google service account JSON, path in env GOOGLE_SERVICE_ACCOUNT_JSON
(or the JSON contents in GOOGLE_SERVICE_ACCOUNT_INFO). Share your target Drive
folder with the service account's email, and set DRIVE_PARENT_FOLDER_ID to that
folder. This keeps the renderer from needing interactive OAuth — appropriate for
an unattended Render service.

Requires: google-api-python-client, google-auth (see requirements.txt).
"""

import json
import os

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2 import service_account
    _HAVE_GOOGLE = True
except Exception:
    _HAVE_GOOGLE = False

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _client():
    if not _HAVE_GOOGLE:
        raise RuntimeError(
            "Google API libraries not installed. Add google-api-python-client "
            "and google-auth to the environment."
        )
    info_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_INFO")
    path_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if info_env:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(info_env), scopes=SCOPES)
    elif path_env:
        creds = service_account.Credentials.from_service_account_file(
            path_env, scopes=SCOPES)
    else:
        raise RuntimeError(
            "Set GOOGLE_SERVICE_ACCOUNT_INFO (JSON string) or "
            "GOOGLE_SERVICE_ACCOUNT_JSON (path).")
    return build("drive", "v3", credentials=creds)


def _make_folder(svc, name, parent):
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent:
        meta["parents"] = [parent]
    f = svc.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return f["id"]


def _upload_file(svc, path, parent):
    name = os.path.basename(path)
    media = MediaFileUpload(path, resumable=True)
    meta = {"name": name, "parents": [parent]}
    svc.files().create(body=meta, media_body=media, fields="id",
                       supportsAllDrives=True).execute()


def upload_job_folder(job_dir, job_id):
    """Upload all deliverables in job_dir (skipping the _work subdir) to a new
    Drive subfolder. Returns the folder's shareable URL."""
    svc = _client()
    parent = os.environ.get("DRIVE_PARENT_FOLDER_ID")
    folder_id = _make_folder(svc, job_id, parent)

    for entry in sorted(os.listdir(job_dir)):
        full = os.path.join(job_dir, entry)
        if entry == "_work" or os.path.isdir(full):
            continue
        _upload_file(svc, full, folder_id)

    # Make the folder link-shareable (anyone with the link can view) so Make/
    # Postiz can fetch the media. Comment out if your workflow shares per-file.
    try:
        svc.permissions().create(
            fileId=folder_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception:
        pass

    return f"https://drive.google.com/drive/folders/{folder_id}"
