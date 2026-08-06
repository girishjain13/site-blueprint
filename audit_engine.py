"""Ties the crawler and analyzers together into a single audit run."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from analyzers import accessibility, content, ia, integrations, keywords, scoring, seo
from analyzers.heuristics import classify_into_heuristics, heuristic_summary
from ai_insights import generate_ai_summary
from crawler import AsyncCrawler, CrawlConfig
from models import AuditStatus, CrawlProgress
from ux_copy import build_lead_assessment, build_plain_summary


async def run_audit(
    config: CrawlConfig,
    progress: CrawlProgress,
    on_progress: Optional[Callable[[], Awaitable[None]]] = None,
    with_ai_summary: bool = True,
) -> dict:
    progress.started_at = datetime.now(timezone.utc)
    crawler = AsyncCrawler(config, progress)
    pages, edges = await crawler.crawl(on_progress=on_progress)

    ia_results = ia.run_ia_analysis(pages, edges, crawler_start_url(config, pages))
    content_results = content.run_content_analysis(pages)
    a11y_results = accessibility.run_accessibility_analysis(pages)
    seo_results = seo.run_seo_analysis(pages)
    score_results = scoring.run_scoring(ia_results, content_results, a11y_results, seo_results, len(pages))
    keyword_results = keywords.run_keyword_analysis(
        crawler.global_word_counts, crawler.global_bigram_counts, crawler.global_doc_freq, len(pages)
    )
    integration_results = integrations.run_integration_analysis(
        crawler.integration_hits, crawler.unrecognized_script_domains, crawler.all_external_scripts, pages, len(pages)
    )
    heuristics_results = classify_into_heuristics(score_results["action_plan"])
    plain_summary = build_plain_summary(score_results, ia_results, content_results, a11y_results)
    lead_assessment = build_lead_assessment(
        score_results, ia_results, content_results, a11y_results, seo_results,
        integration_results, keyword_results, len(pages),
    )

    progress.status = AuditStatus.DONE
    progress.finished_at = datetime.now(timezone.utc)

    audit_data = {
        "meta": {
            "start_url": config.start_url,
            "pages_crawled": len(pages),
            "pages_errored": progress.pages_errored,
            "max_pages_configured": config.max_pages,
            "started_at": progress.started_at.isoformat(),
            "finished_at": progress.finished_at.isoformat(),
            "elapsed_seconds": round(progress.elapsed_seconds, 1),
        },
        "pages": {
            url: {
                "url": rec.url,
                "status_code": rec.status_code,
                "title": rec.title,
                "meta_description": rec.meta_description,
                "word_count": rec.word_count,
                "path_depth": rec.path_depth,
                "click_depth": ia_results["click_depths"].get(url),
                "is_thin_content": rec.is_thin_content,
                "is_duplicate_of": rec.is_duplicate_of,
                "images_total": rec.images_total,
                "images_missing_alt": rec.images_missing_alt,
                "has_schema_org": rec.has_schema_org,
                "canonical": rec.canonical,
                "internal_links_out_count": len(rec.internal_links_out),
                "reading_time_seconds": rec.reading_time_seconds,
                "rendered_height_estimate": rec.rendered_height_estimate,
                "script_count": rec.script_count,
                "external_script_count": rec.external_script_count,
                "error": rec.error,
            }
            for url, rec in pages.items()
        },
        "link_edges": edges,
        "ia": {k: v for k, v in ia_results.items() if k != "click_depths"},
        "content": content_results,
        "accessibility": a11y_results,
        "seo": seo_results,
        "scoring": score_results,
        "keywords": keyword_results,
        "integrations": integration_results,
        "heuristics": heuristics_results,
        "heuristics_summary": heuristic_summary(heuristics_results),
        "plain_summary": plain_summary,
        "lead_assessment": lead_assessment,
    }

    if with_ai_summary:
        summary = await generate_ai_summary(audit_data)
        audit_data["ai_summary"] = summary

    return audit_data


def crawler_start_url(config: CrawlConfig, pages: dict) -> str:
    from crawler import normalize_url

    normalized = normalize_url(config.start_url)
    if normalized in pages:
        return normalized
    # fall back to whatever the crawler resolved the start page to (redirects)
    for url, rec in pages.items():
        if rec.redirected_from == normalized:
            return url
    return normalized
