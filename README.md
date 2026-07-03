# Crane Render — automated social video builder

Turns one crane listing into ready-to-post social assets:

- **3 video masters** — 16:9 (YouTube/X), 9:16 (Reels/Stories/Idea Pins), 1:1 (feed)
- **1 thumbnail** — 16:9, doubles as a Pinterest/Google Business still
- **6 captions** — YouTube, Instagram, Facebook, X, Pinterest, Google Business, each with the listing URL embedded per that platform's link rules

You supply four things per crane: a **photo**, the **source video**, a **voiceover audio file**, and a small **config** (specs + text). The tool does the rest.

---

## What it produces

For a job `id` of `hiab-425k-drywall-kenworth-t880` you get a folder containing:

```
hiab-425k-drywall-kenworth-t880_16x9.mp4
hiab-425k-drywall-kenworth-t880_9x16.mp4
hiab-425k-drywall-kenworth-t880_1x1.mp4
thumbnail.png
captions.json      # machine-readable, for Make/Postiz
captions.txt       # human-readable, for review
```

## How the video is assembled

```
[ 2s opening slide — silent ]
        |
[ main video, full length 1–3 min ]
   voiceover overlaid from the first frame; when the ~60s voiceover ends,
   the video keeps playing silently to its natural end
        |
[ 3s closing slide — silent ]
```

The main video is scaled and centre-cropped to each aspect ratio, so all three
masters come from the one source clip. Source audio is dropped by default
(`keep_source_audio: false`); set it true to mix the original audio low under
the voiceover.

---

## The config file

One JSON file per crane. Copy `config/hiab-425k.example.json` and edit. Fields:

| Field | What it is |
|-------|-----------|
| `id` | Slug used for output filenames and the Drive subfolder |
| `page_url` | The listing page; embedded into captions per platform |
| `phone`, `website`, `dealer` | Contact + brand shown on the closing slide and in captions |
| `title`, `subtitle`, `kicker` | Opening-slide text |
| `closing_kicker`, `closing_headline`, `closing_sub` | Closing-slide text |
| `thumb_line1`, `thumb_line2`, `thumb_spec` | Thumbnail headline (two lines) + spec line |
| `specs_for_copy` | Plain-text spec dump the caption model writes from. **Paste real specs; the model won't invent numbers.** |
| `photo`, `video`, `voiceover` | Filenames in the assets folder (or absolute paths) |
| `photo_9x16`, `photo_1x1` | *Optional.* Purpose-shot vertical / square images for better framing. If blank, the landscape `photo` is cropped to fit. The thumbnail always uses the landscape `photo`. |
| `voiceover_source` | `"file"` = use the supplied `voiceover` audio (manual flow). `"elevenlabs"` = generate the MP3 from `script` via ElevenLabs. |
| `voiceover` | Audio filename (used in `file` mode) |
| `script` | The approved narration text (used in `elevenlabs` mode). Spell out numbers and phone digits for clean TTS delivery. |
| `voice_id`, `tts_model` | *Optional.* Override the ElevenLabs voice / model per job; otherwise the `ELEVENLABS_VOICE_ID` / `ELEVENLABS_MODEL` env vars are used. |
| `keep_source_audio` | `false` = voiceover only; `true` = mix source audio under it |

Long titles auto-shrink (and wrap if needed) so they never clip on the
vertical canvas. The thumbnail headline is two explicit short lines you control,
so keep each punchy.

---

## Running it

### Option A — locally / on any machine

Requires Python 3.12, `ffmpeg`, and a font metric-compatible with Arial
(Liberation Sans is ideal; install `fonts-liberation` on Linux).

```bash
pip install -r requirements.txt
cd app
python run_job.py --config ../config/hiab-425k.json --assets ../assets --out ../output
```

Flags:
- `--no-captions` — skip the Claude API call (offline render test)
- `--upload` — push results to Google Drive
- `--ratios 16x9,9x16` — render a subset

### Option B — Docker (matches the Render environment exactly)

```bash
docker build -t crane-render .
docker run --rm -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GOOGLE_SERVICE_ACCOUNT_INFO="$(cat service-account.json)" \
  -e DRIVE_PARENT_FOLDER_ID=xxxx \
  crane-render
```

### Option C — Render (recommended; you already have an account)

1. Push this folder to a Git repo.
2. In Render: **New → Blueprint**, point it at the repo. `render.yaml` provisions
   a Docker web service with a 10 GB scratch disk.
3. Set the secret env vars in the dashboard: `ANTHROPIC_API_KEY`,
   `GOOGLE_SERVICE_ACCOUNT_INFO` (paste the service-account JSON),
   `DRIVE_PARENT_FOLDER_ID`.
4. Deploy. The service exposes:
   - `POST /render` — multipart form: `config` (JSON), `photo`, `video`, `voiceover`. Returns `{job_id, status_url}`.
   - `GET /status/<job_id>` — poll; when `status` is `done` you get the Drive link and caption text.

Rendering runs in a background thread so the HTTP request returns immediately —
a multi-minute encode never hits Render's request timeout.

### Option D — Google Colab (lowest-friction "not my computer")

Upload the folder, then in a cell:
```python
!apt-get -qq install ffmpeg fonts-liberation
!pip -q install -r requirements.txt
!cd app && python run_job.py --config ../config/hiab-425k.json --assets ../assets --out ../output
```

---

## Voiceover: manual or generated

Two ways to supply the narration, switchable per job via `voiceover_source`:

**Manual (`"file"`)** — you provide a ready MP3 (recorded, or made in a tool
like Canva's AI Voice). It drops into the `voiceover` slot. Keeps a human ear in
the loop before render.

**Generated (`"elevenlabs"`)** — the service turns the approved `script` into an
MP3 via the ElevenLabs API. Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`.
Pick one voice and keep it consistent across every crane so the channel has a
single narrator. Default model is `eleven_multilingual_v2` (high quality;
latency doesn't matter for batch voiceovers).

Either way, the script should **spell out numbers and phone digits** ("nine
thousand pounds", "six four seven, two nine zero...") — TTS reads raw numerals
and symbols inconsistently. The example config's `script` field shows the style.

Phase-one fit: in `elevenlabs` mode you still approve the *script* before it
becomes audio, which preserves your review step. Later, the script-writing
itself can be automated (a Claude call, like captions) for a fully hands-off run.

---



The renderer uploads with a **service account** so it needs no interactive login:

1. In Google Cloud, create a service account; download its JSON key.
2. Enable the Drive API for the project.
3. In Drive, create the destination folder and **share it with the service
   account's email** (the `client_email` in the JSON).
4. Set `DRIVE_PARENT_FOLDER_ID` to that folder's ID (from its URL).
5. Provide the key via `GOOGLE_SERVICE_ACCOUNT_INFO` (JSON string) or
   `GOOGLE_SERVICE_ACCOUNT_JSON` (file path).

The job folder is created inside that parent and made link-readable so Make
and Postiz can fetch the media.

---

## Wiring into Make + Postiz

The service is built to drop into your existing flow:

```
Make trigger (new row / manual)
   → HTTP POST to /render  (sends config + the 3 files)
   → poll GET /status/<id> until status = done
   → [PHASE 1: approval pause — you review captions.txt + the videos in Drive]
   → Postiz: schedule each video + its caption to the 6 channels
```

**Phase 1 (build client confidence):** keep the Make approval/wait module in,
so nothing posts until you've reviewed. The `captions.txt` file and the Drive
folder are there for exactly this review.

**Phase 2 (once trusted):** delete the approval module and it flows straight
through to Postiz. That's a one-module change, not a rebuild.

Captions are generated **inside** the render job (one atomic call Make just
triggers and waits on), so each caption stays bundled with the exact video it
describes.

---

## Environment variables

| Var | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | Caption generation (required for captions) |
| `CAPTION_MODEL` | Override the model (default `claude-sonnet-4-6`) |
| `ELEVENLABS_API_KEY` | Voiceover generation (required when `voiceover_source=elevenlabs`) |
| `ELEVENLABS_VOICE_ID` | Default voice for generated voiceovers (pick one and keep it consistent across cranes) |
| `ELEVENLABS_MODEL` | Override the TTS model (default `eleven_multilingual_v2`) |
| `GOOGLE_SERVICE_ACCOUNT_INFO` *or* `GOOGLE_SERVICE_ACCOUNT_JSON` | Drive auth |
| `DRIVE_PARENT_FOLDER_ID` | Destination Drive folder |
| `RENDER_TMPDIR` | ffmpeg scratch dir — keep on real disk, not a tmpfs |
| `WORK_ROOT` | Where jobs are staged |

---

## Notes, limits, and things to check on first real run

- **Fonts:** designed against Arial; the Docker image ships Liberation Sans
  (metric-compatible). On first deploy, eyeball one vertical opening slide to
  confirm the title fits as expected — the fit math assumes Arial-like metrics.
- **Captions need a live key:** the parsing is tested, but run one real job and
  read `captions.txt` before trusting it to post unattended.
- **Instance sizing:** 1080p ffmpeg wants real CPU/RAM. Use Render's Standard
  plan or higher; the smallest tiers can OOM on a 3-minute encode.
- **Concurrency:** one render holds state in memory. Scale by running more
  Render instances, not more gunicorn workers per instance.
- **Vertical/square framing:** a landscape photo cropped to 9:16 loses the
  sides of the truck — there's no way to show a full wide vehicle in a tall
  frame from a wide source. For best results, supply a purpose-shot vertical
  image via `photo_9x16` (and optionally `photo_1x1`). Without one, the tool
  still works by cropping the landscape photo.
- **Per-ratio photos on the web service:** POST optional `photo_9x16` /
  `photo_1x1` file fields alongside the required `photo`, `video`, `voiceover`.

---

## File map

```
app/
  render_slides.py   slide + thumbnail rendering, all 3 ratios, title auto-fit
  assemble_video.py  ffmpeg timing + assembly (2s open / video+VO / 3s close)
  captions.py        Claude API → 6 platform captions with URL embedding
  drive_upload.py    service-account upload to Google Drive
  run_job_lib.py     the pipeline as an importable function
  run_job.py         CLI entry point
  server.py          Flask service for Render (async jobs)
config/
  brand.json         brand colours + logo paths (shared across cranes)
  hiab-425k.example.json   per-crane config template
assets/              logos, photo, video, voiceover
Dockerfile           ffmpeg + fonts baked in
render.yaml          Render blueprint
requirements.txt
```
