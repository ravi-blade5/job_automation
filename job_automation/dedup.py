from __future__ import annotations

import re
from typing import Dict, Iterable, List

from .models import JobIngestRecord


def normalize_text(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return re.sub(r"[^a-z0-9 ]", "", lowered)


def dedupe_jobs(records: Iterable[JobIngestRecord]) -> List[JobIngestRecord]:
    by_key: Dict[str, JobIngestRecord] = {}
    for record in records:
        key = _dedupe_key(record)
        existing = by_key.get(key)
        if not existing:
            by_key[key] = record
            continue
        if record.date_posted > existing.date_posted:
            by_key[key] = record
    return list(by_key.values())


def _dedupe_key(record: JobIngestRecord) -> str:
    if record.job_url.strip():
        return normalize_text(record.job_url)
    combined = "|".join(
        [
            normalize_text(record.title_raw),
            normalize_text(record.company),
            normalize_text(record.location),
        ]
    )
    return combined

