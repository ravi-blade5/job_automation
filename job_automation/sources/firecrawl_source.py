from __future__ import annotations

from datetime import date
import os
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qs, urlparse

from ..http_client import HttpClientError, request_json
from ..models import JobIngestRecord, build_job_id, utc_now_iso
from .base import JobSource


class FirecrawlJobSource(JobSource):
    def __init__(
        self,
        api_key: str,
        career_urls: List[str],
        max_links_per_domain: int = 15,
    ):
        self.api_key = api_key.strip()
        self.career_urls = [url.strip() for url in career_urls if url.strip()]
        self.max_links_per_domain = max(max_links_per_domain, 1)

    def fetch_jobs(self) -> List[JobIngestRecord]:
        if not self.api_key or not self.career_urls:
            return []

        jobs: List[JobIngestRecord] = []
        seen_external_ids = set()
        for url in self.career_urls:
            company = _extract_company(url)
            links = self._discover_job_links(url)
            for link in links:
                try:
                    record = self._extract_job_record(link, company)
                except Exception as exc:
                    if _debug_sources():
                        print(f"[firecrawl] extract_error link={link} error={exc}")
                    continue
                if not record:
                    continue
                external_id = _derive_external_id(record.job_url, record.title_raw)
                if external_id in seen_external_ids:
                    continue
                seen_external_ids.add(external_id)
                record.job_id = build_job_id("company_site", external_id)
                jobs.append(record)
        return jobs

    def _discover_job_links(self, careers_url: str) -> List[str]:
        mapped_links = self._map_links(careers_url)
        if not mapped_links:
            mapped_links = self._scrape_links(careers_url)
        if not mapped_links:
            return []
        candidates = _filter_job_links(mapped_links, careers_url)
        ranked = _rank_links(candidates)
        deduped: List[str] = []
        seen = set()
        for link in ranked:
            normalized = link.strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(link)
        return deduped[: self.max_links_per_domain]

    def _map_links(self, careers_url: str) -> List[str]:
        try:
            response = request_json(
                method="POST",
                url="https://api.firecrawl.dev/v1/map",
                headers=self._headers,
                payload={"url": careers_url},
            )
        except Exception as exc:
            if _debug_sources():
                print(f"[firecrawl] map_error url={careers_url} error={exc}")
            return []
        return _extract_links_from_map_response(response.body)

    def _scrape_links(self, careers_url: str) -> List[str]:
        try:
            response = request_json(
                method="POST",
                url="https://api.firecrawl.dev/v1/scrape",
                headers=self._headers,
                payload={"url": careers_url, "formats": ["links"]},
            )
        except Exception as exc:
            if _debug_sources():
                print(f"[firecrawl] scrape_links_error url={careers_url} error={exc}")
            return []
        data = response.body.get("data", {})
        links = []
        if isinstance(data, dict):
            raw_links = data.get("links", [])
            if isinstance(raw_links, list):
                links = [str(item).strip() for item in raw_links if str(item).strip()]
        return links

    def _extract_job_record(self, job_url: str, company: str) -> JobIngestRecord | None:
        extracted = self._scrape_structured(job_url)
        if not extracted:
            return None

        title = str(extracted.get("title", "")).strip()
        if not title:
            return None
        if _looks_like_non_job_title(title):
            return None

        apply_url = str(extracted.get("apply_url", "")).strip() or job_url
        description_text = str(extracted.get("description_text", "")).strip()
        if not description_text:
            description_text = str(extracted.get("markdown", "")).strip()
        if not description_text:
            description_text = title

        location = str(extracted.get("location", "")).strip()
        remote_type = _normalize_remote_type(str(extracted.get("remote_type", "")).strip())
        date_posted = _normalize_date(str(extracted.get("date_posted", "")).strip())
        company_name = str(extracted.get("company", "")).strip() or company

        return JobIngestRecord(
            job_id="",  # set by caller after external id derivation
            source="company_site",
            title_raw=title,
            company=company_name,
            location=location,
            remote_type=remote_type,
            job_url=apply_url,
            description_text=description_text,
            date_posted=date_posted,
            scraped_at=utc_now_iso(),
        )

    def _scrape_structured(self, job_url: str) -> Dict[str, str]:
        payload = {
            "url": job_url,
            "formats": ["json", "markdown"],
            "jsonOptions": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "location": {"type": "string"},
                        "remote_type": {"type": "string"},
                        "date_posted": {"type": "string"},
                        "description_text": {"type": "string"},
                        "apply_url": {"type": "string"},
                    },
                    "required": ["title"],
                },
                "prompt": (
                    "Extract job posting data. Return blank fields if unavailable. "
                    "If this page is not a job posting, set title to blank."
                ),
            },
        }
        try:
            response = request_json(
                method="POST",
                url="https://api.firecrawl.dev/v1/scrape",
                headers=self._headers,
                payload=payload,
            )
        except Exception as exc:
            if _debug_sources():
                print(f"[firecrawl] scrape_structured_error url={job_url} error={exc}")
            return {}
        data = response.body.get("data", {})
        if not isinstance(data, dict):
            return {}
        json_data = data.get("json", {})
        extracted: Dict[str, str] = {}
        if isinstance(json_data, dict):
            extracted.update(
                {
                    "job_id": str(json_data.get("job_id", "")).strip(),
                    "title": str(json_data.get("title", "")).strip(),
                    "company": str(json_data.get("company", "")).strip(),
                    "location": str(json_data.get("location", "")).strip(),
                    "remote_type": str(json_data.get("remote_type", "")).strip(),
                    "date_posted": str(json_data.get("date_posted", "")).strip(),
                    "description_text": str(json_data.get("description_text", "")).strip(),
                    "apply_url": str(json_data.get("apply_url", "")).strip(),
                }
            )

        markdown = str(data.get("markdown", "")).strip()
        if markdown:
            extracted["markdown"] = markdown
        if not extracted.get("title"):
            extracted["title"] = _extract_title(markdown, job_url)
        if not extracted.get("apply_url"):
            extracted["apply_url"] = job_url
        return extracted

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}


def _extract_links_from_map_response(body: Dict[str, Any]) -> List[str]:
    links: List[str] = []

    direct = body.get("links")
    if isinstance(direct, list):
        links.extend(str(item).strip() for item in direct if str(item).strip())

    data = body.get("data")
    if isinstance(data, dict):
        nested_links = data.get("links")
        if isinstance(nested_links, list):
            links.extend(str(item).strip() for item in nested_links if str(item).strip())
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for key in ("url", "link"):
                    value = str(item.get(key, "")).strip()
                    if value:
                        links.append(value)
            elif isinstance(item, str) and item.strip():
                links.append(item.strip())
    return links


def _filter_job_links(links: Iterable[str], careers_url: str) -> List[str]:
    base_host = _host(careers_url)
    filtered: List[str] = []
    for link in links:
        candidate = link.strip()
        if not candidate.startswith(("http://", "https://")):
            continue
        if _is_obviously_non_job_link(candidate):
            continue
        if not _is_same_or_known_job_board(base_host, _host(candidate)):
            continue
        if not _is_specific_job_url(candidate):
            continue
        if _looks_like_job_link(candidate):
            filtered.append(candidate)
    return filtered


def _rank_links(links: List[str]) -> List[str]:
    def score(url: str) -> int:
        lowered = url.lower()
        value = 0
        priority_patterns = [
            "greenhouse.io",
            "boards.greenhouse.io",
            "jobs.lever.co",
            "myworkdayjobs.com",
            "ashbyhq.com",
            "smartrecruiters.com",
            "/jobs/",
            "/job/",
            "/openings/",
            "/positions/",
            "/careers/",
            "/career/",
            "jobid=",
            "requisition",
            "reqid=",
        ]
        for pattern in priority_patterns:
            if pattern in lowered:
                value += 2
        if "/team" in lowered or "/about" in lowered:
            value -= 2
        return value

    return sorted(links, key=score, reverse=True)


def _is_same_or_known_job_board(base_host: str, candidate_host: str) -> bool:
    if not candidate_host:
        return False
    if candidate_host == base_host or candidate_host.endswith(f".{base_host}"):
        return True
    known = (
        "greenhouse.io",
        "lever.co",
        "myworkdayjobs.com",
        "ashbyhq.com",
        "smartrecruiters.com",
    )
    return any(candidate_host.endswith(host) for host in known)


def _is_obviously_non_job_link(url: str) -> bool:
    lowered = url.lower()
    blocked_prefixes = ("mailto:", "tel:", "javascript:")
    if lowered.startswith(blocked_prefixes):
        return True
    blocked_contains = (
        "/privacy",
        "/terms",
        "/cookie",
        "/cookies",
        "/contact",
        "/about",
        "/blog",
        "/news",
        "/press",
        "linkedin.com/company",
        "facebook.com",
        "instagram.com",
        "x.com/",
        "twitter.com/",
        "youtube.com/",
    )
    return any(pattern in lowered for pattern in blocked_contains)


def _looks_like_job_link(url: str) -> bool:
    lowered = url.lower()
    positive_patterns = (
        "/job/",
        "/jobs/",
        "/careers/",
        "/career/",
        "/openings/",
        "/positions/",
        "/vacan",
        "jobid=",
        "reqid=",
        "requisition",
        "greenhouse.io",
        "lever.co",
        "myworkdayjobs.com",
        "ashbyhq.com",
        "smartrecruiters.com",
    )
    return any(pattern in lowered for pattern in positive_patterns)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def _extract_company(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    return host.split(".")[0].replace("-", " ").title() if host else "Unknown"


def _extract_title(markdown: str, fallback_url: str) -> str:
    if markdown:
        for line in markdown.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped and len(stripped) > 3:
                return stripped[:140]
    parsed = urlparse(fallback_url)
    fragment = parsed.path.strip("/").split("/")[-1].replace("-", " ").replace("_", " ")
    return fragment.title() if fragment else fallback_url


def _normalize_date(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        return date.today().isoformat()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
        return candidate
    if "T" in candidate:
        try:
            return candidate.split("T", 1)[0]
        except ValueError:
            pass
    common = re.search(r"(\d{4}-\d{2}-\d{2})", candidate)
    if common:
        return common.group(1)
    return date.today().isoformat()


def _normalize_remote_type(raw: str) -> str:
    lowered = raw.strip().lower()
    if "remote" in lowered:
        return "remote"
    if "hybrid" in lowered:
        return "hybrid"
    if "onsite" in lowered or "on-site" in lowered or "office" in lowered:
        return "onsite"
    return "unknown"


def _derive_external_id(job_url: str, title_raw: str) -> str:
    parsed = urlparse(job_url)
    raw_query = parse_qs(parsed.query)
    query = {str(k).lower(): v for k, v in raw_query.items()}
    for key in ("gh_jid", "jobid", "job_id", "reqid", "requisitionid", "id"):
        value = query.get(key)
        if value and str(value[0]).strip():
            return f"{parsed.netloc}:{key}:{str(value[0]).strip()}"

    path = parsed.path.strip("/")
    if path:
        parts = [part for part in path.split("/") if part]
        if parts:
            tail = parts[-1]
            return f"{parsed.netloc}:{tail}"
    slug = re.sub(r"[^a-z0-9]+", "-", title_raw.lower()).strip("-")
    return f"{parsed.netloc}:{slug or 'job'}"


def _looks_like_non_job_title(title: str) -> bool:
    lowered = title.strip().lower()
    blocked = (
        "careers",
        "career opportunities",
        "job openings",
        "join us",
        "home",
        "about us",
        "the job you are looking for is no longer open.",
        "the job you are looking for is no longer open",
        "job not found",
        "this job is no longer available",
    )
    if lowered in blocked:
        return True
    return len(lowered.split()) < 2


def _is_specific_job_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()
    query = parse_qs(parsed.query)

    # Strong signal: explicit job id parameters.
    for key in ("gh_jid", "jobid", "job_id", "reqid", "requisitionid", "id"):
        if key in {k.lower() for k in query.keys()}:
            return True

    if not path:
        return False

    generic_paths = {
        "jobs",
        "job",
        "careers",
        "career",
        "openings",
        "positions",
    }
    if path in generic_paths:
        return False

    # Keep known board patterns even if compact.
    host = parsed.netloc.lower()
    if any(
        host.endswith(board)
        for board in ("greenhouse.io", "lever.co", "myworkdayjobs.com", "ashbyhq.com", "smartrecruiters.com")
    ):
        return True

    # Requires at least one non-generic trailing segment.
    segments = [s for s in path.split("/") if s]
    if not segments:
        return False
    if segments[-1] in generic_paths:
        return False
    return len(segments) >= 2 or bool(re.search(r"\d", segments[-1]))


def _debug_sources() -> bool:
    raw = os.getenv("JOB_AUTOMATION_DEBUG_SOURCES", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
