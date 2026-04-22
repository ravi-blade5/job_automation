from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Dict, List, Sequence

from .artifacts import ApplicationArtifactGenerator
from .dedup import dedupe_jobs
from .enrichment.jd_parser import RuleBasedJDParser
from .enrichment.perplexity import CompanyEnricher
from .models import (
    ActivityLogRecord,
    ApplicationRecord,
    ApplicationStatus,
    CompanyContextRecord,
    Decision,
    DocumentRecord,
    OwnerAction,
    RoleTrack,
    new_application,
)
from .scoring import FitScorer
from .sources.base import JobSource
from .tracking.repository import TrackingRepository

APAC_LOCATION_TOKENS = (
    "apac",
    "asia pacific",
    "asia-pacific",
    "singapore",
    "hong kong",
    "australia",
    "sydney",
    "melbourne",
    "brisbane",
    "perth",
    "new zealand",
    "auckland",
    "wellington",
    "japan",
    "tokyo",
    "osaka",
    "south korea",
    "seoul",
    "taiwan",
    "taipei",
    "malaysia",
    "kuala lumpur",
    "indonesia",
    "jakarta",
    "philippines",
    "manila",
    "thailand",
    "bangkok",
    "vietnam",
    "ho chi minh",
    "hanoi",
)


@dataclass
class PipelineResult:
    ingested: int
    deduped: int
    scored: int
    queued: int


ALLOWED_TRANSITIONS: Dict[ApplicationStatus, Sequence[ApplicationStatus]] = {
    ApplicationStatus.NEW: (
        ApplicationStatus.SCREENING,
        ApplicationStatus.REJECTED,
        ApplicationStatus.CLOSED,
    ),
    ApplicationStatus.SCREENING: (
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.CLOSED,
    ),
    ApplicationStatus.APPLIED: (
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.CLOSED,
    ),
    ApplicationStatus.INTERVIEW: (
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.CLOSED,
    ),
    ApplicationStatus.OFFER: (ApplicationStatus.CLOSED,),
    ApplicationStatus.REJECTED: (ApplicationStatus.CLOSED,),
    ApplicationStatus.CLOSED: (),
}


class JobAutomationPipeline:
    def __init__(
        self,
        sources: Sequence[JobSource],
        tracker: TrackingRepository,
        scorer: FitScorer,
        artifact_generator: ApplicationArtifactGenerator,
        jd_parser: RuleBasedJDParser,
        company_enricher: CompanyEnricher,
        region_filters: Sequence[str] | None = None,
        title_include_keywords: Sequence[str] | None = None,
        title_exclude_keywords: Sequence[str] | None = None,
    ):
        self.sources = list(sources)
        self.tracker = tracker
        self.scorer = scorer
        self.artifact_generator = artifact_generator
        self.jd_parser = jd_parser
        self.company_enricher = company_enricher
        self.region_filters = [item.strip().lower() for item in (region_filters or []) if item.strip()]
        self.title_include_keywords = [
            item.strip().lower() for item in (title_include_keywords or []) if item.strip()
        ]
        self.title_exclude_keywords = [
            item.strip().lower() for item in (title_exclude_keywords or []) if item.strip()
        ]

    def run_daily(self) -> PipelineResult:
        ingested, deduped = self.ingest_and_dedupe()
        scored = self.score_all_jobs()
        queued = self.build_review_queue()
        return PipelineResult(ingested=ingested, deduped=deduped, scored=scored, queued=queued)

    def ingest_and_dedupe(self) -> tuple[int, int]:
        raw_jobs = []
        for source in self.sources:
            raw_jobs.extend(source.fetch_jobs())
        deduped = dedupe_jobs(raw_jobs)
        region_filtered = [job for job in deduped if self._matches_region(job)]
        focused = [job for job in region_filtered if self._matches_title_focus(job)]
        for job in focused:
            self.tracker.upsert_job(job)
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="pipeline",
                entity_id="daily_ingestion",
                event="ingestion_completed",
                details=(
                    f"ingested={len(raw_jobs)}, deduped={len(deduped)}, "
                    f"region_filtered={len(region_filtered)}, title_filtered={len(focused)}"
                ),
            )
        )
        return len(raw_jobs), len(focused)

    def score_all_jobs(self) -> int:
        scored_count = 0
        company_cache = self.tracker.list_company_context()
        for job in self.tracker.list_jobs():
            _ = self.jd_parser.parse(job)
            for role_track in (RoleTrack.AI_PM, RoleTrack.GENAI_LEAD):
                existing_fit = self.tracker.get_fit_score(job.job_id, role_track.value)
                if existing_fit:
                    continue
                fit = self.scorer.score(job, role_track)
                self.tracker.upsert_fit_score(fit)
                scored_count += 1

            company_key = job.company.strip().lower()
            if company_key and company_key not in company_cache:
                context = self.company_enricher.enrich(job.company, job.description_text)
                self.tracker.upsert_company_context(context)
                company_cache[company_key] = context

        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="pipeline",
                entity_id="daily_scoring",
                event="scoring_completed",
                details=f"fit_scores_written={scored_count}",
            )
        )
        return scored_count

    def build_review_queue(self) -> int:
        queued = 0
        for job in self.tracker.list_jobs():
            existing = self.tracker.find_application_by_job(job.job_id)
            if existing:
                continue
            fits = self.tracker.list_fit_scores(job_id=job.job_id)
            eligible = [fit for fit in fits if fit.decision != Decision.LOW_FIT]
            if not eligible:
                continue
            best_fit = sorted(eligible, key=lambda item: item.fit_score, reverse=True)[0]
            application = new_application(
                job_id=job.job_id,
                role_track=best_fit.role_track,
                decision=best_fit.decision,
                fit_score=best_fit.fit_score,
            )
            self.tracker.upsert_application(application)
            self.tracker.add_activity(
                ActivityLogRecord.create(
                    entity_type="application",
                    entity_id=application.application_id,
                    event="queued_for_review",
                    details=f"job_id={job.job_id}, role_track={best_fit.role_track.value}, fit={best_fit.fit_score}",
                )
            )
            queued += 1
        return queued

    def approve_application(self, application_id: str) -> ApplicationRecord:
        application = self._must_get_application(application_id)
        application.owner_action = OwnerAction.APPROVE
        application.status = self._transition(application.status, ApplicationStatus.SCREENING)
        application.updated_at = _now_iso()
        self.tracker.upsert_application(application)
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="application",
                entity_id=application.application_id,
                event="approved",
                details="owner approved for screening",
            )
        )
        return application

    def reject_application(self, application_id: str) -> ApplicationRecord:
        application = self._must_get_application(application_id)
        application.owner_action = OwnerAction.REJECT
        application.status = self._transition(application.status, ApplicationStatus.REJECTED)
        application.updated_at = _now_iso()
        self.tracker.upsert_application(application)
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="application",
                entity_id=application.application_id,
                event="rejected",
                details="owner rejected application",
            )
        )
        return application

    def generate_artifacts(self, application_id: str) -> Dict[str, str]:
        application = self._must_get_application(application_id)
        if application.owner_action != OwnerAction.APPROVE:
            raise PermissionError("Application artifacts can be generated only after explicit approval.")
        if application.status in (ApplicationStatus.REJECTED, ApplicationStatus.CLOSED):
            raise PermissionError("Rejected or closed applications cannot generate artifacts.")

        job = self.tracker.get_job(application.job_id)
        if not job:
            raise LookupError(f"Missing job record for job_id={application.job_id}")
        fit = self.tracker.get_fit_score(job.job_id, application.role_track.value)
        if not fit:
            raise LookupError("Missing fit score for approved application")

        generated = self.artifact_generator.generate(application, job, fit)
        application.documents.update(generated)
        application.cover_note_version = _now_version()
        application.updated_at = _now_iso()
        self.tracker.upsert_application(application)

        for doc_type, path in generated.items():
            self.tracker.add_document(DocumentRecord.create(application.application_id, doc_type, path))
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="application",
                entity_id=application.application_id,
                event="artifacts_generated",
                details=f"documents={','.join(sorted(generated.keys()))}",
            )
        )
        return generated

    def mark_applied(self, application_id: str, applied_date: date | None = None) -> ApplicationRecord:
        application = self._must_get_application(application_id)
        if application.owner_action != OwnerAction.APPROVE:
            raise PermissionError("Cannot mark as applied before approval.")

        applied_date = applied_date or date.today()
        application.status = self._transition(application.status, ApplicationStatus.APPLIED)
        application.applied_on = applied_date.isoformat()
        followup_1 = (applied_date + timedelta(days=5)).isoformat()
        followup_2 = (applied_date + timedelta(days=12)).isoformat()
        application.followup_dates = [followup_1, followup_2]
        application.next_followup_on = followup_1
        application.updated_at = _now_iso()
        self.tracker.upsert_application(application)
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="application",
                entity_id=application.application_id,
                event="marked_applied",
                details=f"applied_on={application.applied_on}, followups={followup_1}|{followup_2}",
            )
        )
        return application

    def advance_status(self, application_id: str, target_status: ApplicationStatus) -> ApplicationRecord:
        application = self._must_get_application(application_id)
        application.status = self._transition(application.status, target_status)
        application.updated_at = _now_iso()
        self.tracker.upsert_application(application)
        self.tracker.add_activity(
            ActivityLogRecord.create(
                entity_type="application",
                entity_id=application.application_id,
                event="status_changed",
                details=f"status={application.status.value}",
            )
        )
        return application

    def mark_followup_done(self, application_id: str) -> ApplicationRecord:
        application = self._must_get_application(application_id)
        if not application.followup_dates:
            application.next_followup_on = ""
        else:
            remaining = list(application.followup_dates[1:])
            application.followup_dates = remaining
            application.next_followup_on = remaining[0] if remaining else ""
        application.updated_at = _now_iso()
        self.tracker.upsert_application(application)
        return application

    def followups_due(self, on_date: date | None = None) -> List[ApplicationRecord]:
        on_date = on_date or date.today()
        due: List[ApplicationRecord] = []
        for app in self.tracker.list_applications():
            if not app.next_followup_on:
                continue
            if app.status in (ApplicationStatus.REJECTED, ApplicationStatus.CLOSED):
                continue
            if app.next_followup_on <= on_date.isoformat():
                due.append(app)
        return due

    def dashboard(self) -> Dict[str, float]:
        apps = self.tracker.list_applications()
        total = len(apps)
        if total == 0:
            return {
                "applications_total": 0,
                "interview_rate_pct": 0.0,
                "offer_rate_pct": 0.0,
                "source_count": 0,
                "median_response_days": 0.0,
            }

        interviews = sum(1 for app in apps if app.status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.CLOSED))
        offers = sum(1 for app in apps if app.status == ApplicationStatus.OFFER)

        job_index = {job.job_id: job for job in self.tracker.list_jobs()}
        source_set = {
            job_index[app.job_id].source
            for app in apps
            if app.job_id in job_index
        }

        response_days = []
        for app in apps:
            if app.applied_on and app.status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.CLOSED):
                applied = _to_date(app.applied_on)
                updated = _to_date(app.updated_at[:10])
                if applied and updated:
                    response_days.append(max((updated - applied).days, 0))
        median_response = _median(response_days)

        return {
            "applications_total": float(total),
            "interview_rate_pct": round((interviews / total) * 100, 2),
            "offer_rate_pct": round((offers / total) * 100, 2),
            "source_count": float(len(source_set)),
            "median_response_days": float(median_response),
        }

    def source_conversion(self) -> Dict[str, Dict[str, int]]:
        result: Dict[str, Dict[str, int]] = defaultdict(lambda: {"applications": 0, "interviews": 0, "offers": 0})
        jobs = {job.job_id: job for job in self.tracker.list_jobs()}
        for app in self.tracker.list_applications():
            job = jobs.get(app.job_id)
            if not job:
                continue
            entry = result[job.source]
            entry["applications"] += 1
            if app.status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.CLOSED):
                entry["interviews"] += 1
            if app.status == ApplicationStatus.OFFER:
                entry["offers"] += 1
        return dict(result)

    def _must_get_application(self, application_id: str) -> ApplicationRecord:
        app = self.tracker.get_application(application_id)
        if not app:
            raise LookupError(f"Application not found: {application_id}")
        return app

    def _matches_region(self, job) -> bool:
        if not self.region_filters:
            return True
        haystack = f"{job.location} {job.remote_type}".lower()
        if "remote" in self.region_filters and "remote" in haystack:
            return True
        direct_filters = [token for token in self.region_filters if token not in {"remote", "apac"}]
        if any(token in haystack for token in direct_filters):
            return True
        if "apac" in self.region_filters and any(token in haystack for token in APAC_LOCATION_TOKENS):
            return True

        # Career pages often omit location; keep unknown-location jobs so they can
        # still be scored and manually reviewed.
        location = str(getattr(job, "location", "")).strip().lower()
        remote_type = str(getattr(job, "remote_type", "")).strip().lower()
        if not location or remote_type in {"", "unknown"}:
            return True
        return False

    def _matches_title_focus(self, job) -> bool:
        title = str(getattr(job, "title_raw", "")).strip().lower()
        description = str(getattr(job, "description_text", "")).strip().lower()
        if not title and not description:
            return False

        title_haystack = f"{title} {description}"
        if any(keyword in title_haystack for keyword in self.title_exclude_keywords):
            return False
        if not self.title_include_keywords:
            return True
        return any(keyword in title_haystack for keyword in self.title_include_keywords)

    def _transition(
        self,
        current: ApplicationStatus,
        target: ApplicationStatus,
    ) -> ApplicationStatus:
        allowed = ALLOWED_TRANSITIONS[current]
        if target not in allowed and target != current:
            raise ValueError(f"Invalid status transition: {current.value} -> {target.value}")
        return target


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_version() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _to_date(raw: str) -> date | None:
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _median(values: List[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0
