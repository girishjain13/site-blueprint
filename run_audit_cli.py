"""Run one audit from the command line and write a static report.

This exists so the audit can run inside a GitHub Actions runner (a real
Linux VM with Python — no CORS issues, no server needed to *serve* the
result) and publish its output as plain files that GitHub Pages can serve
for free. Configure via environment variables so a GitHub Actions
workflow_dispatch input maps straight onto it; falls back to sane defaults
for local use.

Usage (local):
    START_URL=https://example.com MAX_PAGES=100 python run_audit_cli.py

Writes:
    docs/report.html             the report (what GitHub Pages serves)
    docs/index.html               the persistent launcher page
    docs/exports/audit.json
    docs/exports/audit.csv
    docs/exports/audit.xlsx
    docs/screenshots/*.png        only if RENDER_JS + CAPTURE_SCREENSHOTS are on
    history/<domain>.jsonl        committed back to the repo by the workflow
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path

from audit_engine import run_audit
from crawler import CrawlConfig
from history import append_history, load_history
from models import AuditStatus, CrawlProgress
from report_builder import export_csv, export_json, export_xlsx, render_html_report

OUT_DIR = Path(__file__).parent / "docs"
EXPORTS_DIR = OUT_DIR / "exports"
SCREENSHOTS_DIR = OUT_DIR / "screenshots"


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _print_progress_line(progress: CrawlProgress) -> None:
    # Plain-text progress so it's readable in the GitHub Actions log stream,
    # which doesn't render the live dashboard the web app has.
    print(
        f"[audit] status={progress.status.value} "
        f"crawled={progress.pages_crawled} queued={progress.pages_queued} "
        f"errors={progress.pages_errored} current={progress.current_url}",
        flush=True,
    )


def _screenshot_filename(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".png"


async def main() -> int:
    start_url = os.environ.get("START_URL", "").strip()
    if not start_url:
        print("ERROR: START_URL environment variable is required.", file=sys.stderr)
        return 1
    if not (start_url.startswith("http://") or start_url.startswith("https://")):
        print("ERROR: START_URL must include http:// or https://", file=sys.stderr)
        return 1

    max_pages = int(os.environ.get("MAX_PAGES", "5000"))
    max_depth = int(os.environ.get("MAX_DEPTH", "12"))
    concurrency = int(os.environ.get("CONCURRENCY", "8"))
    respect_robots = _env_bool("RESPECT_ROBOTS", True)
    use_sitemap = _env_bool("USE_SITEMAP", True)
    include_subdomains = _env_bool("INCLUDE_SUBDOMAINS", False)
    with_ai_summary = _env_bool("WITH_AI_SUMMARY", True)  # only fires if ANTHROPIC_API_KEY is set too

    render_js = _env_bool("RENDER_JS", False)
    capture_screenshots = _env_bool("CAPTURE_SCREENSHOTS", False) and render_js
    check_external_links = _env_bool("CHECK_EXTERNAL_LINKS", False)
    run_performance = _env_bool("RUN_PERFORMANCE", False)
    pagespeed_api_key = os.environ.get("PAGESPEED_API_KEY", "").strip() or None

    config = CrawlConfig(
        start_url=start_url,
        max_pages=min(max_pages, 5000),
        max_depth=max_depth,
        concurrency=concurrency,
        respect_robots=respect_robots,
        use_sitemap=use_sitemap,
        include_subdomains=include_subdomains,
        render_js=render_js,
        capture_screenshots=capture_screenshots,
        check_external_links=check_external_links,
    )
    progress = CrawlProgress()

    mode_note = " (JS-rendered)" if render_js else ""
    print(f"[audit] starting crawl of {start_url}{mode_note} (max_pages={config.max_pages})", flush=True)

    last_logged = -1

    async def on_progress():
        nonlocal last_logged
        if progress.pages_crawled != last_logged:
            last_logged = progress.pages_crawled
            _print_progress_line(progress)

    prior_history = load_history(start_url)

    audit_data, screenshots = await run_audit(
        config, progress, on_progress=on_progress, with_ai_summary=with_ai_summary,
        run_performance=run_performance, pagespeed_api_key=pagespeed_api_key,
        history_records=prior_history,
    )
    audit_data["audit_id"] = "latest"

    if progress.status == AuditStatus.ERROR:
        print("ERROR: audit failed", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # persist this run's scores to history now, so a crash further down
    # (rendering, exports) doesn't also lose the history record
    new_record = append_history(start_url, audit_data)
    audit_data["history"] = prior_history + [new_record]

    # save screenshots (only populated if render_js + capture_screenshots)
    screenshot_map = {}
    if screenshots:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        for url, png_bytes in screenshots.items():
            fname = _screenshot_filename(url)
            (SCREENSHOTS_DIR / fname).write_bytes(png_bytes)
            screenshot_map[url] = f"screenshots/{fname}"
    audit_data["screenshot_paths"] = screenshot_map

    html = render_html_report(audit_data)
    # the live app serves exports from /api/... and CSS from a /static
    # mount — neither route exists in a static build, and GitHub Pages
    # project sites are served from a /<repo-name>/ subpath, so an
    # absolute "/static/..." link would 404. Inline the CSS and rewrite
    # the export links to plain relative files instead.
    style_css = (Path(__file__).parent / "static" / "style.css").read_text(encoding="utf-8")
    html = html.replace(
        '<link rel="stylesheet" href="/static/style.css">',
        f"<style>\n{style_css}\n</style>",
    )
    html = html.replace("/api/audits/latest/export/json", "exports/audit.json")
    html = html.replace("/api/audits/latest/export/csv", "exports/audit.csv")
    html = html.replace("/api/audits/latest/export/xlsx", "exports/audit.xlsx")
    # the report lives at report.html, not index.html — index.html is the
    # persistent launcher (see below), which a run must never overwrite.
    (OUT_DIR / "report.html").write_text(html, encoding="utf-8")

    (EXPORTS_DIR / "audit.json").write_bytes(export_json(audit_data))
    (EXPORTS_DIR / "audit.csv").write_bytes(export_csv(audit_data))
    (EXPORTS_DIR / "audit.xlsx").write_bytes(export_xlsx(audit_data))

    # Regenerate the launcher page too. It's static/audit-independent, but
    # docs/ isn't committed to the repo (see .gitignore) — it's rebuilt
    # fresh by every workflow run, so this has to happen every run to
    # exist at all, not just once.
    launcher_html = (Path(__file__).parent / "templates" / "launcher.html").read_text(encoding="utf-8")
    launcher_html = launcher_html.replace("{{ inline_css }}", style_css)
    (OUT_DIR / "index.html").write_text(launcher_html, encoding="utf-8")

    print(f"[audit] done — {audit_data['meta']['pages_crawled']} pages, "
          f"UX maturity {audit_data['scoring']['ux_maturity_score']} "
          f"({audit_data['scoring']['ux_maturity_band']})", flush=True)
    if screenshots:
        print(f"[audit] captured {len(screenshots)} screenshot(s)", flush=True)
    if run_performance:
        print(f"[audit] performance sample: avg score "
              f"{audit_data['performance'].get('avg_performance_score')}", flush=True)
    print(f"[audit] history now has {len(audit_data['history'])} record(s) for this domain", flush=True)
    print(f"[audit] wrote {OUT_DIR}/report.html and refreshed {OUT_DIR}/index.html", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
