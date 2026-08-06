"""Plain-language framing for the report — the same numbers the analyzers
produce, described the way you'd explain them out loud in a design review
rather than as raw metric names.
"""
from __future__ import annotations

SCORE_COPY = {
    "ux_maturity_score": {
        "label": "Overall UX Maturity",
        "plain": "A blended read of the four scores below — how findable, well-written, accessible, and search-friendly the site is overall.",
    },
    "ia_health_score": {
        "label": "Information Architecture",
        "plain": "How easy it is to find anything by clicking around — fewer orphaned pages and shorter paths score higher.",
    },
    "content_quality_score": {
        "label": "Content Quality",
        "plain": "Whether pages have enough real substance, aren't duplicated, and use headings in a sensible order.",
    },
    "accessibility_score": {
        "label": "Accessibility",
        "plain": "Whether people using screen readers, keyboard navigation, or assistive tech can actually use the site.",
    },
    "seo_score": {
        "label": "SEO / Findability",
        "plain": "Whether search engines (and link previews) can tell what each page is actually about.",
    },
}

BAND_COPY = {
    "Strong": "This is in good shape — keep an eye on it, but it's not where your next effort should go.",
    "Adequate": "Workable, with some rough edges worth cleaning up when there's time.",
    "Needs Improvement": "Worth prioritizing — there are enough issues here to be affecting real visitors.",
    "Critical": "This needs attention soon — issues at this level are likely costing conversions, comprehension, or accessibility compliance.",
}


def build_plain_summary(scoring: dict, ia: dict, content: dict, a11y: dict) -> list[str]:
    """A few sentences a designer could paste straight into a standup update."""
    lines = []
    band = scoring["ux_maturity_band"]
    lines.append(f"Overall, this site's UX maturity is **{band.lower()}** ({scoring['ux_maturity_score']}/100). {BAND_COPY.get(band, '')}")

    if ia["orphan_page_count"]:
        lines.append(f"{ia['orphan_page_count']} page(s) can't be reached by clicking through the site at all — visitors (and search engines) will only ever find them by a direct link.")
    if ia["pages_over_3_clicks"]:
        lines.append(f"{ia['pages_over_3_clicks']} page(s) take more than 3 clicks to reach from the homepage — that's usually a sign the navigation or category structure needs rethinking.")
    if content["thin_content_count"]:
        lines.append(f"{content['thin_content_count']} page(s) have very little actual content on them — worth checking whether they need expanding, merging, or removing.")
    if content["duplicate_content_page_count"]:
        lines.append(f"{content['duplicate_content_page_count']} page(s) duplicate content that already exists elsewhere on the site — a common source of confusing search results and self-competition.")
    if a11y["pages_with_issues"]:
        lines.append(f"{a11y['pages_with_issues']} of {a11y['pages_analyzed']} pages have at least one accessibility issue — most commonly missing alt text or unlabeled form fields.")
    return lines
