"""Persists a compact score record per audit run, keyed by domain, so
repeat audits of the same site build a trend over time.

This has to be a file committed to the repo, not something written into
docs/ — docs/ is regenerated from scratch by every workflow run (see
.gitignore) and published as a throwaway build artifact, so nothing
written there survives to the next run. A small JSON-lines file per
domain, committed back to the repo by the workflow, is what actually
persists.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HISTORY_DIR = Path(__file__).parent / "history"


def slug_for(url: str) -> str:
    netloc = urlparse(url).netloc or url
    return re.sub(r"[^a-zA-Z0-9._-]", "-", netloc).strip("-").lower() or "site"


def history_path(url: str) -> Path:
    return HISTORY_DIR / f"{slug_for(url)}.jsonl"


def load_history(url: str, cap: int = 100) -> list[dict]:
    path = history_path(url)
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records[-cap:]


def append_history(url: str, audit_data: dict) -> dict:
    """Writes the new record to disk and returns it (for embedding in the
    current report alongside whatever load_history() returned beforehand).
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    scoring = audit_data["scoring"]
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "start_url": audit_data["meta"]["start_url"],
        "pages_crawled": audit_data["meta"]["pages_crawled"],
        "ux_maturity_score": scoring["ux_maturity_score"],
        "ia_health_score": scoring["ia_health_score"],
        "content_quality_score": scoring["content_quality_score"],
        "accessibility_score": scoring["accessibility_score"],
        "seo_score": scoring["seo_score"],
    }
    path = history_path(url)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record
