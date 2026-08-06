"""Optional AI-generated executive summary and narrative recommendations.

Only runs if ANTHROPIC_API_KEY is set in the environment. Fully optional —
the rest of the audit (scores, charts, action plan) works without it.
"""
from __future__ import annotations

import json
import os


def ai_insights_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def generate_ai_summary(audit_data: dict) -> str | None:
    if not ai_insights_available():
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.AsyncAnthropic()
    scoring = audit_data["scoring"]
    prompt = f"""You are a senior UX/IA consultant. Based on this website audit summary,
write a concise executive summary (max 200 words) for a stakeholder deck, plus
3-5 top strategic recommendations. Be specific and reference the numbers given.

Site: {audit_data['meta']['start_url']}
Pages crawled: {audit_data['meta']['pages_crawled']}
IA Health Score: {scoring['ia_health_score']}/100
Content Quality Score: {scoring['content_quality_score']}/100
Accessibility Score: {scoring['accessibility_score']}/100
SEO Score: {scoring['seo_score']}/100
UX Maturity: {scoring['ux_maturity_score']}/100 ({scoring['ux_maturity_band']})
Orphan pages: {audit_data['ia']['orphan_page_count']}
Thin content pages: {audit_data['content']['thin_content_count']}
Duplicate content pages: {audit_data['content']['duplicate_content_page_count']}
Accessibility issues on: {audit_data['accessibility']['pages_with_issues']} pages

Respond in plain text, no markdown headers.
"""
    try:
        resp = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")
    except Exception as exc:
        return f"(AI summary unavailable: {exc})"
