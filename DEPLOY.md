# Deploying Site Blueprint for free, with nothing running locally

## You're on GitHub Pages — here's the fit

GitHub Pages only serves static files; it can't run Python, and a browser
can't crawl arbitrary third-party sites itself (CORS blocks it). So the
crawl has to happen somewhere with real Python execution — and **GitHub
Actions** is that place, for free, on the same repo as your Pages site.

The pattern: you trigger a workflow from the **Actions** tab with the URL
you want audited → it runs the exact same crawler/analyzers from this
project on GitHub's runner → writes a static HTML report → publishes it to
GitHub Pages. No server ever needs to be "on" — the audit runs once per
trigger and the result sits as static files until you run it again.

### Setup (one-time)

1. Push this project to a GitHub repo (Add file → Upload files on the repo
   page works fine, no local git needed — extract the zip first and drag
   the contents in).
2. Repo **Settings → Pages** → under "Build and deployment", set
   **Source: GitHub Actions**.
3. Optional — for the AI executive summary: **Settings → Secrets and
   variables → Actions → New repository secret**, name
   `ANTHROPIC_API_KEY`. Skip this and the report still works, just without
   that section.

### Running an audit

1. Go to the **Actions** tab → **Run audit and publish to GitHub Pages** →
   **Run workflow**.
2. Fill in `start_url` (must include `http://` or `https://`) and adjust
   `max_pages` / `max_depth` / `concurrency` if you want — defaults are
   fine for a first run.
3. Watch the run's logs for live crawl progress (this replaces the
   in-browser live dashboard, since there's no server to poll here).
4. When it finishes, your report is live at
   `https://<your-username>.github.io/<repo-name>/` — same page updates in
   place every time you re-run the workflow with a new target.

That's the whole loop: **Actions tab → fill in a URL → Run workflow → open
the Pages URL.** Nothing installed, nothing running on your machine, and
nothing kept running in the cloud between runs either — it only spends
compute while a workflow is actively executing, which is well inside
GitHub's free minutes for a personal repo.

### What's different from the live app in this mode

- No live crawl dashboard — progress shows as plain log lines in the
  workflow run instead.
- No persistent "start a new audit from a form on the page" — you
  trigger runs from the Actions tab, not from the published site itself
  (the published site is static; it can't accept a form submission).
- Everything else — the crawler, every analyzer, the scoring, the report
  itself (charts, hierarchy tree, link graph, page inventory, action plan)
  — is identical code, just run by `run_audit_cli.py` instead of the
  FastAPI app.

---

## If you ever get access to a host that runs backend code

The rest of this guide (and the `Dockerfile` in this repo) covers running
the full live app — with the in-browser crawl dashboard and on-demand
audits from the page itself — on a free host that supports containers.

### Option A — Hugging Face Spaces (genuinely free, no card)

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
