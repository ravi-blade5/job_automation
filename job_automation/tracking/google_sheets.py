from __future__ import annotations

import json
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class GoogleSheetsTableConfig:
    jobs: str
    fit_scores: str
    applications: str
    companies: str
    contacts: str
    documents: str
    activity_log: str


class GoogleSheetsTrackingRepository(TrackingRepository):
    def __init__(
        self,
        spreadsheet_id: str,
        credentials_file: Path,
        sheets: GoogleSheetsTableConfig,
    ):
        self.spreadsheet_id = spreadsheet_id.strip()
        self.credentials_file = credentials_file
        self.sheets = sheets
        if not self.spreadsheet_id:
            raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is required for Google Sheets tracker.")
        if not self.credentials_file.exists():
            raise RuntimeError(
                f"Google credentials file not found: {self.credentials_file}. "
                "Set GOOGLE_SHEETS_CREDENTIALS_FILE."
            )

        try:
            import gspread  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "gspread is required for Google Sheets tracker. Run: pip install gspread google-auth"
            ) from exc

        self._gspread = gspread
        self.client = gspread.service_account(filename=str(self.credentials_file))
        self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)

        self._table_headers: Dict[str, List[str]] = {
            self.sheets.jobs: [
                "job_id",
                "source",
                "title_raw",
                "company",
                "location",
                "remote_type",
                "job_url",
                "description_text",
                "date_posted",
                "scraped_at",
            ],
            self.sheets.fit_scores: [
                "fit_id",
                "job_id",
                "role_track",
                "fit_score",
                "must_have_match_pct",
                "domain_match_pct",
                "seniority_match",
                "decision",
                "reason_codes",
            ],
            self.sheets.applications: [
                "application_id",
                "job_id",
                "status",
                "resume_variant",
                "cover_note_version",
                "owner_action",
                "applied_on",
                "next_followup_on",
                "role_track",
                "decision",
                "fit_score",
                "followup_dates",
                "documents",
                "created_at",
                "updated_at",
            ],
            self.sheets.companies: [
                "company",
                "funding_signal",
                "business_direction",
                "ai_maturity",
                "enriched_at",
            ],
            self.sheets.contacts: [
                "contact_id",
                "company",
                "name",
                "role",
                "channel",
                "contact_value",
                "notes",
                "job_id",
                "department",
                "source_url",
                "discovered_at",
            ],
            self.sheets.documents: [
                "document_id",
                "application_id",
                "document_type",
                "path_or_url",
                "created_at",
            ],
            self.sheets.activity_log: [
                "activity_id",
                "entity_type",
                "entity_id",
                "event",
                "event_at",
                "details",
            ],
        }
        self._worksheets: Dict[str, object] = {}
        self._rows_cache: Dict[str, List[Dict[str, object]]] = {}
        self._index_cache: Dict[tuple[str, str], Dict[str, int]] = {}

    def upsert_job(self, record: JobIngestRecord) -> None:
        secondary_match: Dict[str, str] = {}
        if record.job_url.strip():
            # If legacy/manual rows are missing job_id, match by job_url so
            # existing rows are updated instead of duplicated.
            secondary_match["job_url"] = record.job_url
        self._upsert_row(
            self.sheets.jobs,
            "job_id",
            record.job_id,
            record.to_dict(),
            secondary_match=secondary_match or None,
        )

    def list_jobs(self) -> List[JobIngestRecord]:
        rows = self._read_rows(self.sheets.jobs)
        return [JobIngestRecord.from_dict(row) for row in rows]

    def get_job(self, job_id: str) -> Optional[JobIngestRecord]:
        row = self._find_row(self.sheets.jobs, "job_id", job_id)
        return JobIngestRecord.from_dict(row) if row else None

    def upsert_fit_score(self, record: FitScoreRecord) -> None:
        fit_id = f"{record.job_id}::{record.role_track.value}"
        payload = record.to_dict()
        payload["fit_id"] = fit_id
        self._upsert_row(self.sheets.fit_scores, "fit_id", fit_id, payload)

    def list_fit_scores(self, job_id: str | None = None) -> List[FitScoreRecord]:
        rows = self._read_rows(self.sheets.fit_scores)
        mapped = [FitScoreRecord.from_dict(row) for row in rows]
        if job_id is None:
            return mapped
        return [item for item in mapped if item.job_id == job_id]

    def get_fit_score(self, job_id: str, role_track: str) -> Optional[FitScoreRecord]:
        fit_id = f"{job_id}::{role_track}"
        row = self._find_row(self.sheets.fit_scores, "fit_id", fit_id)
        return FitScoreRecord.from_dict(row) if row else None

    def upsert_application(self, record: ApplicationRecord) -> None:
        self._upsert_row(
            self.sheets.applications,
            "application_id",
            record.application_id,
            record.to_dict(),
        )

    def get_application(self, application_id: str) -> Optional[ApplicationRecord]:
        row = self._find_row(self.sheets.applications, "application_id", application_id)
        return ApplicationRecord.from_dict(row) if row else None

    def find_application_by_job(self, job_id: str) -> Optional[ApplicationRecord]:
        rows = self._read_rows(self.sheets.applications)
        for row in rows:
            if str(row.get("job_id", "")).strip() != job_id:
                continue
            if str(row.get("status", "")).strip() == "closed":
                continue
            return ApplicationRecord.from_dict(row)
        return None

    def list_applications(self) -> List[ApplicationRecord]:
        rows = self._read_rows(self.sheets.applications)
        return [ApplicationRecord.from_dict(row) for row in rows]

    def list_review_queue(self) -> List[ApplicationRecord]:
        return [
            app
            for app in self.list_applications()
            if app.owner_action.value == "hold" and app.status.value == "new"
        ]

    def upsert_company_context(self, record: CompanyContextRecord) -> None:
        self._upsert_row(
            self.sheets.companies,
            "company",
            record.company,
            record.to_dict(),
        )

    def list_company_context(self) -> Dict[str, CompanyContextRecord]:
        rows = self._read_rows(self.sheets.companies)
        mapped: Dict[str, CompanyContextRecord] = {}
        for row in rows:
            item = CompanyContextRecord.from_dict(row)
            if item.company:
                mapped[item.company.lower()] = item
        return mapped

    def upsert_contact(self, record: ContactRecord) -> None:
        self._upsert_row(
            self.sheets.contacts,
            "contact_id",
            record.contact_id,
            record.to_dict(),
        )

    def list_contacts(
        self,
        job_id: str | None = None,
        company: str | None = None,
    ) -> List[ContactRecord]:
        rows = self._read_rows(self.sheets.contacts)
        contacts = [ContactRecord.from_dict(row) for row in rows]
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
        self._append_row(self.sheets.documents, record.to_dict())

    def list_documents(self, application_id: str | None = None) -> List[DocumentRecord]:
        rows = self._read_rows(self.sheets.documents)
        mapped = [
            DocumentRecord(
                document_id=str(row.get("document_id", "")),
                application_id=str(row.get("application_id", "")),
                document_type=str(row.get("document_type", "")),
                path_or_url=str(row.get("path_or_url", "")),
                created_at=str(row.get("created_at", "")),
            )
            for row in rows
        ]
        if application_id is None:
            return mapped
        return [item for item in mapped if item.application_id == application_id]

    def add_activity(self, record: ActivityLogRecord) -> None:
        self._append_row(self.sheets.activity_log, record.to_dict())

    def list_activity(self) -> List[ActivityLogRecord]:
        rows = self._read_rows(self.sheets.activity_log)
        return [
            ActivityLogRecord(
                activity_id=str(row.get("activity_id", "")),
                entity_type=str(row.get("entity_type", "")),
                entity_id=str(row.get("entity_id", "")),
                event=str(row.get("event", "")),
                event_at=str(row.get("event_at", "")),
                details=str(row.get("details", "")),
            )
            for row in rows
        ]

    def _ensure_worksheet(self, sheet_name: str, headers: List[str]):
        try:
            worksheet = self._with_retry(lambda: self.spreadsheet.worksheet(sheet_name))
        except self._gspread.WorksheetNotFound:
            worksheet = self._with_retry(
                lambda: self.spreadsheet.add_worksheet(
                    title=sheet_name,
                    rows=2000,
                    cols=max(len(headers), 12),
                )
            )

        header_row = self._with_retry(lambda: worksheet.row_values(1))
        normalized_header_row = [value.strip() for value in header_row if value.strip()]
        if normalized_header_row == headers:
            return worksheet
        if normalized_header_row and headers[: len(normalized_header_row)] == normalized_header_row:
            self._with_retry(lambda: worksheet.update("A1", [headers]))
            return worksheet
        if normalized_header_row != headers:
            self._with_retry(lambda: worksheet.clear())
            self._with_retry(lambda: worksheet.update("A1", [headers]))
        return worksheet

    def _read_rows(self, sheet_name: str) -> List[Dict[str, object]]:
        if sheet_name in self._rows_cache:
            return list(self._rows_cache[sheet_name])
        worksheet = self._worksheet(sheet_name)
        rows = self._with_retry(lambda: worksheet.get_all_records(default_blank=""))
        cleaned: List[Dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not any(str(value).strip() for value in row.values()):
                continue
            cleaned.append(self._deserialize_row(row))
        self._rows_cache[sheet_name] = cleaned
        self._clear_index_cache_for_sheet(sheet_name)
        return list(cleaned)

    def _find_row(self, sheet_name: str, id_field: str, id_value: str) -> Optional[Dict[str, object]]:
        for row in self._read_rows(sheet_name):
            if str(row.get(id_field, "")).strip() == id_value:
                return row
        return None

    def _upsert_row(
        self,
        sheet_name: str,
        id_field: str,
        id_value: str,
        payload: Dict[str, object],
        secondary_match: Optional[Dict[str, str]] = None,
    ) -> None:
        worksheet = self._worksheet(sheet_name)
        headers = self._table_headers[sheet_name]
        records = self._read_rows(sheet_name)
        index_key = (sheet_name, id_field)
        normalized_id_value = _normalize_match_value(id_value)
        if index_key not in self._index_cache:
            self._index_cache[index_key] = {
                _normalize_match_value(row.get(id_field, "")): idx
                for idx, row in enumerate(records, start=2)
                if _normalize_match_value(row.get(id_field, ""))
            }
        row_number = self._index_cache[index_key].get(normalized_id_value)
        if row_number is None and secondary_match:
            for field_name, field_value in secondary_match.items():
                row_number = self._find_row_number_by_field(
                    records=records,
                    field_name=field_name,
                    field_value=field_value,
                )
                if row_number is not None:
                    break

        values = [self._serialize_value(payload.get(header, "")) for header in headers]
        normalized_payload = {header: payload.get(header, "") for header in headers}
        if row_number is None:
            self._with_retry(lambda: worksheet.append_row(values, value_input_option="RAW"))
            new_row_number = len(records) + 2
            records.append(self._deserialize_row(normalized_payload))
            self._rows_cache[sheet_name] = records
            if normalized_id_value:
                self._index_cache[index_key][normalized_id_value] = new_row_number
            return

        end_col = _column_label(len(headers))
        self._with_retry(
            lambda: worksheet.update(
                f"A{row_number}:{end_col}{row_number}",
                [values],
                value_input_option="RAW",
            )
        )
        records[row_number - 2] = self._deserialize_row(normalized_payload)
        self._rows_cache[sheet_name] = records
        if normalized_id_value:
            self._index_cache[index_key][normalized_id_value] = row_number

    def _find_row_number_by_field(
        self,
        records: List[Dict[str, object]],
        field_name: str,
        field_value: str,
    ) -> Optional[int]:
        normalized_field_value = _normalize_match_value(field_value)
        if not normalized_field_value:
            return None
        for idx, row in enumerate(records, start=2):
            if _normalize_match_value(row.get(field_name, "")) == normalized_field_value:
                return idx
        return None

    def _append_row(self, sheet_name: str, payload: Dict[str, object]) -> None:
        worksheet = self._worksheet(sheet_name)
        headers = self._table_headers[sheet_name]
        values = [self._serialize_value(payload.get(header, "")) for header in headers]
        self._with_retry(lambda: worksheet.append_row(values, value_input_option="RAW"))
        if sheet_name in self._rows_cache:
            rows = self._rows_cache[sheet_name]
            rows.append(self._deserialize_row({header: payload.get(header, "") for header in headers}))
            self._rows_cache[sheet_name] = rows

    def _serialize_value(self, value: object) -> object:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value

    def _deserialize_row(self, row: Dict[str, object]) -> Dict[str, object]:
        converted: Dict[str, object] = {}
        for key, value in row.items():
            if not isinstance(value, str):
                converted[key] = value
                continue
            stripped = value.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    converted[key] = json.loads(stripped)
                    continue
                except json.JSONDecodeError:
                    pass
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    converted[key] = json.loads(stripped)
                    continue
                except json.JSONDecodeError:
                    pass
            converted[key] = value
        return converted

    def _worksheet(self, sheet_name: str):
        if sheet_name in self._worksheets:
            return self._worksheets[sheet_name]
        worksheet = self._ensure_worksheet(sheet_name, self._table_headers[sheet_name])
        self._worksheets[sheet_name] = worksheet
        return worksheet

    def _clear_index_cache_for_sheet(self, sheet_name: str) -> None:
        keys_to_delete = [key for key in self._index_cache.keys() if key[0] == sheet_name]
        for key in keys_to_delete:
            del self._index_cache[key]

    def _with_retry(self, operation):
        delay_seconds = 2.0
        last_error = None
        for _attempt in range(5):
            try:
                return operation()
            except Exception as exc:
                if not _is_quota_error(exc):
                    raise
                last_error = exc
                time.sleep(delay_seconds)
                delay_seconds = min(delay_seconds * 1.8, 20.0)
        if last_error:
            raise last_error
        raise RuntimeError("Google Sheets operation failed unexpectedly")


def _column_label(index_1_based: int) -> str:
    if index_1_based <= 0:
        return "A"
    result = ""
    index = index_1_based
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    quota_markers = ("429", "quota exceeded", "rate limit", "too many requests")
    return any(marker in text for marker in quota_markers)


def _normalize_match_value(value: object) -> str:
    return str(value).strip().lower()
