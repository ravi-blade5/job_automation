from __future__ import annotations

import os
from typing import Any, Dict, List
from urllib.parse import urlparse

from ..http_client import HttpClientError, request_json
from ..models import JobIngestRecord, build_job_id, utc_now_iso
from .base import JobSource


class ApifyJobSource(JobSource):
    def __init__(self, api_token: str, dataset_ids: List[str], fetch_limit: int = 25):
        self.api_token = api_token.strip()
        self.dataset_ids = [item.strip() for item in dataset_ids if item.strip()]
        self.fetch_limit = max(int(fetch_limit or 0), 0)
        self.last_errors: List[str] = []
        self.last_item_count: int = 0
        self.last_mapped_count: int = 0

    def fetch_jobs(self) -> List[JobIngestRecord]:
        if not self.api_token or not self.dataset_ids:
            return []
        jobs: List[JobIngestRecord] = []
        self.last_errors = []
        self.last_item_count = 0
        self.last_mapped_count = 0
        for dataset_id in self.dataset_ids:
            limit_query = f"&limit={self.fetch_limit}" if self.fetch_limit else ""
            url = (
                f"https://api.apify.com/v2/datasets/{dataset_id}/items"
                f"?clean=true&format=json&token={self.api_token}{limit_query}"
            )
            try:
                response = request_json("GET", url)
            except HttpClientError as exc:
                safe_error = _redact_apify_token(str(exc), self.api_token)
                self.last_errors.append(f"{dataset_id}: {safe_error}")
                if _debug_sources():
                    print(f"[apify] dataset={dataset_id} fetch_error={safe_error}")
                continue
            items = _extract_items(response.body)
            if not isinstance(items, list):
                self.last_errors.append(f"{dataset_id}: unexpected response shape")
                continue
            self.last_item_count += len(items)
            for item in items:
                if not isinstance(item, dict):
                    continue
                mapped = _map_apify_item(item)
                if mapped:
                    jobs.append(mapped)
                elif _debug_sources():
                    keys = sorted(list(item.keys()))[:15]
                    print(f"[apify] skipped_item keys={keys}")
        self.last_mapped_count = len(jobs)
        if _debug_sources():
            print(
                f"[apify] datasets={len(self.dataset_ids)} raw_items={self.last_item_count} mapped={self.last_mapped_count} errors={len(self.last_errors)}"
            )
        return jobs


def _map_apify_item(item: Dict[str, Any]) -> JobIngestRecord | None:
    source = "apify"
    title = _first_non_empty(
        item,
        "title",
        "positionName",
        "jobTitle",
        "name",
        "job.title",
        "position.title",
    )
    company = _first_non_empty(
        item,
        "companyName",
        "company",
        "organization",
        "company.name",
        "organization.name",
        "hiringOrganization.name",
    )
    location = _first_non_empty(
        item,
        "location",
        "jobLocation",
        "locationName",
        "location.name",
        "jobLocation.name",
    )
    remote_type = _first_non_empty(
        item,
        "remoteType",
        "workType",
        "employmentType",
        "workplaceType",
        default="unknown",
    )
    description = _first_non_empty(
        item,
        "description",
        "jobDescription",
        "text",
        "details",
        "snippet",
    )
    job_url = _first_non_empty(
        item,
        "url",
        "jobUrl",
        "applyUrl",
        "link",
        "job.url",
        "urlData.url",
    )
    external_id = _first_non_empty(
        item,
        "id",
        "jobId",
        "job.id",
        "listingId",
        default=job_url or f"{title}_{company}",
    )
    date_posted = _first_non_empty(
        item,
        "datePosted",
        "postedAt",
        "publishDate",
        "createdAt",
        "updatedAt",
    )

    if not company and job_url:
        company = _company_from_url(job_url)

    # Accept records with either (title+company) or (title+job_url).
    if not title or (not company and not job_url):
        return None
    job_id = build_job_id(source, external_id)
    return JobIngestRecord(
        job_id=job_id,
        source=source,
        title_raw=title,
        company=company or "Unknown",
        location=location,
        remote_type=remote_type.lower() or "unknown",
        job_url=job_url,
        description_text=description,
        date_posted=date_posted,
        scraped_at=utc_now_iso(),
    )


def _first_non_empty(item: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = _deep_get(item, key)
        if value is None:
            continue
        if isinstance(value, list):
            joined = " | ".join(str(v).strip() for v in value if str(v).strip())
            if joined:
                return joined
            continue
        if isinstance(value, dict):
            for nested_key in ("name", "title", "value", "text"):
                nested = value.get(nested_key)
                if nested is not None and str(nested).strip():
                    return str(nested).strip()
            continue
        text = str(value).strip()
        if text:
            return text
    return default.strip()


def _deep_get(item: Dict[str, Any], key_path: str) -> Any:
    if "." not in key_path:
        return item.get(key_path)
    current: Any = item
    for part in key_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _extract_items(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("items", "data", "results"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _company_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    if not host:
        return "Unknown"
    return host.split(".")[0].replace("-", " ").title()


def _debug_sources() -> bool:
    raw = os.getenv("JOB_AUTOMATION_DEBUG_SOURCES", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _redact_apify_token(text: str, token: str) -> str:
    if token:
        return text.replace(token, "<redacted>")
    return text
