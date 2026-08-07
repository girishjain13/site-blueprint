"""UX & IA Audit — Streamlit frontend.

This reuses every bit of the actual audit engine (crawler.py, analyzers/*,
audit_engine.py, report_builder.py's export functions) — only the UI layer
is different from app.py's FastAPI+HTML version. Built for hosts where a
full custom frontend isn't worth the deployment friction; if you're running
this on a host that *can* run the FastAPI app, that version has a more
tailored visual design and a live crawl dashboard.

Run locally with:
    streamlit run streamlit_app.py

Notes specific to this hosting path:
- render_js (Playwright) is exposed but not recommended on memory-constrained
  free hosts — a real headless browser is heavy, and this UI can't install
  Playwright's browser binary at deploy time the way the Docker image does.
- Run history is written to local disk (history/*.jsonl) — on a host with
  ephemeral storage (most free tiers), this will NOT survive a
  restart/redeploy. Treat trend tracking as a nice-to-have here, not
  something to rely on.
- Set ANTHROPIC_API_KEY / PAGESPEED_API_KEY via Streamlit's secrets manager
  (Settings → Secrets) to enable the optional AI summary / higher PSI limits.
"""
from __future__ import annotations

import asyncio
import os

import pandas as pd
import streamlit as st

from audit_engine import run_audit
from crawler import CrawlConfig
from history import append_history, load_history
from models import CrawlProgress
from report_builder import export_csv, export_json, export_xlsx

st.set_page_config(page_title="UX & IA Audit", layout="wide")

# Secrets (set via Streamlit's Secrets manager) flow into the same env vars
# ai_insights.py / analyzers/performance.py already look for. st.secrets
# raises FileNotFoundError if no secrets.toml exists at all (i.e. nobody's
# configured any secrets yet) — which is exactly the "works without them"
# case this needs to support, so that has to be caught, not just a missing
# key within an existing file.
try:
    _secrets = st.secrets
    for key in ("ANTHROPIC_API_KEY", "PAGESPEED_API_KEY"):
        if key in _secrets and not os.environ.get(key):
            os.environ[key] = _secrets[key]
except Exception:
    pass  # no secrets configured — every feature that needs one just stays off

if "audit_data" not in st.session_state:
    st.session_state.audit_data = None

st.title("UX & Information Architecture Audit")
st.caption(
    "Crawl a site and get back a heuristic evaluation — scored, prioritized, "
    "and organized the way a design review reads."
)

with st.form("audit_form"):
    start_url = st.text_input("Target URL", placeholder="https://example.com")

    c1, c2, c3 = st.columns(3)
    with c1:
        max_pages = st.number_input("Max pages", min_value=1, max_value=5000, value=5000)
    with c2:
        max_depth = st.number_input("Max crawl depth", min_value=1, max_value=50, value=12)
    with c3:
        concurrency = st.number_input("Concurrency", min_value=1, max_value=30, value=8)

    c4, c5, c6 = st.columns(3)
    with c4:
        respect_robots = st.checkbox("Respect robots.txt", value=True)
    with c5:
        use_sitemap = st.checkbox("Seed from sitemap.xml", value=True)
    with c6:
        include_subdomains = st.checkbox("Include subdomains", value=False)

    c7, c8 = st.columns(2)
    with c7:
        check_external_links = st.checkbox("Spot-check external links for broken (4xx/5xx) targets", value=False)
    with c8:
        run_performance = st.checkbox("Sample real Core Web Vitals (PageSpeed Insights)", value=False)

    with st.expander("Advanced — render_js (usually not a good idea on free hosting)"):
        st.caption(
            "Renders pages with a real headless browser instead of a plain HTTP fetch — "
            "fixes JS-heavy/SPA sites, but needs Playwright's Chromium binary installed and "
            "meaningfully more memory than most free hosting tiers give you. Likely to error "
            "out here; it's reliable in the Docker-based deployment instead."
        )
        render_js = st.checkbox("Render with a real browser anyway", value=False)

    submitted = st.form_submit_button("Run Audit →", use_container_width=True)

if submitted:
    if not start_url or not start_url.startswith(("http://", "https://")):
        st.error("Enter a URL that includes http:// or https://")
    else:
        config = CrawlConfig(
            start_url=start_url,
            max_pages=min(int(max_pages), 5000),
            max_depth=int(max_depth),
            concurrency=int(concurrency),
            respect_robots=respect_robots,
            use_sitemap=use_sitemap,
            include_subdomains=include_subdomains,
            render_js=render_js,
            check_external_links=check_external_links,
        )
        progress = CrawlProgress()
        prior_history = load_history(start_url)

        with st.spinner(f"Crawling {start_url} — this can take a while for larger sites…"):
            try:
                audit_data, _screenshots = asyncio.run(run_audit(
                    config, progress,
                    with_ai_summary=bool(os.environ.get("ANTHROPIC_API_KEY")),
                    run_performance=run_performance,
                    pagespeed_api_key=os.environ.get("PAGESPEED_API_KEY"),
                    history_records=prior_history,
                ))
                new_record = append_history(start_url, audit_data)
                audit_data["history"] = prior_history + [new_record]
                st.session_state.audit_data = audit_data
            except Exception as exc:
                st.error(f"Audit failed: {exc}")
                st.session_state.audit_data = None

data = st.session_state.audit_data

if data:
    scoring = data["scoring"]
    st.success(
        f"{data['meta']['pages_crawled']} pages crawled in {data['meta']['elapsed_seconds']}s — "
        f"UX Maturity {scoring['ux_maturity_score']}/100 ({scoring['ux_maturity_band']})"
    )

    tabs = st.tabs([
        "Overview", "Heuristics & Action Plan", "Content & Keywords",
        "Integrations & Features", "Journey Map", "Site Structure", "Page Inventory", "Exports",
    ])

    # ---------------- Overview ----------------
    with tabs[0]:
        cols = st.columns(5)
        score_fields = [
            ("UX Maturity", "ux_maturity_score"), ("IA Health", "ia_health_score"),
            ("Content", "content_quality_score"), ("Accessibility", "accessibility_score"),
            ("SEO", "seo_score"),
        ]
        for col, (label, key) in zip(cols, score_fields):
            col.metric(label, f"{scoring[key]}/100")

        st.subheader("In plain terms")
        for line in data["plain_summary"]:
            st.markdown("- " + line.replace("**", ""))

        if data.get("ai_summary"):
            st.subheader("Executive Summary (AI-generated)")
            st.write(data["ai_summary"])

        st.subheader("UX Lead's Assessment")
        for para in data["lead_assessment"]["paragraphs"]:
            st.write(para)

        if len(data.get("history", [])) > 1:
            st.subheader("Trend")
            hist_df = pd.DataFrame(data["history"])
            hist_df["date"] = hist_df["timestamp"].str[:10]
            st.line_chart(
                hist_df.set_index("date")[
                    ["ux_maturity_score", "ia_health_score", "accessibility_score"]
                ]
            )
        elif data.get("history"):
            st.caption("This is the first recorded audit for this domain — a trend will appear on your next run.")

        if data.get("performance", {}).get("sampled"):
            st.subheader("Real-World Performance (sampled)")
            st.caption(data["performance"]["note"])
            perf_df = pd.DataFrame(data["performance"]["results"])
            st.dataframe(perf_df, use_container_width=True)

        if data.get("link_health", {}).get("checked"):
            st.subheader("External Link Health")
            if data["link_health"]["broken"]:
                st.dataframe(pd.DataFrame(data["link_health"]["broken"]), use_container_width=True)
            else:
                st.caption("No broken external links found in the sample checked.")

    # ---------------- Heuristics & Action Plan ----------------
    with tabs[1]:
        st.subheader("Heuristic Evaluation")
        st.caption(
            f"{data['heuristics_summary']['assessed_count']} of 10 Nielsen heuristics can be "
            f"checked from a page crawl; the rest need a human walking through real interactions."
        )
        for h in data["heuristics"]:
            if not h["assessable"]:
                st.markdown(f"**{h['id'].upper()} · {h['name']}** — _not assessed: {h['why_not']}_")
            elif h["findings"]:
                with st.expander(f"{h['id'].upper()} · {h['name']} — severity {h['max_severity']}, {len(h['findings'])} finding(s)"):
                    for f in h["findings"]:
                        st.markdown(f"- {f['text']}")
            else:
                st.markdown(f"**{h['id'].upper()} · {h['name']}** — no issues found ✅")

        st.subheader("Prioritized Action Plan")
        plan_df = pd.DataFrame(scoring["action_plan"])
        if not plan_df.empty:
            st.dataframe(plan_df[["priority", "impact", "effort", "area", "action"]], use_container_width=True)
            st.caption("Impact vs. Effort")
            impact_map = {"Low": 1, "Medium": 2, "High": 3}
            plot_df = plan_df.assign(
                impact_n=plan_df["impact"].map(impact_map),
                effort_n=plan_df["effort"].map(impact_map),
            )
            st.scatter_chart(plot_df, x="effort_n", y="impact_n", color="priority")
        else:
            st.caption("No significant issues detected — nice work.")

    # ---------------- Content & Keywords ----------------
    with tabs[2]:
        st.subheader("Content Signals")
        content = data["content"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Avg word count", content["word_count_avg"])
        c2.metric("Thin content pages", content["thin_content_count"])
        c3.metric("Duplicate content pages", content["duplicate_content_page_count"])
        c4.metric("Image alt coverage", f"{content['image_alt_coverage_pct']}%")

        st.subheader("Most Used Keywords")
        kw = data.get("keywords", {}).get("top_keywords", [])
        if kw:
            kw_df = pd.DataFrame(kw).set_index("term")[["count"]]
            st.bar_chart(kw_df)
        phrases = data.get("keywords", {}).get("top_phrases", [])
        if phrases:
            st.caption("Top phrases (2 words)")
            st.dataframe(pd.DataFrame(phrases), use_container_width=True)

    # ---------------- Integrations ----------------
    with tabs[3]:
        integ = data.get("integrations", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("Unique external scripts", integ.get("unique_external_scripts", 0))
        c2.metric("Recognized integrations", len(integ.get("detected", [])))
        c3.metric("Avg scripts / page", integ.get("avg_scripts_per_page", 0))
        if integ.get("detected"):
            st.dataframe(pd.DataFrame(integ["detected"]), use_container_width=True)
        if integ.get("other_scripts"):
            st.caption("Other scripts found (unrecognized)")
            st.dataframe(pd.DataFrame(integ["other_scripts"]), use_container_width=True)

        st.subheader("Feature Matrix")
        st.caption(
            "Common website features detected from the actual markup crawled. "
            "\"Not detected\" means the pattern wasn't found — worth a manual check "
            "before treating it as confirmed absent, especially anything behind a login."
        )
        fm = data.get("feature_matrix", {})
        if fm.get("rows"):
            st.metric("Features detected", f"{fm['present_count']} / {fm['total_count']}")
            fm_df = pd.DataFrame(fm["rows"])[["name", "present", "page_count"]]
            fm_df.columns = ["Feature", "Detected", "Pages"]
            st.dataframe(fm_df, use_container_width=True)

    # ---------------- Journey Map ----------------
    with tabs[4]:
        st.caption(
            "Not real behavioral data — a crawler has no access to analytics or session "
            "recordings. This infers where each persona's goal-driven path most likely lives "
            "in the site's structure, and how many clicks it takes to reach each stage. Worth "
            "validating against real analytics. A persona with little presence likely just "
            "isn't a priority for this site — that's a signal, not a failure."
        )
        jm = data.get("journey_map", {})
        if jm.get("journeys"):
            st.metric("Personas with any presence", f"{jm['journeys_with_any_presence']} / {jm['journeys_total']}")
            journey_names = [j["name"] for j in jm["journeys"]]
            selected = st.selectbox("Persona", journey_names)
            journey = next(j for j in jm["journeys"] if j["name"] == selected)
            st.caption(journey["description"])
            st.write(f"**{journey['stages_present']} / {journey['stages_total']} stages found**")
            for stage in journey["stages"]:
                icon = "✅" if stage["present"] else "⚠️"
                with st.expander(f"{icon} {stage['name']}", expanded=stage["present"]):
                    st.write(stage["description"])
                    if stage["present"]:
                        st.caption(
                            f"{stage['page_count']} page(s) · closest example: {stage['example_url']} "
                            f"({stage['click_depth']} click(s) from home)"
                        )
                    else:
                        st.caption("No matching content found for this stage.")
            for note in journey.get("notes", []):
                st.info(note)

    # ---------------- Site Structure ----------------
    with tabs[5]:
        ia = data["ia"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Orphan pages", ia["orphan_page_count"])
        c2.metric("Max click depth", ia["max_click_depth"])
        c3.metric("Avg click depth", ia["avg_click_depth"])
        c4.metric("Pages >3 clicks deep", ia["pages_over_3_clicks"])

        st.subheader("Pages per top-level section")
        if ia.get("taxonomy"):
            st.bar_chart(pd.Series(ia["taxonomy"]))

        st.subheader("Most-linked-to pages")
        # a simple table stand-in for the FastAPI app's force-directed graph —
        # same underlying data (inbound link counts), simpler to render here
        inbound = {}
        for _src, dst in data.get("link_edges", []):
            inbound[dst] = inbound.get(dst, 0) + 1
        if inbound:
            top_linked = sorted(inbound.items(), key=lambda x: -x[1])[:20]
            st.dataframe(pd.DataFrame(top_linked, columns=["URL", "Inbound Links"]), use_container_width=True)

        if ia.get("orphan_pages"):
            st.subheader("Orphan pages (unreachable by clicking through the site)")
            st.dataframe(pd.DataFrame({"URL": ia["orphan_pages"]}), use_container_width=True)

    # ---------------- Page Inventory ----------------
    with tabs[6]:
        pages_df = pd.DataFrame(data["pages"].values())
        search = st.text_input("Filter by URL or title")
        if search:
            mask = pages_df["url"].str.contains(search, case=False, na=False) | \
                   pages_df["title"].str.contains(search, case=False, na=False)
            pages_df = pages_df[mask]
        st.dataframe(pages_df, use_container_width=True, height=500)

    # ---------------- Exports ----------------
    with tabs[7]:
        st.write("Download the full results in whichever format you need:")
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download JSON", export_json(data), file_name="audit.json", mime="application/json")
        c2.download_button("Download CSV", export_csv(data), file_name="audit.csv", mime="text/csv")
        c3.download_button(
            "Download Excel", export_xlsx(data), file_name="audit.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Enter a URL above and click **Run Audit** to get started.")
