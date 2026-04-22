from __future__ import annotations

from abc import ABC, abstractmethod
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


class TrackingRepository(ABC):
    @abstractmethod
    def upsert_job(self, record: JobIngestRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_jobs(self) -> List[JobIngestRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[JobIngestRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert_fit_score(self, record: FitScoreRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_fit_scores(self, job_id: str | None = None) -> List[FitScoreRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_fit_score(self, job_id: str, role_track: str) -> Optional[FitScoreRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert_application(self, record: ApplicationRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_application(self, application_id: str) -> Optional[ApplicationRecord]:
        raise NotImplementedError

    @abstractmethod
    def find_application_by_job(self, job_id: str) -> Optional[ApplicationRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_applications(self) -> List[ApplicationRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_review_queue(self) -> List[ApplicationRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert_company_context(self, record: CompanyContextRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_company_context(self) -> Dict[str, CompanyContextRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert_contact(self, record: ContactRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_contacts(
        self,
        job_id: str | None = None,
        company: str | None = None,
    ) -> List[ContactRecord]:
        raise NotImplementedError

    @abstractmethod
    def add_document(self, record: DocumentRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_documents(self, application_id: str | None = None) -> List[DocumentRecord]:
        raise NotImplementedError

    @abstractmethod
    def add_activity(self, record: ActivityLogRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_activity(self) -> List[ActivityLogRecord]:
        raise NotImplementedError
