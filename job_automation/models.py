from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Dict, List
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_job_id(source: str, external_id: str) -> str:
    seed = f"{source.strip().lower()}::{external_id.strip().lower()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{source.strip().lower()}_{digest}"


class RoleTrack(StrEnum):
    AI_PM = "ai_pm"
    GENAI_LEAD = "genai_lead"


class Decision(StrEnum):
    MUST_APPLY = "must_apply"
    GOOD_FIT = "good_fit"
    LOW_FIT = "low_fit"


class SeniorityMatch(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApplicationStatus(StrEnum):
    NEW = "new"
    SCREENING = "screening"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    CLOSED = "closed"


class OwnerAction(StrEnum):
    APPROVE = "approve"
    HOLD = "hold"
    REJECT = "reject"


class ContactChannel(StrEnum):
    EMAIL = "email"
    LINKEDIN = "linkedin"
    REFERRAL = "referral"


@dataclass
class JobIngestRecord:
    job_id: str
    source: str
    title_raw: str
    company: str
    location: str
    remote_type: str
    job_url: str
    description_text: str
    date_posted: str
    scraped_at: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "job_id": self.job_id,
            "source": self.source,
            "title_raw": self.title_raw,
            "company": self.company,
            "location": self.location,
            "remote_type": self.remote_type,
            "job_url": self.job_url,
            "description_text": self.description_text,
            "date_posted": self.date_posted,
            "scraped_at": self.scraped_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, str]) -> "JobIngestRecord":
        return cls(
            job_id=raw.get("job_id", "").strip(),
            source=raw.get("source", "").strip(),
            title_raw=raw.get("title_raw", "").strip(),
            company=raw.get("company", "").strip(),
            location=raw.get("location", "").strip(),
            remote_type=raw.get("remote_type", "").strip(),
            job_url=raw.get("job_url", "").strip(),
            description_text=raw.get("description_text", "").strip(),
            date_posted=raw.get("date_posted", "").strip(),
            scraped_at=raw.get("scraped_at", "").strip() or utc_now_iso(),
        )


@dataclass
class FitScoreRecord:
    job_id: str
    role_track: RoleTrack
    fit_score: int
    must_have_match_pct: int
    domain_match_pct: int
    seniority_match: SeniorityMatch
    decision: Decision
    reason_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "job_id": self.job_id,
            "role_track": self.role_track.value,
            "fit_score": self.fit_score,
            "must_have_match_pct": self.must_have_match_pct,
            "domain_match_pct": self.domain_match_pct,
            "seniority_match": self.seniority_match.value,
            "decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "FitScoreRecord":
        reason_codes_raw = raw.get("reason_codes", [])
        if isinstance(reason_codes_raw, str):
            try:
                parsed_reason_codes = json.loads(reason_codes_raw)
                if isinstance(parsed_reason_codes, list):
                    reason_codes_raw = parsed_reason_codes
                else:
                    reason_codes_raw = [reason_codes_raw]
            except json.JSONDecodeError:
                reason_codes_raw = [reason_codes_raw]
        return cls(
            job_id=str(raw.get("job_id", "")),
            role_track=RoleTrack(str(raw.get("role_track", RoleTrack.AI_PM.value))),
            fit_score=int(raw.get("fit_score", 0)),
            must_have_match_pct=int(raw.get("must_have_match_pct", 0)),
            domain_match_pct=int(raw.get("domain_match_pct", 0)),
            seniority_match=SeniorityMatch(
                str(raw.get("seniority_match", SeniorityMatch.MEDIUM.value))
            ),
            decision=Decision(str(raw.get("decision", Decision.LOW_FIT.value))),
            reason_codes=[
                str(item).strip()
                for item in (reason_codes_raw or [])
                if str(item).strip()
            ],
        )


@dataclass
class ApplicationRecord:
    application_id: str
    job_id: str
    status: ApplicationStatus
    resume_variant: str
    cover_note_version: str
    owner_action: OwnerAction
    applied_on: str
    next_followup_on: str
    role_track: RoleTrack
    decision: Decision
    fit_score: int
    followup_dates: List[str] = field(default_factory=list)
    documents: Dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, object]:
        return {
            "application_id": self.application_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "resume_variant": self.resume_variant,
            "cover_note_version": self.cover_note_version,
            "owner_action": self.owner_action.value,
            "applied_on": self.applied_on,
            "next_followup_on": self.next_followup_on,
            "role_track": self.role_track.value,
            "decision": self.decision.value,
            "fit_score": self.fit_score,
            "followup_dates": list(self.followup_dates),
            "documents": dict(self.documents),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "ApplicationRecord":
        followup_dates_raw = raw.get("followup_dates", []) or []
        if isinstance(followup_dates_raw, str):
            try:
                parsed_followups = json.loads(followup_dates_raw)
                if isinstance(parsed_followups, list):
                    followup_dates_raw = parsed_followups
                else:
                    followup_dates_raw = [followup_dates_raw]
            except json.JSONDecodeError:
                followup_dates_raw = [followup_dates_raw]

        documents_raw = raw.get("documents", {}) or {}
        if isinstance(documents_raw, str):
            try:
                parsed_docs = json.loads(documents_raw)
                if isinstance(parsed_docs, dict):
                    documents_raw = parsed_docs
                else:
                    documents_raw = {}
            except json.JSONDecodeError:
                documents_raw = {}

        return cls(
            application_id=str(raw.get("application_id", "")),
            job_id=str(raw.get("job_id", "")),
            status=ApplicationStatus(
                str(raw.get("status", ApplicationStatus.NEW.value))
            ),
            resume_variant=str(raw.get("resume_variant", "A")),
            cover_note_version=str(raw.get("cover_note_version", "")),
            owner_action=OwnerAction(str(raw.get("owner_action", OwnerAction.HOLD.value))),
            applied_on=str(raw.get("applied_on", "")),
            next_followup_on=str(raw.get("next_followup_on", "")),
            role_track=RoleTrack(str(raw.get("role_track", RoleTrack.AI_PM.value))),
            decision=Decision(str(raw.get("decision", Decision.LOW_FIT.value))),
            fit_score=int(raw.get("fit_score", 0)),
            followup_dates=[
                str(item).strip()
                for item in followup_dates_raw
                if str(item).strip()
            ],
            documents={
                str(k): str(v)
                for k, v in documents_raw.items()
                if str(k).strip() and str(v).strip()
            },
            created_at=str(raw.get("created_at", utc_now_iso())),
            updated_at=str(raw.get("updated_at", utc_now_iso())),
        )


@dataclass
class CompanyContextRecord:
    company: str
    funding_signal: str
    business_direction: str
    ai_maturity: str
    enriched_at: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "company": self.company,
            "funding_signal": self.funding_signal,
            "business_direction": self.business_direction,
            "ai_maturity": self.ai_maturity,
            "enriched_at": self.enriched_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, str]) -> "CompanyContextRecord":
        return cls(
            company=raw.get("company", "").strip(),
            funding_signal=raw.get("funding_signal", "").strip(),
            business_direction=raw.get("business_direction", "").strip(),
            ai_maturity=raw.get("ai_maturity", "").strip(),
            enriched_at=raw.get("enriched_at", "").strip() or utc_now_iso(),
        )


@dataclass
class ContactRecord:
    contact_id: str
    job_id: str
    company: str
    name: str
    role: str
    department: str
    channel: ContactChannel
    contact_value: str
    source_url: str
    notes: str
    discovered_at: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "contact_id": self.contact_id,
            "job_id": self.job_id,
            "company": self.company,
            "name": self.name,
            "role": self.role,
            "department": self.department,
            "channel": self.channel.value,
            "contact_value": self.contact_value,
            "source_url": self.source_url,
            "notes": self.notes,
            "discovered_at": self.discovered_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, str]) -> "ContactRecord":
        return cls(
            contact_id=raw.get("contact_id", "").strip(),
            job_id=raw.get("job_id", "").strip(),
            company=raw.get("company", "").strip(),
            name=raw.get("name", "").strip(),
            role=raw.get("role", "").strip(),
            department=raw.get("department", "").strip(),
            channel=ContactChannel(str(raw.get("channel", ContactChannel.EMAIL.value))),
            contact_value=raw.get("contact_value", "").strip(),
            source_url=raw.get("source_url", "").strip(),
            notes=raw.get("notes", "").strip(),
            discovered_at=raw.get("discovered_at", "").strip() or utc_now_iso(),
        )

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        company: str,
        contact_value: str,
        channel: ContactChannel = ContactChannel.EMAIL,
        name: str = "",
        role: str = "",
        department: str = "",
        source_url: str = "",
        notes: str = "",
    ) -> "ContactRecord":
        return cls(
            contact_id=build_contact_id(job_id, channel.value, contact_value),
            job_id=job_id,
            company=company.strip(),
            name=name.strip(),
            role=role.strip(),
            department=department.strip(),
            channel=channel,
            contact_value=contact_value.strip(),
            source_url=source_url.strip(),
            notes=notes.strip(),
            discovered_at=utc_now_iso(),
        )


@dataclass
class DocumentRecord:
    document_id: str
    application_id: str
    document_type: str
    path_or_url: str
    created_at: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "document_id": self.document_id,
            "application_id": self.application_id,
            "document_type": self.document_type,
            "path_or_url": self.path_or_url,
            "created_at": self.created_at,
        }

    @classmethod
    def create(
        cls,
        application_id: str,
        document_type: str,
        path_or_url: str,
    ) -> "DocumentRecord":
        return cls(
            document_id=str(uuid4()),
            application_id=application_id,
            document_type=document_type,
            path_or_url=path_or_url,
            created_at=utc_now_iso(),
        )


@dataclass
class ActivityLogRecord:
    activity_id: str
    entity_type: str
    entity_id: str
    event: str
    event_at: str
    details: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "activity_id": self.activity_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "event": self.event,
            "event_at": self.event_at,
            "details": self.details,
        }

    @classmethod
    def create(
        cls,
        entity_type: str,
        entity_id: str,
        event: str,
        details: str,
    ) -> "ActivityLogRecord":
        return cls(
            activity_id=str(uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            event=event,
            event_at=utc_now_iso(),
            details=details.strip(),
        )


def new_application(
    job_id: str,
    role_track: RoleTrack,
    decision: Decision,
    fit_score: int,
) -> ApplicationRecord:
    return ApplicationRecord(
        application_id=str(uuid4()),
        job_id=job_id,
        status=ApplicationStatus.NEW,
        resume_variant="A" if role_track == RoleTrack.AI_PM else "B",
        cover_note_version="",
        owner_action=OwnerAction.HOLD,
        applied_on="",
        next_followup_on="",
        role_track=role_track,
        decision=decision,
        fit_score=fit_score,
    )


def plus_days_iso(base_date: date, days: int) -> str:
    return (base_date + timedelta(days=days)).isoformat()


def build_contact_id(job_id: str, channel: str, contact_value: str) -> str:
    seed = f"{job_id.strip().lower()}::{channel.strip().lower()}::{contact_value.strip().lower()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"contact_{digest}"
