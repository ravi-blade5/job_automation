from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import traceback
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List
from threading import Lock
from urllib.parse import parse_qs, urlparse

from .apify_refresh import refresh_apify_datasets
from .cli import _build_pipeline
from .config import load_settings
from .models import (
    ActivityLogRecord,
    ApplicationRecord,
    ApplicationStatus,
    FitScoreRecord,
    JobIngestRecord,
    OwnerAction,
)
from .pipeline import JobAutomationPipeline
from .resume_tailor import ResumeTailor, resolve_resume_tailor_file

ALLOWED_TRACKERS = {"airtable", "google_sheets", "json"}
INDEX_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "webapp_index.html"
)
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_PIPELINE_CACHE: Dict[str, JobAutomationPipeline] = {}
_PIPELINE_CACHE_LOCK = Lock()


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(
        description="Serve a lightweight review app for the job automation workflow."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--tracker",
        choices=sorted(ALLOWED_TRACKERS),
        default=settings.tracker_backend,
    )
    args = parser.parse_args()

    tracker_backend = _normalize_tracker_backend(args.tracker, settings.tracker_backend)
    handler_class = _build_handler(default_tracker=tracker_backend)
    server = ThreadingHTTPServer((args.host, args.port), handler_class)
    print(f"Job automation web app running at http://{args.host}:{args.port}")
    print(f"Default tracker: {tracker_backend}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web app...")
    finally:
        server.server_close()


def build_overview_payload(
    pipeline: JobAutomationPipeline,
    tracker_backend: str,
) -> Dict[str, object]:
    snapshot = _build_snapshot(pipeline, include_fit_scores=True, include_activity=True)
    jobs = snapshot["jobs"]
    applications = snapshot["applications"]
    followups_due = snapshot["followups_due"]
    status_counts = snapshot["status_counts"]
    review_queue = snapshot["review_queue"]
    activity = snapshot["activity"]

    return {
        "tracker": tracker_backend,
        "summary": {
            "jobs_total": len(jobs),
            "applications_total": len(applications),
            "review_queue_total": len(review_queue),
            "followups_due_total": len(followups_due),
            "status_counts": dict(status_counts),
        },
        "dashboard": snapshot["dashboard"],
        "intelligence": _intelligence_summary(pipeline),
        "source_conversion": snapshot["source_conversion"],
        "review_queue": review_queue,
        "jobs": [item.to_dict() for item in jobs],
        "applications": [item.to_dict() for item in applications],
        "recent_jobs": [item.to_dict() for item in jobs[:30]],
        "recent_applications": [item.to_dict() for item in applications[:30]],
        "followups_due": [item.to_dict() for item in followups_due[:20]],
        "activity": [item.to_dict() for item in activity[:40]],
    }


def _build_handler(default_tracker: str):
    class JobAutomationHandler(BaseHTTPRequestHandler):
        server_version = "JobAutomationWeb/1.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                path_parts = [part for part in parsed.path.split("/") if part]
                if parsed.path == "/":
                    self._send_html(
                        HTTPStatus.OK,
                        _render_index_html(default_tracker=default_tracker),
                    )
                    return
                if parsed.path == "/api/health":
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "data": {
                                "service": "job_automation_webapp",
                                "default_tracker": default_tracker,
                            },
                        },
                    )
                    return
                if parsed.path == "/api/overview":
                    tracker_backend = _tracker_from_query(parsed.query, default_tracker)
                    pipeline = _pipeline_for_tracker(tracker_backend)
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "data": build_overview_payload(
                                pipeline=pipeline,
                                tracker_backend=tracker_backend,
                            ),
                        },
                    )
                    return
                if parsed.path == "/api/dashboard":
                    tracker_backend = _tracker_from_query(parsed.query, default_tracker)
                    pipeline = _pipeline_for_tracker(tracker_backend)
                    snapshot = _build_snapshot(
                        pipeline,
                        include_fit_scores=False,
                        include_activity=False,
                    )
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "data": {
                                "tracker": tracker_backend,
                                "summary": {
                                    "jobs_total": len(snapshot["jobs"]),
                                    "applications_total": len(snapshot["applications"]),
                                    "review_queue_total": len(snapshot["review_queue"]),
                                    "followups_due_total": len(snapshot["followups_due"]),
                                    "status_counts": dict(snapshot["status_counts"]),
                                },
                                "dashboard": snapshot["dashboard"],
                                "intelligence": _intelligence_summary(pipeline),
                                "source_conversion": snapshot["source_conversion"],
                                "followups_due": [
                                    item.to_dict() for item in snapshot["followups_due"][:20]
                                ],
                            },
                        },
                    )
                    return
                if len(path_parts) == 4 and path_parts[:2] == ["files", "applications"]:
                    tracker_backend = _tracker_from_query(parsed.query, default_tracker)
                    pipeline = _pipeline_for_tracker(tracker_backend)
                    document_path = _resolve_application_document(
                        pipeline,
                        application_id=path_parts[2],
                        document_type=path_parts[3],
                    )
                    self._send_file(document_path)
                    return
                if len(path_parts) == 4 and path_parts[:2] == ["files", "resume-tailor"]:
                    settings = load_settings()
                    document_path = resolve_resume_tailor_file(
                        artifacts_dir=settings.artifacts_dir,
                        run_id=path_parts[2],
                        filename=path_parts[3],
                        gcs_bucket=settings.gcs_bucket,
                        gcs_prefix=settings.gcs_artifacts_prefix,
                        gcp_project_id=settings.gcp_project_id,
                    )
                    self._send_file(document_path)
                    return
                self._send_error_json(HTTPStatus.NOT_FOUND, "Route not found.")
            except ValueError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except PermissionError as exc:
                self._send_error_json(HTTPStatus.FORBIDDEN, str(exc))
            except (LookupError, FileNotFoundError) as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                traceback.print_exc()
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    _format_exception(exc),
                )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/run-daily":
                    tracker_backend = _tracker_from_query(parsed.query, default_tracker)
                    pipeline = _pipeline_for_tracker(
                        tracker_backend,
                        refresh_apify=_env_bool("JOB_AUTOMATION_REFRESH_APIFY_BEFORE_DAILY", False),
                    )
                    result = pipeline.run_daily()
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "data": {
                                "tracker": tracker_backend,
                                "result": {
                                    "ingested": result.ingested,
                                    "deduped": result.deduped,
                                    "scored": result.scored,
                                    "queued": result.queued,
                                },
                            },
                        },
                    )
                    return

                if parsed.path == "/api/rescore":
                    tracker_backend = _tracker_from_query(parsed.query, default_tracker)
                    pipeline = _pipeline_for_tracker(tracker_backend, refresh_cache=True)
                    scored = pipeline.rescore_all_jobs()
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "data": {
                                "tracker": tracker_backend,
                                "scored": scored,
                            },
                        },
                    )
                    return

                if parsed.path == "/api/resume-tailor":
                    settings = load_settings()
                    payload = self._read_json_body()
                    tailor = ResumeTailor(
                        resume_dir=settings.resume_dir,
                        artifacts_dir=settings.artifacts_dir,
                        gcs_bucket=settings.gcs_bucket,
                        gcs_prefix=settings.gcs_artifacts_prefix,
                        gcp_project_id=settings.gcp_project_id,
                    )
                    result = tailor.generate(
                        job_description=str(payload.get("job_description", "")),
                        target_track=str(payload.get("target_track", "auto")),
                        role_title=str(payload.get("role_title", "")),
                        company=str(payload.get("company", "")),
                    )
                    self._send_json(HTTPStatus.OK, {"ok": True, "data": result.to_dict()})
                    return

                path_parts = [part for part in parsed.path.split("/") if part]
                if len(path_parts) == 4 and path_parts[:2] == ["api", "applications"]:
                    tracker_backend = _tracker_from_query(parsed.query, default_tracker)
                    application_id = path_parts[2]
                    action = path_parts[3]
                    pipeline = _pipeline_for_tracker(tracker_backend)
                    payload = self._read_json_body()

                    if action == "approve":
                        record = pipeline.approve_application(application_id)
                        self._send_json(HTTPStatus.OK, {"ok": True, "data": record.to_dict()})
                        return
                    if action == "reject":
                        record = pipeline.reject_application(application_id)
                        self._send_json(HTTPStatus.OK, {"ok": True, "data": record.to_dict()})
                        return
                    if action == "generate-artifacts":
                        generated = pipeline.generate_artifacts(application_id)
                        self._send_json(HTTPStatus.OK, {"ok": True, "data": generated})
                        return
                    if action == "mark-applied":
                        applied_on = _parse_applied_on(payload)
                        record = pipeline.mark_applied(
                            application_id,
                            applied_date=applied_on,
                        )
                        self._send_json(HTTPStatus.OK, {"ok": True, "data": record.to_dict()})
                        return
                    if action == "advance-status":
                        target_status = _parse_target_status(payload)
                        record = pipeline.advance_status(application_id, target_status)
                        self._send_json(HTTPStatus.OK, {"ok": True, "data": record.to_dict()})
                        return
                    if action == "mark-followup-done":
                        record = pipeline.mark_followup_done(application_id)
                        self._send_json(HTTPStatus.OK, {"ok": True, "data": record.to_dict()})
                        return

                self._send_error_json(HTTPStatus.NOT_FOUND, "Route not found.")
            except ValueError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except PermissionError as exc:
                self._send_error_json(HTTPStatus.FORBIDDEN, str(exc))
            except (LookupError, FileNotFoundError) as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                traceback.print_exc()
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    _format_exception(exc),
                )

        def log_message(self, format: str, *args: object) -> None:
            print(f"[job_automation_web] {self.address_string()} - {format % args}")

        def _read_json_body(self) -> Dict[str, object]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                return {}
            raw_body = self.rfile.read(content_length)
            if not raw_body:
                return {}
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("Request body must be valid JSON.") from exc
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object.")
            return body

        def _send_html(self, status: HTTPStatus, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, status: HTTPStatus, payload: Dict[str, object]) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            body = path.read_bytes()
            content_type, _ = mimetypes.guess_type(path.name)
            if path.suffix.lower() in {".txt", ".md"}:
                content_type = "text/plain; charset=utf-8"
            if not content_type:
                content_type = "application/octet-stream"
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'inline; filename="{path.name}"',
            )
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status: HTTPStatus, message: str) -> None:
            self._send_json(status, {"ok": False, "error": message})

    return JobAutomationHandler


def _pipeline_for_tracker(
    tracker_backend: str,
    *,
    refresh_apify: bool = False,
    refresh_cache: bool = False,
) -> JobAutomationPipeline:
    settings = load_settings()
    normalized_tracker = _normalize_tracker_backend(
        tracker_backend,
        settings.tracker_backend,
    )
    if refresh_apify and settings.apify_api_token:
        runtime_env = settings.data_dir / "runtime_apify.env"
        runtime_env.parent.mkdir(parents=True, exist_ok=True)
        if not runtime_env.exists():
            runtime_env.write_text("APIFY_DATASET_IDS=\n", encoding="utf-8")
        refresh_result = refresh_apify_datasets(
            api_token=settings.apify_api_token,
            env_path=runtime_env,
            summary_dir=settings.artifacts_dir / "apify_refresh",
            existing_dataset_ids=[],
            provider=settings.apify_refresh_provider,
            spec_path=settings.apify_refresh_spec_file,
            task_ids=settings.apify_task_ids,
            wait_seconds=settings.apify_run_wait_seconds,
        )
        if refresh_result.successful_dataset_ids:
            settings = replace(
                settings,
                apify_dataset_ids=refresh_result.successful_dataset_ids,
            )
        return _build_pipeline(settings, normalized_tracker)

    with _PIPELINE_CACHE_LOCK:
        if refresh_cache:
            _PIPELINE_CACHE.pop(normalized_tracker, None)
        cached = _PIPELINE_CACHE.get(normalized_tracker)
        if cached is not None:
            return cached
        pipeline = _build_pipeline(settings, normalized_tracker)
        _PIPELINE_CACHE[normalized_tracker] = pipeline
        return pipeline


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_tracker_backend(raw: str | None, fallback: str) -> str:
    tracker_backend = (raw or fallback).strip().lower()
    if tracker_backend not in ALLOWED_TRACKERS:
        raise ValueError(
            f"Unsupported tracker '{tracker_backend}'. Choose one of: {', '.join(sorted(ALLOWED_TRACKERS))}."
        )
    return tracker_backend


def _intelligence_summary(pipeline: JobAutomationPipeline) -> Dict[str, object]:
    intelligence = getattr(getattr(pipeline, "scorer", None), "sheet_intelligence", None)
    if not intelligence:
        return {
            "sheet_intelligence_enabled": False,
            "keyword_count": 0,
            "benchmark_jd_count": 0,
        }
    return {
        "sheet_intelligence_enabled": True,
        "keyword_count": getattr(intelligence, "keyword_count", 0),
        "benchmark_jd_count": getattr(intelligence, "benchmark_count", 0),
    }


def _tracker_from_query(query_string: str, default_tracker: str) -> str:
    params = parse_qs(query_string)
    tracker_raw = params.get("tracker", [default_tracker])[0]
    return _normalize_tracker_backend(tracker_raw, default_tracker)


def _parse_applied_on(payload: Dict[str, object]) -> date:
    raw = str(payload.get("applied_on", "")).strip()
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("applied_on must be in YYYY-MM-DD format.") from exc


def _parse_target_status(payload: Dict[str, object]) -> ApplicationStatus:
    raw = str(payload.get("status", "")).strip().lower()
    if not raw:
        raise ValueError("status is required.")
    try:
        return ApplicationStatus(raw)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported status '{raw}'. Choose one of: {', '.join(item.value for item in ApplicationStatus)}."
        ) from exc


def _build_snapshot(
    pipeline: JobAutomationPipeline,
    *,
    include_fit_scores: bool,
    include_activity: bool,
) -> Dict[str, object]:
    tracker = pipeline.tracker
    jobs = _sorted_jobs(tracker.list_jobs())
    applications = _sorted_applications(tracker.list_applications())
    fit_scores = tracker.list_fit_scores() if include_fit_scores else []
    activity = _sorted_activity(tracker.list_activity()) if include_activity else []

    job_index = {job.job_id: job for job in jobs}
    fit_index = {
        (fit.job_id, fit.role_track.value): fit
        for fit in fit_scores
    }
    queue_items = [
        application
        for application in applications
        if application.owner_action == OwnerAction.HOLD
        and application.status == ApplicationStatus.NEW
    ]
    followups_due = _followups_due_from_applications(applications)
    status_counts = Counter(item.status.value for item in applications)

    review_queue: List[Dict[str, object]] = []
    for application in queue_items:
        job = job_index.get(application.job_id)
        fit = fit_index.get((application.job_id, application.role_track.value))
        review_queue.append(
            {
                "application": application.to_dict(),
                "job": job.to_dict() if job else None,
                "fit_score": fit.to_dict() if fit else None,
            }
        )

    return {
        "jobs": jobs,
        "applications": applications,
        "activity": activity,
        "fit_scores": fit_scores,
        "review_queue": review_queue,
        "followups_due": followups_due,
        "status_counts": status_counts,
        "dashboard": _dashboard_from_records(applications, jobs),
        "source_conversion": _source_conversion_from_records(applications, job_index),
    }


def _sorted_jobs(jobs: List[JobIngestRecord]) -> List[JobIngestRecord]:
    return sorted(
        jobs,
        key=lambda item: (item.scraped_at or "", item.date_posted or "", item.job_id),
        reverse=True,
    )


def _sorted_applications(applications: List[ApplicationRecord]) -> List[ApplicationRecord]:
    return sorted(
        applications,
        key=lambda item: (item.updated_at or "", item.created_at or "", item.application_id),
        reverse=True,
    )


def _sorted_activity(activity: List[ActivityLogRecord]) -> List[ActivityLogRecord]:
    return sorted(
        activity,
        key=lambda item: (item.event_at or "", item.activity_id),
        reverse=True,
    )


def _followups_due_from_applications(
    applications: List[ApplicationRecord],
    on_date: date | None = None,
) -> List[ApplicationRecord]:
    target_date = (on_date or date.today()).isoformat()
    due = []
    for application in applications:
        if not application.next_followup_on:
            continue
        if application.status in (ApplicationStatus.REJECTED, ApplicationStatus.CLOSED):
            continue
        if application.next_followup_on <= target_date:
            due.append(application)
    return due


def _dashboard_from_records(
    applications: List[ApplicationRecord],
    jobs: List[JobIngestRecord],
) -> Dict[str, float]:
    total = len(applications)
    if total == 0:
        return {
            "applications_total": 0,
            "interview_rate_pct": 0.0,
            "offer_rate_pct": 0.0,
            "source_count": 0,
            "median_response_days": 0.0,
        }

    interviews = sum(
        1
        for app in applications
        if app.status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.CLOSED)
    )
    offers = sum(1 for app in applications if app.status == ApplicationStatus.OFFER)
    job_index = {job.job_id: job for job in jobs}
    source_set = {
        job_index[app.job_id].source
        for app in applications
        if app.job_id in job_index
    }

    response_days = []
    for app in applications:
        if not app.applied_on:
            continue
        if app.status not in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.CLOSED):
            continue
        applied = _to_date(app.applied_on)
        updated = _to_date(app.updated_at[:10])
        if applied and updated:
            response_days.append(max((updated - applied).days, 0))

    return {
        "applications_total": float(total),
        "interview_rate_pct": round((interviews / total) * 100, 2),
        "offer_rate_pct": round((offers / total) * 100, 2),
        "source_count": float(len(source_set)),
        "median_response_days": float(_median(response_days)),
    }


def _source_conversion_from_records(
    applications: List[ApplicationRecord],
    job_index: Dict[str, JobIngestRecord],
) -> Dict[str, Dict[str, int]]:
    result: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"applications": 0, "interviews": 0, "offers": 0}
    )
    for application in applications:
        job = job_index.get(application.job_id)
        if not job:
            continue
        entry = result[job.source]
        entry["applications"] += 1
        if application.status in (
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.CLOSED,
        ):
            entry["interviews"] += 1
        if application.status == ApplicationStatus.OFFER:
            entry["offers"] += 1
    return dict(result)


def _resolve_application_document(
    pipeline: JobAutomationPipeline,
    *,
    application_id: str,
    document_type: str,
) -> Path:
    application = pipeline.tracker.get_application(application_id)
    if not application:
        raise LookupError(f"Application not found: {application_id}")
    raw_path = application.documents.get(document_type, "").strip()
    if not raw_path:
        raise LookupError(
            f"No stored document '{document_type}' for application {application_id}."
        )
    document_path = Path(raw_path).expanduser().resolve()
    allowed_roots = [WORKSPACE_ROOT]
    artifact_generator = getattr(pipeline, "artifact_generator", None)
    for attr in ("artifacts_root", "resume_dir"):
        root = getattr(artifact_generator, attr, None)
        if root:
            allowed_roots.append(Path(root).resolve())
    if not any(_is_relative_to(document_path, root) for root in allowed_roots):
        raise PermissionError("Document path is outside the allowed workspace.")
    if not document_path.is_file():
        raise FileNotFoundError(f"Document not found: {document_path}")
    return document_path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def _to_date(raw: str) -> date | None:
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None


def _median(values: List[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def _render_index_html(default_tracker: str) -> str:
    template = INDEX_TEMPLATE.read_text(encoding="utf-8")
    return template.replace("__DEFAULT_TRACKER__", html.escape(default_tracker, quote=True))


if __name__ == "__main__":
    main()
