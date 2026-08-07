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
    # login.html and pricing.html are intentionally broken links in the
    # fixture (added to validate feature-matrix/journey-map detection
    # against real link text without needing real pages behind them)
    broken_link_count = 2
    assert seo_results["pages_ok"] == len(pages) - broken_link_count
    assert len(seo_results["title_issues"]) > 0

    score_results = scoring.run_scoring(ia_results, content_results, a11y_results, seo_results, len(pages))
    for key in ("ia_health_score", "content_quality_score", "accessibility_score", "seo_score", "ux_maturity_score"):
        assert 0 <= score_results[key] <= 100
    assert score_results["action_plan"], "expected at least one action item given fixture issues"

    from analyzers import feature_matrix, journey

    fm_results = feature_matrix.run_feature_matrix(crawler.feature_hits, [])
    detected_ids = {row["id"] for row in fm_results["rows"] if row["present"]}
    for expected in ("search", "login", "newsletter", "faq", "pricing", "blog", "contact_form"):
        assert expected in detected_ids, f"expected '{expected}' to be detected in the feature matrix fixture"

    jm = journey.build_journey_map(pages, ia_results["click_depths"])
    prospective = next(j for j in jm["journeys"] if j["id"] == "prospective_customer")
    stage_status = {s["id"]: s["present"] for s in prospective["stages"]}
    assert stage_status["awareness"] is True   # blog
    assert stage_status["consideration"] is True  # about
    assert stage_status["action"] is True      # contact form
    assert len(jm["journeys"]) == 4  # prospective customer, job seeker, existing customer, press/investor


def test_normalize_url_preserves_trailing_slash_forms():
    from crawler import normalize_url
    assert normalize_url("http://x.test/about/") == "http://x.test/about/"
    assert normalize_url("http://x.test/about") == "http://x.test/about"
    assert normalize_url("http://x.test/about#section") == "http://x.test/about"
    assert normalize_url("http://x.test") == "http://x.test/"


REDIRECT_SITE_DIR = Path(__file__).parent / "fixtures" / "redirect_site"
REDIRECT_SITE_PORT = 8124


@pytest.fixture(scope="module")
def redirect_server():
    """Serves fixtures/redirect_site, 301-redirecting /about -> /about/ —
    a linked page that only exists at a different URL than the one it was
    linked from. This is the exact scenario that silently broke orphan
    detection (see crawler.py's redirect_map): the link graph recorded the
    edge against the pre-redirect URL, which never matched the page's
    actual (post-redirect) key, so a perfectly reachable page looked
    orphaned.
    """
    class RedirectHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(REDIRECT_SITE_DIR), **kwargs)

        def do_GET(self):
            if self.path == "/about":
                self.send_response(301)
                self.send_header("Location", "/about/")
                self.end_headers()
                return
            super().do_GET()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", REDIRECT_SITE_PORT), RedirectHandler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{REDIRECT_SITE_PORT}/"
        httpd.shutdown()


@pytest.mark.asyncio
async def test_redirected_internal_links_are_not_orphaned(redirect_server):
    from crawler import normalize_url

    config = CrawlConfig(start_url=redirect_server, max_pages=20, concurrency=3, use_sitemap=False, respect_robots=False)
    progress = CrawlProgress()
    crawler = AsyncCrawler(config, progress)
    pages, edges = await crawler.crawl()

    about_url = next(u for u in pages if u.rstrip("/").endswith("about"))
    # confirm the redirect actually happened, i.e. this test is exercising
    # the scenario it claims to — if this ever stops being true because the
    # fixture changed, the rest of the assertions would be vacuous
    assert crawler.redirect_map, "expected the fixture's /about -> /about/ redirect to be recorded"

    start_norm = normalize_url(redirect_server)
    ia_results = ia.run_ia_analysis(pages, edges, start_norm)
    assert ia_results["orphan_page_count"] == 0, "the redirected /about/ page should be reachable, not orphaned"
    assert about_url not in ia_results["orphan_pages"]
