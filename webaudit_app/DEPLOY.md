# Deploying Site Blueprint for free, with nothing running locally

The app is a standard Dockerized FastAPI service, so it runs on most
container-friendly free tiers. Below are two options that don't require a
local Python install or a credit card at signup, as of early 2026 — free-tier
terms change often, so double-check current pricing/limits on the
provider's site before you commit.

## Option A — Hugging Face Spaces (recommended: genuinely free, no card)

1. Create a free account at huggingface.co (no card required).
2. Click **New Space** → give it a name → SDK: **Docker** → hardware:
   **CPU basic (free)** → Create Space.
3. On the Space's **Files** tab, click **Upload files** and drag in every
   file/folder from this project (or upload the zip and it'll prompt you —
   if it doesn't auto-extract, unzip it into a folder first and drag the
   contents in). Make sure `Dockerfile` ends up at the repo root.
   - Alternative: push the folder to a GitHub repo, then in the Space
     settings choose "link to a GitHub repo" instead of uploading directly.
4. The Space will build automatically (watch the **Logs** tab). When it
   finishes, your app is live at `https://<your-username>-<space-name>.hf.space`.
5. Optional — AI executive summaries: Space **Settings → Variables and
   secrets → New secret** → name `ANTHROPIC_API_KEY`, value your key.
   Everything else works without this.

**Free-tier caveats:** CPU Basic Spaces can go to sleep after a period of
inactivity and take a few seconds to wake back up on the next visit. The
in-memory audit store (see README's *Known limitations*) means any audits
in progress are lost if the Space restarts — for a personal/demo tool this
is fine; re-run the audit.

## Option B — Render.com free web service

1. Push this project to a GitHub repo (Render deploys from a repo, not a
   direct upload).
2. At render.com, **New → Web Service** → connect the repo.
3. Render should auto-detect the `Dockerfile`. If it instead offers a
   native Python environment, set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Choose the **Free** instance type → Create Web Service.
5. Same caveats as above, plus: Render's free web services spin down after
   ~15 minutes of no traffic and take ~30-50 seconds to cold-start on the
   next request — the first load after idling will feel slow, that's expected.

## Getting the code onto GitHub without installing anything locally

If you don't already have this project in a repo:

1. Create a new empty repo on github.com (web UI, no CLI).
2. On the repo page, use **Add file → Upload files**, and drag in the
   extracted project folder's contents.
3. Commit directly on the `main` branch via the web UI.

That's the whole path from "zip in this chat" to "running in the cloud"
without a local Python environment or terminal.
