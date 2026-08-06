"""Optional JavaScript-rendering fetch path, using a headless browser
instead of a raw HTTP request. This exists because a plain HTTP fetch
(see crawler.py's default path) only ever sees the HTML a server sends
before any JavaScript runs — for a client-rendered app (React/Angular/Vue,
etc.) that can be nearly empty even though a real visitor sees a full
page. Rendering is opt-in (`render_js=True`) because it's slower (a real
browser navigation per page instead of a lightweight HTTP request) and
needs the Playwright browser binaries installed — see README/DEPLOY for
the extra setup step this requires in CI or a Dockerfile.

Note: this module's browser-launch path could not be exercised end-to-end
in the environment this was built in (the sandbox's network allowlist
blocks Playwright's browser-binary CDN) — the logic is written to the
documented Playwright async API and is straightforward, but treat a first
real run on GitHub Actions (which has open internet) as the actual test.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RenderedPage:
    url: str  # final URL after any client-side/JS redirect
    html: str
    status_code: Optional[int]
    screenshot: Optional[bytes] = None
    error: Optional[str] = None


class RenderingClient:
    """Wraps a single headless Chromium instance for the whole crawl.
    Launch once, reuse a pool of pages/contexts, close once at the end —
    launching a fresh browser per page would be far too slow.
    """

    def __init__(self, concurrency: int = 4, capture_screenshots: bool = False, timeout_ms: int = 20000):
        self.concurrency = max(1, min(concurrency, 6))  # a real browser is heavy; keep this modest
        self.capture_screenshots = capture_screenshots
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._semaphore = None

    async def start(self):
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 IA-UX-AuditBot/1.0"
            ),
        )
        import asyncio
        self._semaphore = asyncio.Semaphore(self.concurrency)

    async def stop(self):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass  # best-effort cleanup — a shutdown error shouldn't crash the whole run

    async def fetch(self, url: str) -> RenderedPage:
        async with self._semaphore:
            page = await self._context.new_page()
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                # give any post-load JS (lazy content, hydration) a brief moment
                await page.wait_for_timeout(400)
                html = await page.content()
                status = response.status if response else None
                final_url = page.url
                screenshot = None
                if self.capture_screenshots:
                    screenshot = await page.screenshot(type="png", full_page=False)
                return RenderedPage(url=final_url, html=html, status_code=status, screenshot=screenshot)
            except Exception as exc:
                return RenderedPage(url=url, html="", status_code=None, error=f"render_failed: {exc.__class__.__name__}")
            finally:
                await page.close()
