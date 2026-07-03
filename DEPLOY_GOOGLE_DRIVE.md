# Google Drive setup for Crane Render — step by step

This sets up the "robot account" (service account) that lets the render service
upload finished videos to your Google Drive on its own. You do this once.

**What you'll end up with — the three things Render needs:**
1. The **Google Drive API** enabled in a Cloud project.
2. A **service-account JSON key** (a text file) → goes in `GOOGLE_SERVICE_ACCOUNT_INFO`.
3. A **Drive folder ID** for a folder shared with the robot → goes in `DRIVE_PARENT_FOLDER_ID`.

Allow ~15 minutes. The Cloud Console is sprawling; the **search bar at the top**
is the most reliable way to get anywhere, so I lean on it below. Exact menu
labels occasionally change — when in doubt, search for the thing by name.

> Note: this is entirely optional for a first render test. You can deploy and
> prove rendering + voiceover work without Drive, then come back and do this when
> you're ready to wire up Make + Postiz (which is what actually needs files in
> Drive).

---

## Step 1 — Open the Google Cloud Console

Go to **console.cloud.google.com** and sign in with the Google account that owns
(or should own) the Drive where videos will land. The first time, you may be
asked to agree to terms — accept them. You do **not** need to enable billing for
this; the Drive API usage here is free.

## Step 2 — Create a project

A "project" is just a container for this setup.

1. At the very top of the page, click the **project picker** (the dropdown next
   to "Google Cloud", showing the current project name or "Select a project").
2. Click **New Project**.
3. Name it something memorable like `crane-render`. Leave the organization/location
   as-is. Click **Create**.
4. Wait a few seconds, then make sure the project picker at the top now shows
   `crane-render`. **Everything after this must happen inside this project** — if
   the top bar shows a different project, click the picker and switch back.

## Step 3 — Enable the Google Drive API

1. In the top **search bar**, type `Google Drive API` and select it from the
   results (it's under "Marketplace / APIs").
2. On its page, click **Enable**.
3. Wait for it to finish — you'll land on the API's overview page when it's done.

> Make sure it's the **Google Drive API** (the standard REST API), not any
> "MCP" or other Drive-related entry. This is the one the service uses.

## Step 4 — Create the service account (the robot)

1. In the search bar, type `Service Accounts` and open it (under "IAM & Admin").
2. Click **Create Service Account** near the top.
3. **Service account name:** type `crane-render-uploader` (or similar). Google
   fills in an ID automatically. Click **Create and Continue**.
4. **Grant access** step: you can skip this — it's for project-level roles, which
   we don't need (access is granted by sharing a Drive folder instead). Click
   **Continue**, then **Done**.
5. You're back on the service accounts list. You'll see your new account with an
   **email address** like:
   `crane-render-uploader@crane-render.iam.gserviceaccount.com`
   **Copy that email — you need it in Step 6.**

## Step 5 — Create and download the JSON key

1. In the service accounts list, click your `crane-render-uploader` account to
   open it.
2. Go to the **Keys** tab.
3. Click **Add Key → Create new key**.
4. Choose **JSON** and click **Create**.
5. Your browser downloads a `.json` file (named something like
   `crane-render-xxxxx.json`). **This is the credential. Keep it safe and private**
   — anyone with this file can act as the robot. Don't email it around or commit
   it to Git.

You'll paste the *contents* of this file into Render later (Step 8).

## Step 6 — Create the Drive folder and share it with the robot

1. Go to **drive.google.com** (signed in as the same account, or any account —
   see the note below).
2. Create a new folder, e.g. **Crane Render Output**.
3. Right-click the folder → **Share** (or open it and use the Share button).
4. In the share dialog, paste the **service account email** from Step 4
   (`crane-render-uploader@...iam.gserviceaccount.com`).
5. Set its access to **Editor** (so the robot can create files and subfolders).
6. **Untick** "Notify people" if offered (the robot has no inbox). Click **Share**
   / **Send**.

That's the key move: the robot can now write into *this one folder* and nothing
else in your Drive.

> Note on account ownership: a service account isn't part of a Workspace
> organization, so it's simplest to share a folder from a **personal** Google
> Drive. If you're on Google Workspace with strict external-sharing rules, your
> admin may block sharing to the service-account email — if the share fails or is
> restricted, that's why, and you may need admin help or a folder in a personal
> Drive.

## Step 7 — Get the folder ID

1. Open the folder in Drive (double-click it).
2. Look at the URL in your browser. It ends with the folder ID:
   `https://drive.google.com/drive/folders/`**`1A2b3C4d5E6f7G8h9I0j...`**
3. Copy that ID (the part after `/folders/`). This goes in `DRIVE_PARENT_FOLDER_ID`.

## Step 8 — Put both values into Render

In your Render service's **Environment** tab (from the Render deploy guide):

| Render env var | What to paste |
|----------------|---------------|
| `GOOGLE_SERVICE_ACCOUNT_INFO` | The **entire contents** of the JSON file from Step 5. Open the file in a text editor, select all, copy, and paste the whole thing (it starts with `{` and ends with `}`). |
| `DRIVE_PARENT_FOLDER_ID` | The folder ID from Step 7. |

Save. Render redeploys, and the service can now upload to that folder.

> Why paste the JSON contents rather than upload a file? Render stores env vars
> as text, and the service reads the JSON from `GOOGLE_SERVICE_ACCOUNT_INFO`
> directly. Pasting the whole JSON blob is expected and correct.

---

## Quick test that it worked

After a job runs with Drive configured, the `/status/<id>` response includes a
`drive_url`. Open it — you should see a new subfolder (named after the crane's
`id`) containing the three videos, the thumbnail, and the caption files. If they're
there, the whole chain works.

## If something goes wrong

- **"Permission denied" / 403 on upload** → the folder isn't shared with the
  service account email, or it's shared as Viewer not Editor. Re-check Step 6.
- **"API not enabled" error** → the Google Drive API isn't enabled in the *same
  project* as the service account. Re-check Step 3, and confirm the project
  picker shows `crane-render`.
- **"Invalid credentials" / can't parse** → the `GOOGLE_SERVICE_ACCOUNT_INFO`
  paste is incomplete or has stray characters. Re-copy the full JSON, from the
  opening `{` to the closing `}`.
- **Files render but never appear in Drive** → confirm both env vars are set and
  the service redeployed after you saved them.

## Security reminders

- The JSON key is a password-equivalent. Don't commit it to Git, don't paste it
  into chats or emails. It only ever belongs in Render's Environment settings.
- If the key is ever exposed, delete it in the service account's **Keys** tab and
  create a new one — the old one stops working immediately.
- The robot can only touch the folder(s) you explicitly shared with it. To revoke
  all access, unshare the folder or delete the service account.
