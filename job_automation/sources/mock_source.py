from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..models import JobIngestRecord, build_job_id, utc_now_iso
from .base import JobSource


class MockJobSource(JobSource):
    def __init__(self, path: Path, source_name: str = "mock"):
        self.path = path
        self.source_name = source_name

    def fetch_jobs(self) -> List[JobIngestRecord]:
        if not self.path.exists():
            return []
        raw_items = json.loads(self.path.read_text(encoding="utf-8"))
        jobs: List[JobIngestRecord] = []
        for item in raw_items:
            external_id = str(item.get("external_id", "")).strip() or str(
                item.get("job_url", "")
            ).strip()
            if not external_id:
                external_id = f"{item.get('title_raw', '')}_{item.get('company', '')}"
            job_id = build_job_id(self.source_name, external_id)
            jobs.append(
                JobIngestRecord(
                    job_id=job_id,
                    source=self.source_name,
                    title_raw=str(item.get("title_raw", "")).strip(),
                    company=str(item.get("company", "")).strip(),
                    location=str(item.get("location", "")).strip(),
                    remote_type=str(item.get("remote_type", "hybrid")).strip(),
                    job_url=str(item.get("job_url", "")).strip(),
                    description_text=str(item.get("description_text", "")).strip(),
                    date_posted=str(item.get("date_posted", "")).strip(),
                    scraped_at=str(item.get("scraped_at", "")).strip() or utc_now_iso(),
                )
            )
        return jobs

