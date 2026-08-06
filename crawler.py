"""Async breadth-first website crawler with robots.txt / sitemap support,
canonicalization, redirect handling, and concurrency control.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from models import AuditStatus, CrawlProgress, PageRecord
from robots import RobotsInfo

DEFAULT_HEADERS = {
    "User-Agent": "IA-UX-AuditBot/1.0 (+https://example.com/bot; respects robots.txt)"
}

SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".rar",
    ".mp4", ".mp3", ".avi", ".mov", ".css", ".js", ".xml", ".ico", ".woff",
    ".woff2", ".ttf", ".eot", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def normalize_url(url: str) -> str:
    """Strip fragments and ensure an empty path becomes '/'.

    Deliberately does NOT strip trailing slashes: many servers 301-redirect
    a no-slash directory URL ("/about") to its slash form ("/about/"), and
    httpx follows that automatically. If we stripped the slash here, the
    pre-fetch (queued) URL and the post-redirect (crawled/stored) URL would
    end up as two different strings, which silently breaks link-graph edges
    between them. Leaving both forms distinct is safer than mismatching.
    """
    url, _frag = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path or "/"
    normalized = parsed._replace(path=path, query=parsed.query)
    return normalized.geturl()


def same_site(url: str, root_netloc: str, include_subdomains: bool) -> bool:
    netloc = urlparse(url).netloc
    if include_subdomains:
        return netloc == root_netloc or netloc.endswith("." + root_netloc.split(":")[0])
    return netloc == root_netloc


@dataclass
class CrawlConfig:
    start_url: str
    max_pages: int = 200
    max_depth: int = 12
    concurrency: int = 8
    request_timeout: float = 15.0
    include_subdomains: bool = False
    respect_robots: bool = True
    use_sitemap: bool = True
    auth_headers: Optional[dict] = None


class AsyncCrawler:
    """Breadth-first crawler. Produces a dict[url] -> PageRecord and an
    internal-link edge list suitable for building a NetworkX graph.
    """

    def __init__(self, config: CrawlConfig, progress: CrawlProgress):
        self.config = config
        self.progress = progress
        self.pages: dict[str, PageRecord] = {}
        self.edges: list[tuple[str, str]] = []  # (from_url, to_url) internal links
        self._seen: set[str] = set()
        self._root_netloc = urlparse(config.start_url).netloc

    async def crawl(self, on_progress: Optional[Callable[[], Awaitable[None]]] = None):
        cfg = self.config
        self.progress.status = AuditStatus.CRAWLING
        self.progress.max_pages = cfg.max_pages
        headers = dict(DEFAULT_HEADERS)
        if cfg.auth_headers:
            headers.update(cfg.auth_headers)

        limits = httpx.Limits(max_connections=cfg.concurrency, max_keepalive_connections=cfg.concurrency)
        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=cfg.request_timeout, limits=limits
        ) as client:
            robots = RobotsInfo(cfg.start_url)
            if cfg.respect_robots:
                await robots.load(client)

            queue: deque[tuple[str, int]] = deque()
            start = normalize_url(cfg.start_url)
            queue.append((start, 0))
            self._seen.add(start)

            # Seed extra URLs from sitemap.xml so IA analysis reflects the
            # declared site structure, not just what's link-reachable.
            if cfg.use_sitemap:
                try:
                    sitemap_urls = await robots.discover_sitemap_urls(client, cap=cfg.max_pages * 2)
                    for u in sitemap_urls:
                        nu = normalize_url(u)
                        if nu not in self._seen and same_site(nu, self._root_netloc, cfg.include_subdomains):
                            self._seen.add(nu)
                            queue.append((nu, 1))
                except Exception:
                    pass

            sem = asyncio.Semaphore(cfg.concurrency)
            t0 = time.monotonic()
            in_flight: set[asyncio.Task] = set()

            async def worker(url: str, depth: int):
                async with sem:
                    await self._fetch_and_parse(client, robots, url, depth, queue)
                    self.progress.pages_crawled = len(self.pages)
                    self.progress.pages_queued = len(queue)
                    self.progress.current_url = url
                    elapsed = time.monotonic() - t0
                    self.progress.elapsed_seconds = elapsed
                    n = max(self.progress.pages_crawled, 1)
                    self.progress.avg_page_seconds = elapsed / n
                    remaining = min(len(queue), cfg.max_pages - self.progress.pages_crawled)
                    self.progress.eta_seconds = max(remaining, 0) * self.progress.avg_page_seconds
                    if on_progress:
                        await on_progress()

            while queue and len(self.pages) < cfg.max_pages:
                # launch a batch up to available concurrency
                batch = []
                while queue and len(batch) < cfg.concurrency and len(self.pages) + len(batch) < cfg.max_pages:
                    url, depth = queue.popleft()
                    if depth > cfg.max_depth:
                        continue
                    batch.append(worker(url, depth))
                if not batch:
                    break
                await asyncio.gather(*batch)

        self.progress.status = AuditStatus.ANALYZING
        return self.pages, self.edges

    async def _fetch_and_parse(
        self,
        client: httpx.AsyncClient,
        robots: RobotsInfo,
        url: str,
        depth: int,
        queue: deque,
    ):
        record = PageRecord(url=url, depth=depth, path_depth=self._path_depth(url))
        if self.config.respect_robots and not robots.can_fetch(url):
            record.error = "blocked_by_robots_txt"
            self.pages[url] = record
            self.progress.note(f"Skipped (robots.txt disallow): {url}")
            return

        t0 = time.monotonic()
        try:
            resp = await client.get(url)
            record.fetch_ms = (time.monotonic() - t0) * 1000
            record.status_code = resp.status_code
            if str(resp.url) != url:
                record.redirected_from = url
                record.url = str(resp.url)
            content_type = resp.headers.get("content-type", "")
            record.content_type = content_type

            if resp.status_code >= 400:
                record.error = f"http_{resp.status_code}"
                self.pages[record.url] = record
                self.progress.pages_errored += 1
                self.progress.note(f"Error {resp.status_code}: {url}")
                return

            if "text/html" not in content_type:
                self.pages[record.url] = record
                return

            self._parse_html(record, resp.text, queue, depth)
            self.pages[record.url] = record

        except httpx.HTTPError as exc:
            record.error = f"request_failed: {exc.__class__.__name__}"
            record.fetch_ms = (time.monotonic() - t0) * 1000
            self.pages[url] = record
            self.progress.pages_errored += 1
            self.progress.note(f"Failed: {url} ({exc.__class__.__name__})")

    def _path_depth(self, url: str) -> int:
        path = urlparse(url).path
        return len([seg for seg in path.split("/") if seg])

    def _parse_html(self, record: PageRecord, html: str, queue: deque, depth: int):
        soup = BeautifulSoup(html, "lxml")

        # --- metadata ---
        if soup.title and soup.title.string:
            record.title = soup.title.string.strip()
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            record.meta_description = meta_desc["content"].strip()
        canonical = soup.find("link", attrs={"rel": "canonical"})
        if canonical and canonical.get("href"):
            record.canonical = canonical["href"]
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            record.lang = html_tag["lang"]

        for og in soup.find_all("meta", attrs={"property": lambda p: p and p.startswith("og:")}):
            record.og_tags[og["property"]] = og.get("content", "")

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            record.has_schema_org = True
            txt = (script.string or "")[:200]
            record.schema_types.append(txt)

        # --- headings ---
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            record.heading_sequence.append(tag.name)
            if tag.name == "h1":
                record.h1_list.append(tag.get_text(strip=True))

        # --- content ---
        body = soup.find("body")
        text = body.get_text(separator=" ", strip=True) if body else soup.get_text(separator=" ", strip=True)
        words = text.split()
        record.word_count = len(words)
        record.reading_time_seconds = int(len(words) / 3.5)  # ~200 wpm
        record.text_hash = hashlib.sha1(" ".join(words).encode("utf-8", "ignore")).hexdigest()
        record.is_thin_content = record.word_count < 150

        # scroll-depth proxy: estimate rendered height from block-level element count
        block_tags = soup.find_all(["p", "div", "section", "article", "li", "img", "h1", "h2", "h3"])
        record.rendered_height_estimate = 80 + len(block_tags) * 45  # rough px estimate per block

        # --- accessibility ---
        images = soup.find_all("img")
        record.images_total = len(images)
        record.images_missing_alt = sum(1 for img in images if not img.get("alt", "").strip())
        forms = soup.find_all("form")
        record.forms_total = len(forms)
        missing_labels = 0
        for form in forms:
            for inp in form.find_all(["input", "textarea", "select"]):
                itype = inp.get("type", "text")
                if itype in ("hidden", "submit", "button"):
                    continue
                has_label = bool(inp.get("aria-label")) or bool(inp.get("id") and soup.find("label", attrs={"for": inp.get("id")}))
                if not has_label:
                    missing_labels += 1
        record.inputs_missing_label = missing_labels
        record.aria_landmark_count = len(soup.find_all(attrs={"role": True}))

        # --- links ---
        base = record.url
        internal, external = 0, 0
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urljoin(base, href)
            if any(absolute.lower().split("?")[0].endswith(ext) for ext in SKIP_EXTENSIONS):
                continue
            normalized = normalize_url(absolute)
            if same_site(normalized, self._root_netloc, self.config.include_subdomains):
                internal += 1
                record.internal_links_out.append(normalized)
                self.edges.append((record.url, normalized))
                if normalized not in self._seen and len(self._seen) < self.config.max_pages * 3:
                    self._seen.add(normalized)
                    queue.append((normalized, depth + 1))
            else:
                external += 1
        record.external_links_out_count = external
