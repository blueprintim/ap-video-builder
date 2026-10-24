# Deploying Crane Render to Render.com — step by step

This walks you from the zip on your computer to a live service you can send jobs
to. Allow about 30–45 minutes the first time. You'll need three secrets ready:
your **Anthropic API key**, your **ElevenLabs API key + chosen voice ID**, and a
**Google service-account JSON + Drive folder ID** (the Drive part can wait if you
want to test rendering first).

There are two paths. **Path A (Blueprint)** is the recommended one and what the
included `render.yaml` is built for. **Path B (Dashboard, no Git)** is a fallback
if you'd rather not touch Git at all. Read Path A first.

---

## Before you start: the one hard requirement

Render's Blueprint feature reads `render.yaml` **from a Git repository** — it
can't read it from a zip or your local disk. So Path A needs the project pushed
to GitHub (or GitLab/Bitbucket). If that's a blocker, use Path B.

Either way, the project must NOT contain your secrets. The code already reads
every key from environment variables, and `.gitignore` already excludes real
per-crane configs — so you're safe to push as-is.

---

# Path A — Blueprint via GitHub (recommended)

## Step 1 — Unzip the project locally

Unzip `crane_render.zip`. You should see the `crane_render/` folder with `app/`,
`config/`, `assets/`, `Dockerfile`, `render.yaml`, and `README.md` inside.

## Step 2 — Put it in a GitHub repo

If you have Git and a GitHub account:

```bash
cd crane_render
git init
git add .
git commit -m "Crane render service"
```

Then create an empty repo on github.com (call it `crane-render`, keep it
**private** — this is your tooling, not public code), and follow GitHub's
"push an existing repository" instructions, which look like:

```bash
git remote add origin https://github.com/<your-username>/crane-render.git
git branch -M main
git push -u origin main
```

If you don't use Git from the command line, GitHub Desktop (a free app) lets you
do all of the above with buttons: "Add existing repository" → point it at the
`crane_render` folder → "Publish repository" (tick **Keep this code private**).

**Sanity check before pushing:** open the folder and confirm there's no file with
real API keys in it. There shouldn't be — keys live in Render, not the repo.

## Step 3 — Connect the repo to Render

1. Log in to the Render Dashboard.
2. Click **New** (top right) → **Blueprint**.
3. If this is your first time, Render asks to connect your GitHub account —
   approve it, and optionally limit access to just the `crane-render` repo.
4. In the list of repos, click **Connect** next to `crane-render`.
5. Render scans the repo, finds `render.yaml`, and shows you the service it will
   create (a Docker web service named `crane-render`). Give the Blueprint a name
   and confirm the branch is `main`.
6. Click **Apply** / **Create**.

Render now builds the Docker image (this takes several minutes the first time —
it's installing ffmpeg and fonts). You'll see build logs stream by.

## Step 4 — Set your secrets

The `render.yaml` declares the secret env vars but deliberately leaves their
values blank (marked `sync: false`) so they never live in Git. You fill them in
the dashboard:

1. In the Render Dashboard, open the **crane-render** service.
2. Go to the **Environment** tab.
3. You'll see these keys waiting for values. Set them:

   | Key | Value |
   |-----|-------|
   | `CRANE_API_TOKEN` | a long random secret that callers must send (see below) |
   | `ANTHROPIC_API_KEY` | your Anthropic key (`sk-ant-...`) |
   | `ELEVENLABS_API_KEY` | your ElevenLabs key |
   | `ELEVENLABS_VOICE_ID` | the voice ID you chose in ElevenLabs |
   | `GOOGLE_SERVICE_ACCOUNT_INFO` | paste the entire service-account JSON (can wait) |
   | `DRIVE_PARENT_FOLDER_ID` | the Drive folder ID (can wait) |

   The non-secret ones (`CAPTION_MODEL`, `ELEVENLABS_MODEL`, `RENDER_TMPDIR`,
   `WORK_ROOT`) are already filled from `render.yaml` — leave them.

4. Save. Render redeploys automatically with the new values.

> **The access token.** The service spends your ElevenLabs and Anthropic credit
> and publishes to Drive, so every call except the `/` health check must carry
> `Authorization: Bearer <CRANE_API_TOKEN>`. Make one with `openssl rand -hex 32`
> (any 24+ random characters work), save it in Render and in Make, and never put
> it in Git. With no token set the service answers `503` to everything but the
> health check — it will not run open.

> Finding your ElevenLabs voice ID: in the ElevenLabs app, open the voice you
> want and copy its voice ID (a string like `21m00Tcm4TlvDq8ikWAM`). Pick one
> voice and use it for every crane so the channel has a consistent narrator.

## Step 5 — Confirm it's alive

Once the deploy shows **Live**, find your service URL (top of the service page,
like `https://crane-render-xxxx.onrender.com`). Open it in a browser — you should
see a small JSON health response:

```json
{"ok": true, "service": "crane-render"}
```

That means the service is up.

## Step 6 — Run one real test job

This is the moment to verify captions and voiceover with real keys before
trusting anything unattended. The service takes a `POST /render` with the config
plus files. The easiest first test is from your computer with `curl`. Put a test
crane's `config.json`, `photo.jpg`, and `video.mp4` in a folder, then (for the
ElevenLabs voiceover path, no audio file needed):

```bash
curl -X POST https://crane-render-xxxx.onrender.com/render \
  -H "Authorization: Bearer $CRANE_API_TOKEN" \
  -F "config=@config.json" \
  -F "photo=@photo.jpg" \
  -F "video=@video.mp4"
```

(Use a config with `"voiceover_source": "elevenlabs"` and a `"script"`. If
instead you're supplying your own MP3, set `"voiceover_source": "file"` and add
`-F "voiceover=@voiceover.mp3"`.)

You'll get back:

```json
{"job_id": "abc123...", "status_url": "/status/abc123..."}
```

Poll the status until it's done:

```bash
curl -H "Authorization: Bearer $CRANE_API_TOKEN" \
  https://crane-render-xxxx.onrender.com/status/abc123...
```

When `status` is `done`, the response includes the caption text and (if Drive is
configured) the Drive folder link with your three videos and thumbnail. **Read
the captions and listen to the voiceover now** — this is your quality check.

---

# Path B — Dashboard deploy without Git

If you truly don't want to use Git, Render can build from a Docker image you push
to a registry, OR you can create the service manually. The honest tradeoff: you
lose the one-click `render.yaml` setup and configure the service by hand, and
updating the code later is more manual. For most people Path A is less work
overall. If you still want Path B:

1. Dashboard → **New** → **Web Service**.
2. Choose **Deploy an existing image** (if you've pushed the Docker image to a
   registry like Docker Hub) — this requires building and pushing the image
   yourself first with `docker build` and `docker push`.
3. Set the same environment variables from Step 4 above in the service's
   **Environment** tab.
4. Set the instance type to **Standard** or higher (see sizing note below).

Because this skips `render.yaml`, you'll also manually add the persistent disk
(Settings → Disks → 10 GB at mount path `/srv/_jobs`) that the Blueprint would
have created.

---

## Adding the token to a service that is already running

An existing deployment (and the Make scenario that calls it) keeps working
through this order; do the steps in sequence and don't merge the auth change first:

1. **Make first.** Add the header `Authorization: Bearer <token>` to the
   `POST /render` HTTP module and to the `GET /status/<id>` poll. The old code
   ignores the extra header, so nothing changes yet.
2. **Render second.** Environment tab → add `CRANE_API_TOKEN` with the same
   value → save (this redeploys the current code; still no change in behaviour).
3. **Merge the change.** Render auto-deploys. From now on a request without the
   token is refused. Check: `curl -i https://<service>/render -X POST` should
   return `401`, and a normal Make run should still complete.
4. **Rolling back** is a Render redeploy of the previous deploy; the token and
   the Make headers can stay in place.

A service that has no token set is *closed*, not open: until step 2 is done the
new version answers `503 auth_not_configured` to Make.

---

## Important settings and gotchas

**Instance size.** 1080p video encoding needs real CPU and memory. Use the
**Standard** plan or higher — the smallest/free tiers can run out of memory on a
3-minute encode and kill the job. You can start on Standard and size up if you
see out-of-memory errors in the logs.

**The free tier sleeps.** Free Render services spin down when idle and take ~30–60
seconds to wake on the next request. For a render service that's triggered
occasionally by Make, that cold start is usually fine, but it's another reason
Standard (which doesn't sleep) is the better fit here.

**First build is slow.** Installing ffmpeg + fonts into the image takes several
minutes. Later deploys are faster due to layer caching.

**Disk is scratch, not storage.** The 10 GB disk is working space for renders.
Finished videos should go to Google Drive (that's what the upload step is for) —
don't rely on the disk to keep deliverables long-term.

**Long renders vs. timeouts.** The service runs each job in a background thread
and returns immediately, so a multi-minute encode won't hit Render's request
timeout. You poll `/status/<id>` for completion. This is already built in.

**Updating the code later (Path A).** Make your change locally, commit, and push
to `main`. Render auto-deploys the new version. No dashboard clicks needed.

---

## What to do once the test job looks right

1. Confirm the captions read well and the voiceover voice is the one you want.
2. Eyeball one vertical (9:16) video to confirm the title fits and framing is OK
   (supply a `photo_9x16` if the landscape crop looks tight).
3. Then move to wiring Make → this service → Postiz, keeping the approval/review
   pause in place until the client is confident.

If a job fails, open the service's **Logs** tab in Render — the error from the
render pipeline (bad config field, missing key, ffmpeg issue) shows up there.
