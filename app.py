"""Site Blueprint — Enterprise Website IA & UX Audit tool.

Run with:
    uvicorn app:app --reload --port 8000
then open http://localhost:8000
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from audit_engine import run_audit
from crawler import CrawlConfig
from models import AuditStatus, CrawlProgress
from report_builder import export_csv, export_json, export_xlsx, render_html_report

app = FastAPI(title="Site Blueprint — IA/UX Audit")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

GRAPH_NODE_CAP = 250
MAX_PAGES_HARD_CAP = 5000

# In-memory audit store. For multi-process / multi-worker deployments this
# would move to Redis or a DB — kept simple here since this is a
# single-process local tool, not the multi-tenant SaaS version of the spec.
_audits: dict[str, dict] = {}


class StartAuditRequest(BaseModel):
    start_url: str
    max_pages: int = Field(default=5000, ge=1, le=MAX_PAGES_HARD_CAP)
    max_depth: int = Field(default=12, ge=1, le=50)
    concurrency: int = Field(default=8, ge=1, le=30)
    respect_robots: bool = True
    use_sitemap: bool = True
    include_subdomains: bool = False


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (Path(__file__).parent / "templates" / "index.html").read_text()
    return HTMLResponse(html)


@app.post("/api/audits")
async def start_audit(req: StartAuditRequest):
    if not (req.start_url.startswith("http://") or req.start_url.startswith("https://")):
        raise HTTPException(400, "start_url must include http:// or https://")

    audit_id = uuid.uuid4().hex[:12]
    progress = CrawlProgress()
    _audits[audit_id] = {"progress": progress, "result": None, "error": None}

    config = CrawlConfig(
        start_url=req.start_url,
        max_pages=min(req.max_pages, MAX_PAGES_HARD_CAP),
        max_depth=req.max_depth,
        concurrency=req.concurrency,
        include_subdomains=req.include_subdomains,
        respect_robots=req.respect_robots,
        use_sitemap=req.use_sitemap,
    )

    async def task():
        try:
            result = await run_audit(config, progress)
            result["audit_id"] = audit_id
            _audits[audit_id]["result"] = result
        except Exception as exc:  # surfaced via /status so the UI doesn't hang
            progress.status = AuditStatus.ERROR
            progress.note(f"Fatal error: {exc}")
            _audits[audit_id]["error"] = str(exc)

    asyncio.create_task(task())
    return {"audit_id": audit_id}


@app.get("/api/audits/{audit_id}/status")
async def audit_status(audit_id: str):
    entry = _audits.get(audit_id)
    if not entry:
        raise HTTPException(404, "audit not found")
    p: CrawlProgress = entry["progress"]
    return {
        "status": p.status.value,
        "pages_crawled": p.pages_crawled,
        "pages_queued": p.pages_queued,
        "pages_errored": p.pages_errored,
        "max_pages": p.max_pages,
        "current_url": p.current_url,
        "elapsed_seconds": p.elapsed_seconds,
        "eta_seconds": p.eta_seconds,
        "log": p.log[-40:],
        "error": entry.get("error"),
    }


@app.get("/api/audits/{audit_id}/report", response_class=HTMLResponse)
async def audit_report(audit_id: str):
    entry = _audits.get(audit_id)
    if not entry:
        raise HTTPException(404, "audit not found")
    if entry["result"] is None:
        raise HTTPException(409, "audit not finished yet")
    html = render_html_report(entry["result"], graph_cap=GRAPH_NODE_CAP)
    return HTMLResponse(html)


@app.get("/api/audits/{audit_id}/export/json")
async def export_json_route(audit_id: str):
    entry = _require_done(audit_id)
    return Response(export_json(entry["result"]), media_type="application/json",
                     headers={"Content-Disposition": f"attachment; filename=audit_{audit_id}.json"})


@app.get("/api/audits/{audit_id}/export/csv")
async def export_csv_route(audit_id: str):
    entry = _require_done(audit_id)
    return Response(export_csv(entry["result"]), media_type="text/csv",
                     headers={"Content-Disposition": f"attachment; filename=audit_{audit_id}.csv"})


@app.get("/api/audits/{audit_id}/export/xlsx")
async def export_xlsx_route(audit_id: str):
    entry = _require_done(audit_id)
    return Response(
        export_xlsx(entry["result"]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=audit_{audit_id}.xlsx"},
    )


def _require_done(audit_id: str) -> dict:
    entry = _audits.get(audit_id)
    if not entry:
        raise HTTPException(404, "audit not found")
    if entry["result"] is None:
        raise HTTPException(409, "audit not finished yet")
    return entry
