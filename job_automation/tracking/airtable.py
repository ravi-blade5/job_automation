from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote

from ..http_client import HttpClientError, request_json
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


@dataclass(frozen=True)
class AirtableTableConfig:
    jobs: str
    fit_scores: str
    applications: str
    companies: str
    contacts: str
    documents: str
    activity_log: str


class AirtableTrackingRepository(TrackingRepository):
    def __init__(
        self,
        api_token: str,
        base_id: str,
        tables: AirtableTableConfig,
    ):
        self.api_token = api_token.strip()
        self.base_id = base_id.strip()
        self.tables = tables
        if not self.api_token or not self.base_id:
            raise RuntimeError("Airtable token and base id are required for Airtable tracker")

    def upsert_job(self, record: JobIngestRecord) -> None:
        self._upsert_by_field(
            table=self.tables.jobs,
            id_field="job_id",
            id_value=record.job_id,
            fields=record.to_dict(),
        )

    def list_jobs(self) -> List[JobIngestRecord]:
        records = self._list_records(self.tables.jobs)
        return [JobIngestRecord.from_dict(rec.get("fields", {})) for rec in records]

    def get_job(self, job_id: str) -> Optional[JobIngestRecord]:
        record = self._find_by_field(self.tables.jobs, "job_id", job_id)
        if not record:
            return None
        return JobIngestRecord.from_dict(record.get("fields", {}))

    def upsert_fit_score(self, record: FitScoreRecord) -> None:
        composite_id = f"{record.job_id}::{record.role_track.value}"
        payload = record.to_dict()
        payload["fit_id"] = composite_id
        self._upsert_by_field(
            table=self.tables.fit_scores,
            id_field="fit_id",
            id_value=composite_id,
            fields=payload,
        )

    def list_fit_scores(self, job_id: str | None = None) -> List[FitScoreRecord]:
        formula = None
        if job_id:
            formula = f"{{job_id}}='{_escape_formula_value(job_id)}'"
        records = self._list_records(self.tables.fit_scores, formula=formula)
        return [FitScoreRecord.from_dict(rec.get("fields", {})) for rec in records]

    def get_fit_score(self, job_id: str, role_track: str) -> Optional[FitScoreRecord]:
        fit_id = f"{job_id}::{role_track}"
        record = self._find_by_field(self.tables.fit_scores, "fit_id", fit_id)
        if not record:
            return None
        return FitScoreRecord.from_dict(record.get("fields", {}))

    def upsert_application(self, record: ApplicationRecord) -> None:
        self._upsert_by_field(
            table=self.tables.applications,
            id_field="application_id",
            id_value=record.application_id,
            fields=record.to_dict(),
        )

    def get_application(self, application_id: str) -> Optional[ApplicationRecord]:
        record = self._find_by_field(
            self.tables.applications, "application_id", application_id
        )
        if not record:
            return None
        return ApplicationRecord.from_dict(record.get("fields", {}))

    def find_application_by_job(self, job_id: str) -> Optional[ApplicationRecord]:
        formula = (
            f"AND({{job_id}}='{_escape_formula_value(job_id)}',"
            "{status}!='closed')"
        )
        records = self._list_records(self.tables.applications, formula=formula, max_records=1)
        if not records:
            return None
        return ApplicationRecord.from_dict(records[0].get("fields", {}))

    def list_applications(self) -> List[ApplicationRecord]:
        records = self._list_records(self.tables.applications)
        return [ApplicationRecord.from_dict(rec.get("fields", {})) for rec in records]

    def list_review_queue(self) -> List[ApplicationRecord]:
        formula = "AND({owner_action}='hold',{status}='new')"
        records = self._list_records(self.tables.applications, formula=formula)
        return [ApplicationRecord.from_dict(rec.get("fields", {})) for rec in records]

    def upsert_company_context(self, record: CompanyContextRecord) -> None:
        self._upsert_by_field(
            table=self.tables.companies,
            id_field="company",
            id_value=record.company,
            fields=record.to_dict(),
        )

    def list_company_context(self) -> Dict[str, CompanyContextRecord]:
        records = self._list_records(self.tables.companies)
        result: Dict[str, CompanyContextRecord] = {}
        for rec in records:
            item = CompanyContextRecord.from_dict(rec.get("fields", {}))
            if item.company:
                result[item.company.lower()] = item
        return result

    def upsert_contact(self, record: ContactRecord) -> None:
        self._upsert_by_field(
            table=self.tables.contacts,
            id_field="contact_id",
            id_value=record.contact_id,
            fields=record.to_dict(),
        )

    def list_contacts(
        self,
        job_id: str | None = None,
        company: str | None = None,
    ) -> List[ContactRecord]:
        formula = None
        if job_id and company:
            formula = (
                f"AND({{job_id}}='{_escape_formula_value(job_id)}',"
                f"{{company}}='{_escape_formula_value(company)}')"
            )
        elif job_id:
            formula = f"{{job_id}}='{_escape_formula_value(job_id)}'"
        elif company:
            formula = f"{{company}}='{_escape_formula_value(company)}'"
        records = self._list_records(self.tables.contacts, formula=formula)
        return [ContactRecord.from_dict(rec.get("fields", {})) for rec in records]

    def add_document(self, record: DocumentRecord) -> None:
        self._create_record(self.tables.documents, record.to_dict())

    def list_documents(self, application_id: str | None = None) -> List[DocumentRecord]:
        formula = None
        if application_id:
            formula = f"{{application_id}}='{_escape_formula_value(application_id)}'"
        records = self._list_records(self.tables.documents, formula=formula)
        return [
            DocumentRecord(
                document_id=str(rec.get("fields", {}).get("document_id", "")),
                application_id=str(rec.get("fields", {}).get("application_id", "")),
                document_type=str(rec.get("fields", {}).get("document_type", "")),
                path_or_url=str(rec.get("fields", {}).get("path_or_url", "")),
                created_at=str(rec.get("fields", {}).get("created_at", "")),
            )
            for rec in records
        ]

    def add_activity(self, record: ActivityLogRecord) -> None:
        self._create_record(self.tables.activity_log, record.to_dict())

    def list_activity(self) -> List[ActivityLogRecord]:
        records = self._list_records(self.tables.activity_log)
        return [
            ActivityLogRecord(
                activity_id=str(rec.get("fields", {}).get("activity_id", "")),
                entity_type=str(rec.get("fields", {}).get("entity_type", "")),
                entity_id=str(rec.get("fields", {}).get("entity_id", "")),
                event=str(rec.get("fields", {}).get("event", "")),
                event_at=str(rec.get("fields", {}).get("event_at", "")),
                details=str(rec.get("fields", {}).get("details", "")),
            )
            for rec in records
        ]

    def _upsert_by_field(
        self,
        table: str,
        id_field: str,
        id_value: str,
        fields: Dict[str, object],
    ) -> None:
        existing = self._find_by_field(table, id_field, id_value)
        if existing:
            record_id = existing.get("id")
            if isinstance(record_id, str) and record_id:
                self._patch_record(table, record_id, fields)
                return
        self._create_record(table, fields)

    def _find_by_field(
        self,
        table: str,
        field_name: str,
        field_value: str,
    ) -> Optional[Dict[str, object]]:
        formula = f"{{{field_name}}}='{_escape_formula_value(field_value)}'"
        records = self._list_records(table, formula=formula, max_records=1)
        if not records:
            return None
        return records[0]

    def _list_records(
        self,
        table: str,
        formula: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        encoded_table = quote(table)
        url = f"https://api.airtable.com/v0/{self.base_id}/{encoded_table}"
        query: List[str] = []
        if formula:
            query.append(f"filterByFormula={quote(formula)}")
        if max_records is not None:
            query.append(f"maxRecords={max_records}")
        if query:
            url = f"{url}?{'&'.join(query)}"
        response = request_json(
            method="GET",
            url=url,
            headers=self._headers,
        )
        records = response.body.get("records", [])
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)]

    def _create_record(self, table: str, fields: Dict[str, object]) -> None:
        encoded_table = quote(table)
        url = f"https://api.airtable.com/v0/{self.base_id}/{encoded_table}"
        payload = {"records": [{"fields": _serialize_fields(fields)}]}
        request_json(method="POST", url=url, headers=self._headers, payload=payload)

    def _patch_record(self, table: str, record_id: str, fields: Dict[str, object]) -> None:
        encoded_table = quote(table)
        url = f"https://api.airtable.com/v0/{self.base_id}/{encoded_table}/{record_id}"
        payload = {"fields": _serialize_fields(fields)}
        request_json(method="PATCH", url=url, headers=self._headers, payload=payload)

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }


def _escape_formula_value(value: str) -> str:
    return value.replace("'", "\\'")


def _serialize_fields(fields: Dict[str, object]) -> Dict[str, object]:
    serialized: Dict[str, object] = {}
    for key, value in fields.items():
        if isinstance(value, (dict, list)):
            serialized[key] = json.dumps(value, ensure_ascii=False)
        else:
            serialized[key] = value
    return serialized
