"""Real performance data via Google's PageSpeed Insights API — the actual
Core Web Vitals (LCP, CLS, INP/TBT) a browser would measure, rather than
the script-count proxy the rest of this tool otherwise relies on.

Deliberately sampled, not run on every page: PSI takes 5-15+ seconds per
call and is rate-limited without an API key (roughly 1 req/sec; a free key
from Google Cloud Console raises that substantially, still at no cost).
Running it against a full crawl of hundreds/thousands of pages would blow
past both that rate limit and reasonable CI run time, so this checks a
small, meaningful sample (homepage + the most-linked-to pages) instead of
claiming full-site coverage it can't actually deliver.

Not independently verified end-to-end in the environment this was built
in — outbound network to Google's API was not reachable from that sandbox.
The request/response shape follows PSI's documented v5 API; treat a first
real run as the actual test, and check the logged HTTP status if a page
comes back with no data.
"""
from __future__ import annotations

import asyncio

import httpx

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def select_sample_pages(pages: dict, edges: list[tuple[str, str]], start_url: str, sample_size: int = 5) -> list[str]:
    """Homepage first, then the most-linked-to pages — the ones most likely
    to matter for a business (and most likely to represent real traffic).
    """
    from collections import Counter

    inbound = Counter()
    for _src, dst in edges:
        inbound[dst] += 1

    candidates = [
        url for url, rec in pages.items()
        if rec.status_code and rec.status_code < 400 and rec.content_type and "text/html" in rec.content_type
    ]
    candidates.sort(key=lambda u: (-1 if u == start_url else 0, -inbound.get(u, 0)))
    return candidates[:sample_size]


async def fetch_pagespeed(client: httpx.AsyncClient, url: str, api_key: str | None, strategy: str = "mobile") -> dict:
    params = {"url": url, "strategy": strategy, "category": "PERFORMANCE"}
    if api_key:
        params["key"] = api_key
    try:
        resp = await client.get(PSI_ENDPOINT, params=params, timeout=45.0)
        if resp.status_code != 200:
            return {"url": url, "error": f"http_{resp.status_code}"}
        data = resp.json()
        lighthouse = data.get("lighthouseResult", {})
        audits = lighthouse.get("audits", {})
        perf_score = lighthouse.get("categories", {}).get("performance", {}).get("score")
        return {
            "url": url,
            "performance_score": round(perf_score * 100) if perf_score is not None else None,
            "lcp": audits.get("largest-contentful-paint", {}).get("displayValue"),
            "cls": audits.get("cumulative-layout-shift", {}).get("displayValue"),
            "tbt": audits.get("total-blocking-time", {}).get("displayValue"),
            "speed_index": audits.get("speed-index", {}).get("displayValue"),
            "report_url": f"https://pagespeed.web.dev/analysis?url={httpx.QueryParams({'url': url})['url']}",
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"url": url, "error": exc.__class__.__name__}


async def run_performance_analysis(
    pages: dict, edges: list[tuple[str, str]], start_url: str,
    api_key: str | None = None, sample_size: int = 5,
) -> dict:
    sample = select_sample_pages(pages, edges, start_url, sample_size)
    if not sample:
        return {"sampled": False, "results": [], "avg_performance_score": None}

    results = []
    async with httpx.AsyncClient() as client:
        # PSI is rate-limited without a key — run sequentially with a small
        # delay rather than firing all requests at once and getting 429s.
        for url in sample:
            results.append(await fetch_pagespeed(client, url, api_key))
            if not api_key:
                await asyncio.sleep(1.2)

    scores = [r["performance_score"] for r in results if r.get("performance_score") is not None]
    return {
        "sampled": True,
        "sample_size": len(sample),
        "results": results,
        "avg_performance_score": round(sum(scores) / len(scores)) if scores else None,
        "note": "Sampled — homepage plus the most-linked-to pages, not every page in the crawl.",
    }
