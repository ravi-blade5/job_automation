from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.parse import urlparse

from .http_client import HttpClientError, request_json
from .models import (
    ActivityLogRecord,
    ApplicationRecord,
    ApplicationStatus,
    CompanyContextRecord,
    ContactChannel,
    ContactRecord,
    FitScoreRecord,
    JobIngestRecord,
)
from .tracking.repository import TrackingRepository

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
NO_REPLY_RE = re.compile(r"\b(?:no-?reply|donotreply|do-not-reply)\b", re.IGNORECASE)
GENERIC_EMAIL_HINTS = ("careers", "jobs", "recruit", "recruiting", "talent", "hr", "hiring")
VENDOR_EMAIL_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "ashbyhq.com",
    "smartrecruiters.com",
)
RESULT_KEYWORDS = (
    "careers",
    "career",
    "recruit",
    "recruiting",
    "talent",
    "hiring",
    "people",
    "jobs",
    "contact",
    "team",
)
BLOCKED_RESULT_HOSTS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)
LOW_CONFIDENCE_RESULT_HOSTS = (
    "contactout.com",
    "rocketreach.co",
    "rocketreach.com",
    "zoominfo.com",
    "signalhire.com",
    "lusha.com",
    "seamless.ai",
    "jobgether.com",
    "dice.com",
)
FREE_EMAIL_DOMAINS = (
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
)
NON_WORK_TLDS = ("webp", "png", "jpg", "jpeg", "svg", "gif", "ico", "avif")
OUTREACH_HEADERS = [
    "application_id",
    "job_id",
    "company",
    "job_title",
    "department_hint",
    "role_track",
    "decision",
    "fit_score",
    "location",
    "remote_type",
    "job_url",
    "contact_status",
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_source_url",
    "contact_notes",
    "cover_letter_focus",
]


@dataclass(frozen=True)
class OutreachLead:
    application_id: str
    job_id: str
    company: str
    job_title: str
    department_hint: str
    role_track: str
    decision: str
    fit_score: int
    location: str
    remote_type: str
    job_url: str
    contact_status: str
    contact_name: str
    contact_role: str
    contact_email: str
    contact_source_url: str
    contact_notes: str
    cover_letter_focus: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "application_id": self.application_id,
            "job_id": self.job_id,
            "company": self.company,
            "job_title": self.job_title,
            "department_hint": self.department_hint,
            "role_track": self.role_track,
            "decision": self.decision,
            "fit_score": self.fit_score,
            "location": self.location,
            "remote_type": self.remote_type,
            "job_url": self.job_url,
            "contact_status": self.contact_status,
            "contact_name": self.contact_name,
            "contact_role": self.contact_role,
            "contact_email": self.contact_email,
            "contact_source_url": self.contact_source_url,
            "contact_notes": self.contact_notes,
            "cover_letter_focus": self.cover_letter_focus,
        }


@dataclass(frozen=True)
class OutreachExportResult:
    leads_built: int
    contacts_discovered: int
    csv_path: Path
    json_path: Path


class FirecrawlContactFinder:
    def __init__(
        self,
        api_key: str,
        search_limit: int = 6,
        max_contacts_per_job: int = 5,
    ):
        self.api_key = api_key.strip()
        self.search_limit = max(int(search_limit or 0), 1)
        self.max_contacts_per_job = max(int(max_contacts_per_job or 0), 1)

    def discover(self, job: JobIngestRecord) -> List[ContactRecord]:
        if not self.api_key or not job.company.strip():
            return []

        company_domain = _extract_company_domain(job.job_url)
        team_hint = infer_department_hint(job)
        candidates: Dict[str, tuple[int, ContactRecord]] = {}
        for query in _build_contact_queries(job, team_hint=team_hint):
            for result in self._search(query):
                source_url = str(result.get("url", "")).strip()
                markdown = str(result.get("markdown", "")).strip()
                title = str(result.get("title", "")).strip()
                description = str(result.get("description", "")).strip()
                if not _is_promising_result(job, source_url, title, description, markdown):
                    continue
                for contact in _extract_contacts_from_markdown(
                    job=job,
                    markdown=markdown,
                    source_url=source_url,
                ):
                    score = _contact_priority(contact, company_domain=company_domain, team_hint=team_hint)
                    existing = candidates.get(contact.contact_id)
                    if existing is None or score > existing[0]:
                        candidates[contact.contact_id] = (score, contact)

        if not candidates and job.job_url.strip():
            markdown = self._scrape_markdown(job.job_url)
            for contact in _extract_contacts_from_markdown(
                job=job,
                markdown=markdown,
                source_url=job.job_url,
            ):
                score = _contact_priority(contact, company_domain=company_domain, team_hint=team_hint)
                candidates[contact.contact_id] = (score, contact)

        ordered = sorted(
            candidates.values(),
            key=lambda item: item[0],
            reverse=True,
        )
        return [item[1] for item in ordered[: self.max_contacts_per_job]]

    def _search(self, query: str) -> List[Dict[str, object]]:
        try:
            response = request_json(
                method="POST",
                url="https://api.firecrawl.dev/v1/search",
                headers={"Authorization": f"Bearer {self.api_key}"},
                payload={
                    "query": query,
                    "limit": self.search_limit,
                    "scrapeOptions": {"formats": ["markdown"]},
                },
            )
        except HttpClientError:
            return []
        data = response.body.get("data", [])
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _scrape_markdown(self, url: str) -> str:
        try:
            response = request_json(
                method="POST",
                url="https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {self.api_key}"},
                payload={"url": url, "formats": ["markdown"]},
            )
        except HttpClientError:
            return ""
        data = response.body.get("data", {})
        if not isinstance(data, dict):
            return ""
        return str(data.get("markdown", "")).strip()


class ManualOutreachLeadBuilder:
    def __init__(
        self,
        tracker: TrackingRepository,
        artifacts_root: Path,
        contact_finder: FirecrawlContactFinder | None = None,
    ):
        self.tracker = tracker
        self.artifacts_root = artifacts_root
        self.contact_finder = contact_finder
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def build_export(self, refresh_contacts: bool = False) -> OutreachExportResult:
        jobs = {job.job_id: job for job in self.tracker.list_jobs()}
        company_context = self.tracker.list_company_context()
        active_apps = [
            app
            for app in self.tracker.list_applications()
            if app.status not in (ApplicationStatus.REJECTED, ApplicationStatus.CLOSED)
        ]

        contacts_discovered = 0
        if self.contact_finder:
            for application in active_apps:
                job = jobs.get(application.job_id)
                if not job:
                    continue
                existing_contacts = self.tracker.list_contacts(job_id=job.job_id)
                if existing_contacts and not refresh_contacts:
                    continue
                discovered = self.contact_finder.discover(job)
                for contact in discovered:
                    self.tracker.upsert_contact(contact)
                if discovered:
                    contacts_discovered += len(discovered)
                    self.tracker.add_activity(
                        ActivityLogRecord.create(
                            entity_type="job",
                            entity_id=job.job_id,
                            event="contacts_discovered",
                            details=f"contacts={len(discovered)}",
                        )
                    )

        leads: List[OutreachLead] = []
        for application in active_apps:
            job = jobs.get(application.job_id)
            if not job:
                continue
            fit = self.tracker.get_fit_score(job.job_id, application.role_track.value)
            context = company_context.get(job.company.strip().lower())
            job_contacts = sorted(
                self.tracker.list_contacts(job_id=job.job_id),
                key=lambda contact: _contact_priority(
                    contact,
                    company_domain=_extract_company_domain(job.job_url),
                    team_hint=infer_department_hint(job),
                ),
                reverse=True,
            )
            if job_contacts:
                for contact in job_contacts:
                    leads.append(
                        _build_lead_row(
                            application=application,
                            job=job,
                            fit=fit,
                            context=context,
                            contact=contact,
                        )
                    )
                continue
            leads.append(
                _build_lead_row(
                    application=application,
                    job=job,
                    fit=fit,
                    context=context,
                    contact=None,
                )
            )

        export_dir = self.artifacts_root / "outreach"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        csv_path = export_dir / f"manual_outreach_leads_{stamp}.csv"
        json_path = export_dir / f"manual_outreach_leads_{stamp}.json"
        _write_leads_csv(csv_path, leads)
        _write_leads_json(json_path, leads)
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="pipeline",
                entity_id="manual_outreach_export",
                event="outreach_export_built",
                details=f"leads={len(leads)}, contacts_discovered={contacts_discovered}",
            )
        )
        return OutreachExportResult(
            leads_built=len(leads),
            contacts_discovered=contacts_discovered,
            csv_path=csv_path,
            json_path=json_path,
        )


def _build_contact_queries(job: JobIngestRecord, *, team_hint: str) -> List[str]:
    company = job.company.strip()
    domain = _extract_company_domain(job.job_url)
    title_hint = _trim_text(job.title_raw, 80)
    targets = _contact_target_terms(team_hint=team_hint, title_hint=title_hint)
    queries: list[str] = []
    if domain:
        queries.append(f'site:{domain} "{company}" careers recruiting email')
        queries.append(f'site:{domain} "{company}" talent acquisition email')
        for target in targets:
            queries.append(f'site:{domain} "{company}" {target} email')
            queries.append(f'site:{domain} "{company}" {target} team')
    queries.append(f'"{company}" careers recruiting email')
    queries.append(f'"{company}" talent acquisition hiring email')
    for target in targets:
        queries.append(f'"{company}" {target} email')
    return _dedupe_preserve_order(queries)[:10]


def _contact_target_terms(*, team_hint: str, title_hint: str) -> list[str]:
    targets = [title_hint, "GenAI", "AI team"]
    lowered = team_hint.lower()
    if "solutions" in lowered or "presales" in lowered:
        targets.extend(
            [
                "AI solution expert",
                "GenAI solutions",
                "solutions consultant",
                "solution architect",
                "customer engineering",
                "presales",
                "sales engineering",
                "hiring manager",
            ]
        )
    elif "product" in lowered or "strategy" in lowered:
        targets.extend(
            [
                "AI product",
                "GenAI product",
                "product leadership",
                "hiring manager",
            ]
        )
    elif "engineering" in lowered or "platform" in lowered:
        targets.extend(
            [
                "AI engineering",
                "ML platform",
                "applied AI",
                "engineering leadership",
                "hiring manager",
            ]
        )
    else:
        targets.extend(
            [
                "AI leadership",
                "GenAI leadership",
                "talent acquisition",
                "hiring manager",
            ]
        )
    return [item.strip() for item in targets if item.strip()]


def _extract_company_domain(job_url: str) -> str:
    host = urlparse(job_url.strip()).netloc.lower().replace("www.", "")
    if not host or host.endswith(VENDOR_EMAIL_DOMAINS):
        return ""
    return host


def _is_promising_result(
    job: JobIngestRecord,
    source_url: str,
    title: str,
    description: str,
    markdown: str,
) -> bool:
    host = urlparse(source_url).netloc.lower().replace("www.", "")
    if not host:
        return False
    if any(host.endswith(blocked) for blocked in BLOCKED_RESULT_HOSTS):
        return False
    haystack = " ".join([source_url, title, description, markdown[:500]]).lower()
    if job.company.strip().lower() not in haystack:
        return False
    if "@" in haystack:
        return True
    return any(keyword in haystack for keyword in RESULT_KEYWORDS)


def _extract_contacts_from_markdown(
    job: JobIngestRecord,
    markdown: str,
    source_url: str,
) -> List[ContactRecord]:
    if not markdown.strip():
        return []

    results: Dict[str, ContactRecord] = {}
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    fallback_department = infer_department_hint(job)

    for index, line in enumerate(lines):
        emails = [email.strip().lower() for email in EMAIL_RE.findall(line)]
        if not emails:
            continue
        window_lines = lines[max(0, index - 2) : min(len(lines), index + 3)]
        window = " | ".join(window_lines)
        for email in emails:
            if _should_skip_email(email):
                continue
            role = _infer_contact_role(window)
            name = _infer_contact_name(window, email)
            department = _infer_contact_department(role, fallback_department)
            notes = _trim_text(window, 220)
            contact = ContactRecord.create(
                job_id=job.job_id,
                company=job.company,
                contact_value=email,
                channel=ContactChannel.EMAIL,
                name=name,
                role=role,
                department=department,
                source_url=source_url,
                notes=notes,
            )
            existing = results.get(contact.contact_id)
            if existing is None or _contact_priority(contact) > _contact_priority(existing):
                results[contact.contact_id] = contact
    return list(results.values())


def _should_skip_email(email: str) -> bool:
    lowered = email.strip().lower()
    if NO_REPLY_RE.search(lowered):
        return True
    if any(lowered.endswith(f"@{domain}") for domain in VENDOR_EMAIL_DOMAINS):
        return True
    if any(lowered.endswith(f"@{domain}") for domain in FREE_EMAIL_DOMAINS):
        return True
    if lowered.rsplit(".", 1)[-1] in NON_WORK_TLDS:
        return True
    return False


def _infer_contact_role(context: str) -> str:
    lowered = context.lower()
    if any(token in lowered for token in ("talent acquisition", "talent partner", "recruiter", "recruiting", "sourcer")):
        return "Recruiting / Talent"
    if any(token in lowered for token in ("people operations", "people ops", "human resources", "hr team")):
        return "People / HR"
    if any(
        token in lowered
        for token in (
            "solution expert",
            "solutions consultant",
            "solution consultant",
            "customer engineer",
            "sales engineer",
            "presales",
            "pre-sales",
            "solution architect",
            "technical consultant",
        )
    ):
        return "Solutions / Presales"
    if any(token in lowered for token in ("hiring manager", "head of product", "product lead", "product team")):
        return "Product"
    if any(token in lowered for token in ("engineering manager", "head of engineering", "engineering team")):
        return "Engineering"
    if any(token in lowered for token in ("solutions", "presales", "solution architect")):
        return "Solutions / Presales"
    return ""


def _infer_contact_name(context: str, email: str) -> str:
    without_email = context.replace(email, " ")
    matches = re.findall(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+){1,2}\b", without_email)
    for match in matches:
        lowered = match.lower()
        if lowered in {"human resources", "people operations"}:
            continue
        return match.strip()
    return ""


def _infer_contact_department(role: str, fallback_department: str) -> str:
    if role:
        return role
    return fallback_department


def infer_department_hint(job: JobIngestRecord) -> str:
    corpus = f"{job.title_raw} {job.description_text}".lower()
    if any(token in corpus for token in ("product manager", "product owner", "roadmap", "gtm", "stakeholder")):
        return "Product / Strategy"
    if any(
        token in corpus
        for token in (
            "solution architect",
            "solutions lead",
            "solution expert",
            "solutions expert",
            "solution consultant",
            "customer engineer",
            "sales engineer",
            "presales",
            "pre-sales",
            "customer workshop",
            "technical consultant",
        )
    ):
        return "Solutions / Presales"
    if any(token in corpus for token in ("platform", "engineering", "ml engineer", "ai engineer", "developer")):
        return "Engineering / AI Platform"
    if any(token in corpus for token in ("customer success", "implementation", "onboarding")):
        return "Customer Success / Implementations"
    if any(token in corpus for token in ("operations", "transformation", "strategy", "governance")):
        return "Strategy / Operations"
    return "AI / General"


def _build_cover_letter_focus(
    job: JobIngestRecord,
    fit: FitScoreRecord | None,
    department_hint: str,
    context: CompanyContextRecord | None,
) -> str:
    focus = []
    if department_hint == "Product / Strategy":
        focus.append("Lead with product strategy, roadmap ownership, stakeholder alignment, and GTM execution.")
    elif department_hint == "Solutions / Presales":
        focus.append(
            "Lead with AI solutioning, executive workshops, customer discovery, value articulation, and presales credibility."
        )
    elif department_hint == "Engineering / AI Platform":
        focus.append("Lead with AI platform delivery, implementation depth, and shipping reliable systems.")
    elif department_hint == "Customer Success / Implementations":
        focus.append("Lead with onboarding, adoption, and turning delivery into measurable customer outcomes.")
    else:
        focus.append("Lead with enterprise AI execution and the ability to connect strategy to delivery.")

    if fit and "strong_domain_alignment" in fit.reason_codes:
        focus.append("Mirror the domain language from the role rather than sending a generic AI cover note.")
    if fit and "strong_tool_alignment" in fit.reason_codes:
        focus.append("Call out the exact AI/tooling stack mentioned in the posting.")
    if context and context.business_direction:
        focus.append(f"Reflect the company's current direction: {_trim_text(context.business_direction, 120)}.")
    return " ".join(focus)


def _build_lead_row(
    *,
    application: ApplicationRecord,
    job: JobIngestRecord,
    fit: FitScoreRecord | None,
    context: CompanyContextRecord | None,
    contact: ContactRecord | None,
) -> OutreachLead:
    department_hint = infer_department_hint(job)
    return OutreachLead(
        application_id=application.application_id,
        job_id=job.job_id,
        company=job.company,
        job_title=job.title_raw,
        department_hint=contact.department if contact and contact.department else department_hint,
        role_track=application.role_track.value,
        decision=application.decision.value,
        fit_score=int(fit.fit_score if fit else application.fit_score),
        location=job.location,
        remote_type=job.remote_type,
        job_url=job.job_url,
        contact_status="found" if contact and contact.contact_value else "missing",
        contact_name=contact.name if contact else "",
        contact_role=contact.role if contact else "",
        contact_email=contact.contact_value if contact else "",
        contact_source_url=contact.source_url if contact else "",
        contact_notes=contact.notes if contact else "",
        cover_letter_focus=_build_cover_letter_focus(job, fit, department_hint, context),
    )


def _write_leads_csv(path: Path, leads: Sequence[OutreachLead]) -> None:
    rows = [lead.to_dict() for lead in leads]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTREACH_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_leads_json(path: Path, leads: Sequence[OutreachLead]) -> None:
    path.write_text(
        json.dumps([lead.to_dict() for lead in leads], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _contact_priority(contact: ContactRecord, *, company_domain: str = "", team_hint: str = "") -> int:
    value = contact.contact_value.strip().lower()
    role = contact.role.strip().lower()
    source = contact.source_url.strip().lower()
    score = 0
    host = urlparse(source).netloc.lower().replace("www.", "")
    if company_domain and value.endswith(f"@{company_domain}"):
        score += 12
    if company_domain and host.endswith(company_domain):
        score += 8
    if any(token in value for token in GENERIC_EMAIL_HINTS):
        score += 8
    if any(token in role for token in ("recruit", "talent", "people", "hr", "hiring")):
        score += 6
    if team_hint == "Solutions / Presales" and any(
        token in role for token in ("solution", "presales", "customer engineer", "sales engineer", "architect")
    ):
        score += 6
    if team_hint == "Product / Strategy" and "product" in role:
        score += 6
    if team_hint == "Engineering / AI Platform" and any(token in role for token in ("engineering", "ai", "platform")):
        score += 6
    if "/careers" in source or "/jobs" in source or "/team" in source or "/contact" in source:
        score += 4
    if any(host.endswith(domain) for domain in LOW_CONFIDENCE_RESULT_HOSTS):
        score -= 8
    if value.startswith(("info@", "hello@", "contact@", "support@")):
        score -= 2
    return score


def _trim_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
