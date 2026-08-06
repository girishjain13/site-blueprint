"""End-to-end test: spins up the bundled sample_site on a local HTTP
server, runs the real crawler + all analyzers against it, and checks
the results are structurally and numerically sane. This is the fixture
also used to manually validate the tool during development.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

import pytest

from analyzers import accessibility, content, ia, scoring, seo
from crawler import AsyncCrawler, CrawlConfig
from models import CrawlProgress

SAMPLE_SITE_DIR = Path(__file__).parent.parent / "sample_site"


SAMPLE_SITE_PORT = 8099  # must match the absolute host:port baked into sample_site/sitemap.xml


@pytest.fixture(scope="module")
def sample_server():
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(SAMPLE_SITE_DIR), **kw)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", SAMPLE_SITE_PORT), handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://localhost:{SAMPLE_SITE_PORT}/"
        httpd.shutdown()


@pytest.mark.asyncio
async def test_crawl_and_analyze(sample_server):
    config = CrawlConfig(start_url=sample_server, max_pages=50, concurrency=5, use_sitemap=True)
    progress = CrawlProgress()
    crawler = AsyncCrawler(config, progress)
    pages, edges = await crawler.crawl()

    # sanity: crawler found the known fixture pages
    assert len(pages) >= 9
    assert any(u.rstrip("/").endswith("about") for u in pages)
    assert any("orphan.html" in u for u in pages), "orphan page should be discovered via sitemap.xml"

    start_url = sample_server.rstrip("/") + "/" if not sample_server.endswith("/") else sample_server
    # normalize like the app does
    from crawler import normalize_url
    start_norm = normalize_url(sample_server)

    ia_results = ia.run_ia_analysis(pages, edges, start_norm)
    assert ia_results["orphan_page_count"] == 1
    assert any("orphan.html" in u for u in ia_results["orphan_pages"])
    assert ia_results["max_click_depth"] >= 2

    content_results = content.run_content_analysis(pages)
    assert content_results["thin_content_count"] > 0  # fixture pages are short
    assert content_results["duplicate_content_page_count"] >= 1  # widget-pro/widget-lite are identical

    a11y_results = accessibility.run_accessibility_analysis(pages)
    assert a11y_results["images_missing_alt"] >= 1
    assert a11y_results["inputs_missing_label"] >= 1  # contact form has unlabeled inputs

    seo_results = seo.run_seo_analysis(pages)
    assert seo_results["pages_ok"] == len(pages)
    assert len(seo_results["title_issues"]) > 0

    score_results = scoring.run_scoring(ia_results, content_results, a11y_results, seo_results, len(pages))
    for key in ("ia_health_score", "content_quality_score", "accessibility_score", "seo_score", "ux_maturity_score"):
        assert 0 <= score_results[key] <= 100
    assert score_results["action_plan"], "expected at least one action item given fixture issues"


def test_normalize_url_preserves_trailing_slash_forms():
    from crawler import normalize_url
    assert normalize_url("http://x.test/about/") == "http://x.test/about/"
    assert normalize_url("http://x.test/about") == "http://x.test/about"
    assert normalize_url("http://x.test/about#section") == "http://x.test/about"
    assert normalize_url("http://x.test") == "http://x.test/"
