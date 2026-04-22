from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..models import (
    ActivityLogRecord,
    ApplicationRecord,
    CompanyContextRecord,
    ContactRecord,
    DocumentRecord,
    FitScoreRecord,
    JobIngestRecord,
)
from .repository import TrackingRepository


class LocalJSONTrackingRepository(TrackingRepository):
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_path = self.root_dir / "jobs.json"
        self.fit_scores_path = self.root_dir / "fit_scores.json"
        self.applications_path = self.root_dir / "applications.json"
        self.companies_path = self.root_dir / "companies.json"
        self.contacts_path = self.root_dir / "contacts.json"
        self.documents_path = self.root_dir / "documents.json"
        self.activity_path = self.root_dir / "activity_log.json"
        self._bootstrap_files()

    def upsert_job(self, record: JobIngestRecord) -> None:
        rows = self._load_dict(self.jobs_path)
        rows[record.job_id] = record.to_dict()
        self._save_dict(self.jobs_path, rows)

    def list_jobs(self) -> List[JobIngestRecord]:
        rows = self._load_dict(self.jobs_path)
        return [JobIngestRecord.from_dict(item) for item in rows.values()]

    def get_job(self, job_id: str) -> Optional[JobIngestRecord]:
        rows = self._load_dict(self.jobs_path)
        raw = rows.get(job_id)
        return JobIngestRecord.from_dict(raw) if raw else None

    def upsert_fit_score(self, record: FitScoreRecord) -> None:
        rows = self._load_dict(self.fit_scores_path)
        rows[f"{record.job_id}::{record.role_track.value}"] = record.to_dict()
        self._save_dict(self.fit_scores_path, rows)

    def list_fit_scores(self, job_id: str | None = None) -> List[FitScoreRecord]:
        rows = self._load_dict(self.fit_scores_path)
        all_rows = [FitScoreRecord.from_dict(item) for item in rows.values()]
        if not job_id:
            return all_rows
        return [item for item in all_rows if item.job_id == job_id]

    def get_fit_score(self, job_id: str, role_track: str) -> Optional[FitScoreRecord]:
        rows = self._load_dict(self.fit_scores_path)
        key = f"{job_id}::{role_track}"
        raw = rows.get(key)
        return FitScoreRecord.from_dict(raw) if raw else None

    def upsert_application(self, record: ApplicationRecord) -> None:
        rows = self._load_dict(self.applications_path)
        rows[record.application_id] = record.to_dict()
        self._save_dict(self.applications_path, rows)

    def get_application(self, application_id: str) -> Optional[ApplicationRecord]:
        rows = self._load_dict(self.applications_path)
        raw = rows.get(application_id)
        return ApplicationRecord.from_dict(raw) if raw else None

    def find_application_by_job(self, job_id: str) -> Optional[ApplicationRecord]:
        for application in self.list_applications():
            if application.job_id == job_id and application.status.value != "closed":
                return application
        return None

    def list_applications(self) -> List[ApplicationRecord]:
        rows = self._load_dict(self.applications_path)
        return [ApplicationRecord.from_dict(item) for item in rows.values()]

    def list_review_queue(self) -> List[ApplicationRecord]:
        return [
            app
            for app in self.list_applications()
            if app.owner_action.value == "hold" and app.status.value == "new"
        ]

    def upsert_company_context(self, record: CompanyContextRecord) -> None:
        rows = self._load_dict(self.companies_path)
        rows[record.company.lower()] = record.to_dict()
        self._save_dict(self.companies_path, rows)

    def list_company_context(self) -> Dict[str, CompanyContextRecord]:
        rows = self._load_dict(self.companies_path)
        return {
            key: CompanyContextRecord.from_dict(value)
            for key, value in rows.items()
        }

    def upsert_contact(self, record: ContactRecord) -> None:
        rows = self._load_dict(self.contacts_path)
        rows[record.contact_id] = record.to_dict()
        self._save_dict(self.contacts_path, rows)

    def list_contacts(
        self,
        job_id: str | None = None,
        company: str | None = None,
    ) -> List[ContactRecord]:
        rows = self._load_dict(self.contacts_path)
        contacts = [ContactRecord.from_dict(item) for item in rows.values()]
        if job_id is not None:
            contacts = [item for item in contacts if item.job_id == job_id]
        if company is not None:
            normalized_company = company.strip().lower()
            contacts = [
                item
                for item in contacts
                if item.company.strip().lower() == normalized_company
            ]
        return contacts

    def add_document(self, record: DocumentRecord) -> None:
        rows = self._load_list(self.documents_path)
        rows.append(record.to_dict())
        self._save_list(self.documents_path, rows)

    def list_documents(self, application_id: str | None = None) -> List[DocumentRecord]:
        rows = self._load_list(self.documents_path)
        documents = [
            DocumentRecord(
                document_id=str(item.get("document_id", "")),
                application_id=str(item.get("application_id", "")),
                document_type=str(item.get("document_type", "")),
                path_or_url=str(item.get("path_or_url", "")),
                created_at=str(item.get("created_at", "")),
            )
            for item in rows
        ]
        if application_id is None:
            return documents
        return [doc for doc in documents if doc.application_id == application_id]

    def add_activity(self, record: ActivityLogRecord) -> None:
        rows = self._load_list(self.activity_path)
        rows.append(record.to_dict())
        self._save_list(self.activity_path, rows)

    def list_activity(self) -> List[ActivityLogRecord]:
        rows = self._load_list(self.activity_path)
        return [
            ActivityLogRecord(
                activity_id=str(item.get("activity_id", "")),
                entity_type=str(item.get("entity_type", "")),
                entity_id=str(item.get("entity_id", "")),
                event=str(item.get("event", "")),
                event_at=str(item.get("event_at", "")),
                details=str(item.get("details", "")),
            )
            for item in rows
        ]

    def _bootstrap_files(self) -> None:
        for path in (
            self.jobs_path,
            self.fit_scores_path,
            self.applications_path,
            self.companies_path,
            self.contacts_path,
        ):
            if not path.exists():
                self._save_dict(path, {})
        for path in (self.documents_path, self.activity_path):
            if not path.exists():
                self._save_list(path, [])

    def _load_dict(self, path: Path) -> Dict[str, dict]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def _load_list(self, path: Path) -> List[dict]:
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        return raw

    def _save_dict(self, path: Path, payload: Dict[str, dict]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_list(self, path: Path, payload: List[dict]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
