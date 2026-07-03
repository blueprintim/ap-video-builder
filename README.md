# crane_page_builder

Standalone Flask service that builds an Atlas Polar `Framework.php` product page
from a Trello card's attachments (spec spreadsheet + images + videos) and
publishes it to the web server over SFTP.

Designed to be called by a Make.com scenario when a card gets the
**"Ready to publish"** label. Can run on its own or be folded into the existing
`crane_render` service (register the blueprint from `app/server.py`).

## Endpoint

`POST /build_product_page`  (header `X-Build-Token: <BUILD_API_TOKEN>`)

Body: see `sample_make_payload.json`. Attachment URLs are Trello download URLs;
`trello_key`/`trello_token` come from the Make Trello connection. `publish:false`
performs a dry run (renders + reports, no writes).

### Pipeline
1. **Download & sort** attachments securely — host allowlist (Trello only),
   size/count caps, extension-based sorting into spreadsheet / images / videos.
2. **Parse** the spreadsheet into product + truck spec blocks, price, contact.
   Missing/unparseable sheet or missing Model → **422, nothing published.**
3. **Video** — concat multiple clips (filename-number order) via ffmpeg
   (two-pass, robust to mixed resolution/fps/audio) → upload to Sirv.
4. **Slug** from crane Model + truck Make + Model; **numeric suffix on
   collision** (`-2`, `-3`…) — never overwrites.
5. **Render** the `.php` page (row per non-blank spec pair; logo by product
   group; fixed section icons).
6. **Publish** images (`1.jpg…N.jpg`) into `media_path` and the `.php` to
   `demo-used-equipment/`.

## Environment variables
| Var | Purpose |
|-----|---------|
| `BUILD_API_TOKEN` | Shared secret required in `X-Build-Token`. If unset, auth is skipped (dev only). |
| `SIRV_CLIENT_ID` / `SIRV_CLIENT_SECRET` / `SIRV_ACCOUNT` | Sirv upload. If unset, video is concatenated but not uploaded (no video URL). |
| `SFTP_HOST` / `SFTP_PORT` / `SFTP_USER` / `SFTP_PASSWORD` or `SFTP_KEYFILE` / `SFTP_WEBROOT` | SFTP publish target. If `SFTP_HOST` unset, writes to `MOCK_PUBLISH_DIR` (dry run). |
| `MOCK_PUBLISH_DIR` | Local dir for mock publishing (default `/tmp/cpb_publish`). |

## Local run / test
```bash
pip install -r requirements.txt
PYTHONPATH=. python -m pytest tests/ -q          # unit tests
PYTHONPATH=. python -m app.server                # serve on :8000 (mock publish)
```

## Notes / decisions
- **Plain FTP vs SFTP:** ships with SFTP (paramiko). If the host is plain FTP
  only, swap `SFTPPublisher` for an `ftplib`-based publisher with the same
  interface (`exists` / `put_bytes` / `put_file`).
- **Sirv client** is a standard REST implementation; if crane_render already has
  a working Sirv client, drop it in — the builder only needs
  `.upload(local, remote) -> url`.
- **Product-group → media folder** map lives in `app/server.py`
  (`PRODUCT_GROUP_DIR_MAP`); extend as new equipment lines appear.
- **Icons** are fixed (`../../icon-crane.png`, `../../icon-truck.png`); confirm
  these filenames exist on the server or adjust in `app/renderer.py`.
