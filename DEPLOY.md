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

### Running an audit — two ways

**From the published page itself (recommended):** open
`https://<your-username>.github.io/<repo-name>/` — that's a persistent
launcher page with a URL box right on it. Paste a GitHub personal access
token (the page explains how to create one, scoped to just this repo)
and a target URL, click **Run Audit**, and the page will trigger the
workflow and show you live status until it's done, then link straight to
the report. Behind the scenes it's calling the same GitHub Actions
workflow — this page just automates clicking through the Actions tab for
you, using GitHub's API from your browser.

**From the Actions tab (no token needed):** **Actions** → **"Run audit
and publish to GitHub Pages"** → **Run workflow** → fill in `start_url` →
run. Use this if you'd rather not paste a token anywhere, or you're
scripting/automating audits yourself.

Either way, when it finishes, the report is at
`https://<your-username>.github.io/<repo-name>/report.html` (the launcher
page links to it automatically). GitHub Pages can take a minute or two to
actually publish after the workflow finishes — if the report looks stale
right after a run, that's just CDN propagation, not a failure.

### What's different from the live FastAPI app in this mode

- The in-page "Run Audit" button on the launcher calls the GitHub API
  directly from your browser (via `fetch`) rather than talking to a
  server this project runs — there is no server, by definition, on a
  static host. This means starting a run needs a personal access token
  (typed into the page, sent straight to `api.github.com`, never written
  to the repo or stored anywhere unless you tick "remember"). The live
  FastAPI app doesn't need this since it has its own backend to talk to.
- Progress during a run is polled from GitHub's API rather than pushed
  from a live server, so updates land every few seconds rather than
  instantly.
- Everything else — the crawler, every analyzer, the scoring, the report
  itself (charts, hierarchy tree, link graph, page inventory, action plan,
  keyword frequency) — is identical code, just run by `run_audit_cli.py`
  instead of the FastAPI app.

---

## Option C — Streamlit Community Cloud (a different frontend, but free with no card historically required)

This uses a separate entry point — `streamlit_app.py` — built for hosts that
can't reasonably run a full custom FastAPI+HTML frontend. It reuses every
bit of the actual audit engine (crawler, analyzers, scoring, exports); only
the visual layer is simpler, built from Streamlit's own components instead
of the custom design in `templates/`.

**Important:** `streamlit_app.py` needs its own dependency file,
`requirements-streamlit.txt` — NOT the main `requirements.txt`. Installing
Streamlit and FastAPI in the same environment causes a real, silent-until-
you-hit-it version conflict on a shared dependency (`starlette`) that
breaks the FastAPI app. Keep these two deployment paths in separate
environments.

### Setup

1. Push this repo to GitHub (you likely already have this from the earlier
   GitHub Pages attempt).
2. Go to **share.streamlit.io**, sign in with your GitHub account (no card
   required, historically — confirm at signup, since free-tier terms shift).
3. **New app** → select your repo and the `main` branch → main file path:
   `streamlit_app.py`.
4. Under **Advanced settings**, set the requirements file path to
   `requirements-streamlit.txt` (not the default `requirements.txt`).
5. In the same Advanced settings, add secrets in TOML format if you want
   them:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   PAGESPEED_API_KEY = "..."
   ```
   Both are optional — the app works without them.
6. Deploy. Your app will be live at a `*.streamlit.app` URL.

### What's different here vs. the FastAPI app

- Visual design is Streamlit's own components (tabs, metrics, dataframes,
  built-in charts) rather than the custom "Studio" theme — functionally
  equivalent, just simpler to look at.
- The internal-link force-directed graph is replaced with a plain sorted
  table of most-linked-to pages — same underlying data, simpler rendering.
- `render_js` (Playwright) is exposed but not recommended here — this
  platform's free tier has tight memory limits, and there's no build step
  to install Playwright's browser binary the way the Dockerfile does for
  other hosts. It's left in as an option in case you're on a beefier plan,
  with a clear warning in the UI.
- Run history is written to local disk, which is typically ephemeral on
  free hosting — trend tracking may not survive a redeploy/restart here
  the way it does when GitHub Actions commits the history file to the repo.

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
