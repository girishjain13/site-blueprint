# Site Blueprint — Enterprise Website IA & UX Audit Tool

A working audit tool that crawls a website and produces an Information
Architecture, UX, Content, Accessibility, and SEO report — scores, an
interactive HTML report, and JSON/CSV/XLSX exports.

This is the **real, working audit engine** distilled from a much larger
"enterprise SaaS platform" spec. It intentionally does **not** include
multi-tenant auth, billing, Celery/Redis workers, or Docker/CI-CD scaffolding
— see *Scope* below for why, and what you'd add to get there.

## What it does

- Crawls a site (static HTML, up to 5,000 pages) respecting `robots.txt`,
  discovering extra URLs from `sitemap.xml`, following redirects, with
  bounded concurrency.
- Analyzes:
  - **IA** — URL hierarchy tree, path/click-depth distribution, orphan
    pages (via a NetworkX link graph), top-level taxonomy.
  - **Content** — word counts, thin-content flags, duplicate content
    detection, heading-order issues, image/alt coverage.
  - **Accessibility** — missing alt text, unlabeled form fields, missing
    `lang`, missing ARIA landmarks, multiple `<h1>`s.
  - **SEO / metadata** — title/description length & uniqueness, canonical
    tags, Open Graph, Schema.org (JSON-LD) coverage, HTTP status breakdown.
- Scores the site 0–100 on each dimension plus an overall **UX Maturity**
  score, and produces a prioritized action plan.
- Renders an interactive HTML report (charts, a hierarchy tree, a
  force-directed internal-link graph, a sortable/filterable page inventory)
  and exports to JSON, CSV, and XLSX.
- Optionally generates an AI executive summary via the Anthropic API if
  `ANTHROPIC_API_KEY` is set — everything else works without it.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000`, enter a URL you own or have permission to
crawl, and start the audit. When it finishes you're taken straight to the
report. Only static HTML is fetched — there's no JavaScript rendering, so
heavily client-rendered pages will show thinner content than the browser
sees.

To enable the optional AI executive summary:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Running the tests

```bash
pip install pytest pytest-asyncio
pytest -v
```

The test suite spins up the bundled `sample_site/` fixture on
`localhost:8099` and runs the real crawler and every analyzer against it —
it's also a good reference for expected output shapes.

## Project layout

```
app.py                 FastAPI app: routes, background audit task, exports
audit_engine.py         Orchestrates crawl + all analyzers into one result
crawler.py               Async crawler (robots.txt, sitemap, redirects)
robots.py                 robots.txt / sitemap.xml parsing helpers
models.py                  Shared dataclasses (PageRecord, CrawlProgress)
ai_insights.py               Optional LLM executive summary
report_builder.py              HTML report render + JSON/CSV/XLSX export
analyzers/
  ia.py                        Hierarchy, click-depth, orphans, taxonomy
  content.py                    Word counts, duplicates, heading order
  accessibility.py               Alt text, labels, ARIA, lang
  seo.py                          Titles, descriptions, canonicals, schema
  scoring.py                      Composite scores + action plan
templates/
  index.html               Crawl launcher + live progress dashboard
  report.html                Full audit report (charts, tree, graph, table)
static/style.css              Shared "blueprint" design system
sample_site/                Local fixture site used by the tests
tests/test_integration.py     End-to-end test against sample_site
```

## Known limitations (by design, given the scope)

- **No JS rendering.** The crawler fetches raw HTML only. Sites that render
  primary content client-side will show as thin/empty. Adding Playwright
  for a "render mode" is the natural next step if you need it — it wasn't
  included here to keep the tool runnable without a browser download.
- **Orphan-page detection depends on sitemap coverage.** A page with zero
  inbound internal links *and* absent from `sitemap.xml` is invisible to
  any crawler by definition — it can't be discovered, only inferred from
  an external source (server logs, GA, a CMS export). If you have one of
  those, feeding its URLs in as extra sitemap-style seeds would close this
  gap.
- **In-memory audit store.** Audit state lives in the FastAPI process's
  memory (`app.py`'s `_audits` dict). Restarting the server loses
  in-progress/completed audits. Fine for a local tool; swap in Redis or a
  database table if you need persistence or multiple worker processes.
- **Single-process concurrency.** Bounded by an `asyncio.Semaphore`, not a
  distributed job queue — appropriate for pages in the hundreds to low
  thousands, not for running many large audits in parallel.
- **PDF export** is "print the HTML report" (there's a print stylesheet)
  rather than a separately generated PDF file; wire up something like
  WeasyPrint if you need a literal `.pdf` on disk.
- **Scoring weights are simple and transparent** (see
  `analyzers/scoring.py`) rather than tuned against real benchmark data —
  treat the 0–100 numbers as directionally useful, not authoritative.

## Path to the original "enterprise SaaS" spec

The original brief also called for multi-tenant auth, subscriptions/usage
quotas, a Celery/Redis job queue, a separate React frontend, Docker Compose
+ CI/CD, and Core Web Vitals / brand-compliance analyzers. None of that
changes the audit logic above — it's additive infrastructure around it:

1. Move `_audits` and `CrawlProgress` into Postgres; move the crawl task
   from `asyncio.create_task` into a Celery worker so it survives restarts
   and scales horizontally.
2. Add an auth layer (e.g. an OAuth/JWT provider) and scope audits to a
   `team_id` / `project_id`.
3. Split the frontend into a proper React app consuming the same
   `/api/audits/*` routes (they're already a clean JSON API).
4. Containerize `app.py` + a Celery worker + Postgres + Redis behind Nginx,
   wire up GitHub Actions for tests + build + deploy.
5. Add analyzers as new files under `analyzers/` (Core Web Vitals would
   need Playwright/Lighthouse; brand compliance would need a rules engine
   or vision-model calls) — the plugin point already exists, since
   `audit_engine.py` just calls each analyzer module and merges the dict.
