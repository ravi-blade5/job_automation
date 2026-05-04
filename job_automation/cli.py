from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import List

from .apify_refresh import refresh_apify_datasets
from .artifacts import ApplicationArtifactGenerator
from .config import Settings, load_settings
from .enrichment.jd_parser import GeminiJDParser, RuleBasedJDParser
from .enrichment.sheet_intelligence import load_google_sheet_intelligence
from .gcp_bundle import build_gcp_sync_bundle
from .openclaw_sync import sync_to_openclaw_workspace
from .outreach import FirecrawlContactFinder, ManualOutreachLeadBuilder
from .enrichment.perplexity import CompanyEnricher, PerplexityCompanyEnricher
from .models import ApplicationStatus
from .pipeline import JobAutomationPipeline
from .profile_store import ResumeProfileStore
from .scoring import FitScorer
from .sources.apify_source import ApifyJobSource
from .sources.firecrawl_source import FirecrawlJobSource
from .sources.mock_source import MockJobSource
from .tracking.airtable import AirtableTableConfig, AirtableTrackingRepository
from .tracking.local_json import LocalJSONTrackingRepository
from .vapi_prep import VapiInterviewPrep


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "build-gcp-sync-bundle":
        adb_root = Path(args.adb_root).expanduser() if args.adb_root else Path(__file__).resolve().parents[2]
        athena_root = Path(args.athena_root).expanduser() if args.athena_root else adb_root / "Athena-Public"
        openclaw_root = (
            Path(args.openclaw_root).expanduser()
            if args.openclaw_root
            else (Path.home() / ".openclaw")
        )
        output_path = (
            Path(args.output).expanduser()
            if args.output
            else adb_root / "deploy" / "gcp_vm" / ".dist" / "openclaw-athena-sync.tar.gz"
        )
        result = build_gcp_sync_bundle(
            adb_root=adb_root,
            athena_root=athena_root,
            openclaw_root=openclaw_root,
            output_path=output_path,
        )
        print(
            json.dumps(
                {
                    "output_path": str(result.output_path),
                    "manifest_path": str(result.manifest_path),
                    "files_included": result.files_included,
                    "generated_at": result.generated_at.isoformat(),
                },
                indent=2,
            )
        )
        return

    settings = load_settings()
    tracker_backend = (getattr(args, "tracker", None) or settings.tracker_backend).lower()
    pipeline = _build_pipeline(settings, tracker_backend)

    if args.command == "run-daily":
        result = pipeline.run_daily()
        print(
            json.dumps(
                {
                    "ingested": result.ingested,
                    "deduped": result.deduped,
                    "scored": result.scored,
                    "queued": result.queued,
                },
                indent=2,
            )
        )
        return

    if args.command == "rescore-jobs":
        scored = pipeline.rescore_all_jobs()
        print(json.dumps({"scored": scored}, indent=2))
        return

    if args.command == "refresh-apify-datasets":
        repo_root = Path(args.repo_root).expanduser() if args.repo_root else Path(__file__).resolve().parents[2]
        env_path = Path(args.env_path).expanduser() if args.env_path else repo_root / ".env"
        summary_dir = (
            Path(args.summary_dir).expanduser()
            if args.summary_dir
            else (settings.artifacts_dir / "apify_refresh")
        )
        result = refresh_apify_datasets(
            api_token=settings.apify_api_token,
            env_path=env_path,
            summary_dir=summary_dir,
            existing_dataset_ids=settings.apify_dataset_ids,
            provider=args.provider or settings.apify_refresh_provider,
            spec_path=Path(args.spec).expanduser() if args.spec else settings.apify_refresh_spec_file,
            task_ids=settings.apify_task_ids,
            wait_seconds=args.wait_seconds or settings.apify_run_wait_seconds,
        )
        print(
            json.dumps(
                {
                    "provider": result.provider,
                    "actor_id": result.actor_id,
                    "task_ids": result.task_ids,
                    "successful_dataset_ids": result.successful_dataset_ids,
                    "used_existing_dataset_ids": result.used_existing_dataset_ids,
                    "updated_env": result.updated_env,
                    "summary_path": str(result.summary_path),
                    "run_count": len(result.runs),
                },
                indent=2,
            )
        )
        return

    if args.command == "list-review-queue":
        payload = [item.to_dict() for item in pipeline.tracker.list_review_queue()]
        print(json.dumps(payload, indent=2))
        return

    if args.command == "approve":
        application = pipeline.approve_application(args.application_id)
        print(json.dumps(application.to_dict(), indent=2))
        return

    if args.command == "reject":
        application = pipeline.reject_application(args.application_id)
        print(json.dumps(application.to_dict(), indent=2))
        return

    if args.command == "generate-artifacts":
        generated = pipeline.generate_artifacts(args.application_id)
        print(json.dumps(generated, indent=2))
        return

    if args.command == "mark-applied":
        applied_on = date.fromisoformat(args.applied_on) if args.applied_on else date.today()
        application = pipeline.mark_applied(args.application_id, applied_date=applied_on)
        print(json.dumps(application.to_dict(), indent=2))
        return

    if args.command == "advance-status":
        target = ApplicationStatus(args.target_status)
        application = pipeline.advance_status(args.application_id, target)
        print(json.dumps(application.to_dict(), indent=2))
        return

    if args.command == "followups-due":
        target_date = date.fromisoformat(args.on) if args.on else date.today()
        due = pipeline.followups_due(on_date=target_date)
        print(json.dumps([item.to_dict() for item in due], indent=2))
        return

    if args.command == "dashboard":
        payload = {
            "dashboard": pipeline.dashboard(),
            "source_conversion": pipeline.source_conversion(),
        }
        print(json.dumps(payload, indent=2))
        return

    if args.command == "build-interview-pack":
        app = pipeline.tracker.get_application(args.application_id)
        if not app:
            raise LookupError(f"Application not found: {args.application_id}")
        job = pipeline.tracker.get_job(app.job_id)
        if not job:
            raise LookupError(f"Job not found: {app.job_id}")
        prep = VapiInterviewPrep(settings.artifacts_dir)
        path = prep.build_mock_screen_pack(app, job)
        print(json.dumps({"application_id": app.application_id, "interview_pack": path}, indent=2))
        return

    if args.command == "build-outreach-leads":
        contact_finder = None
        if settings.firecrawl_api_key:
            contact_finder = FirecrawlContactFinder(api_key=settings.firecrawl_api_key)
        builder = ManualOutreachLeadBuilder(
            tracker=pipeline.tracker,
            artifacts_root=settings.artifacts_dir,
            contact_finder=contact_finder,
        )
        result = builder.build_export(refresh_contacts=bool(args.refresh_contacts))
        print(
            json.dumps(
                {
                    "leads_built": result.leads_built,
                    "contacts_discovered": result.contacts_discovered,
                    "csv_path": str(result.csv_path),
                    "json_path": str(result.json_path),
                },
                indent=2,
            )
        )
        return

    if args.command == "sync-openclaw-workspace":
        workspace_dir = Path(args.workspace_dir).expanduser() if args.workspace_dir else None
        repo_root = Path(args.repo_root).expanduser() if args.repo_root else None
        result = sync_to_openclaw_workspace(
            tracker=pipeline.tracker,
            artifacts_root=settings.artifacts_dir,
            workspace_dir=workspace_dir,
            repo_root=repo_root,
        )
        print(
            json.dumps(
                {
                    "workspace_dir": str(result.workspace_dir),
                    "job_hunt_dir": str(result.job_hunt_dir),
                    "status_dir": str(result.status_dir),
                    "athena_dir": str(result.athena_dir) if result.athena_dir else None,
                    "skill_path": str(result.skill_path) if result.skill_path else None,
                    "athena_skill_path": str(result.athena_skill_path) if result.athena_skill_path else None,
                    "summary_path": str(result.summary_path),
                    "refresh_status_path": str(result.refresh_status_path),
                    "refresh_status_json_path": str(result.refresh_status_json_path),
                    "readme_path": str(result.readme_path),
                    "daily_memory_path": str(result.daily_memory_path),
                    "latest_csv_path": str(result.latest_csv_path) if result.latest_csv_path else None,
                    "latest_json_path": str(result.latest_json_path) if result.latest_json_path else None,
                    "jobs_total": result.jobs_total,
                    "applications_total": result.applications_total,
                    "contacts_total": result.contacts_total,
                    "leads_total": result.leads_total,
                    "leads_with_email": result.leads_with_email,
                },
                indent=2,
            )
        )
        return

    raise RuntimeError(f"Unsupported command: {args.command}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automated job discovery pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_daily = sub.add_parser("run-daily")
    _add_tracker_arg(run_daily)

    rescore = sub.add_parser("rescore-jobs")
    _add_tracker_arg(rescore)

    refresh_apify = sub.add_parser("refresh-apify-datasets")
    refresh_apify.add_argument(
        "--repo-root",
        required=False,
        help="ADB_HCL repo root. Defaults to the current repo root.",
    )
    refresh_apify.add_argument(
        "--env-path",
        required=False,
        help="Path to the .env file whose APIFY_DATASET_IDS should be updated. Defaults to <repo-root>/.env.",
    )
    refresh_apify.add_argument(
        "--summary-dir",
        required=False,
        help="Directory for refresh summaries. Defaults to job_automation/artifacts/apify_refresh.",
    )
    refresh_apify.add_argument(
        "--provider",
        required=False,
        choices=["linkedin", "indeed"],
        help="Apify provider to run when APIFY_TASK_IDS is not configured.",
    )
    refresh_apify.add_argument(
        "--spec",
        required=False,
        help="JSON spec file containing queries, locations, and max_results_per_run.",
    )
    refresh_apify.add_argument(
        "--wait-seconds",
        required=False,
        type=int,
        help="Maximum wait time for a single Apify run before continuing.",
    )

    review_queue = sub.add_parser("list-review-queue")
    _add_tracker_arg(review_queue)

    approve = sub.add_parser("approve")
    _add_tracker_arg(approve)
    approve.add_argument("--application-id", required=True)

    reject = sub.add_parser("reject")
    _add_tracker_arg(reject)
    reject.add_argument("--application-id", required=True)

    generate = sub.add_parser("generate-artifacts")
    _add_tracker_arg(generate)
    generate.add_argument("--application-id", required=True)

    mark_applied = sub.add_parser("mark-applied")
    _add_tracker_arg(mark_applied)
    mark_applied.add_argument("--application-id", required=True)
    mark_applied.add_argument("--applied-on", required=False, help="YYYY-MM-DD")

    advance = sub.add_parser("advance-status")
    _add_tracker_arg(advance)
    advance.add_argument("--application-id", required=True)
    advance.add_argument(
        "--target-status",
        required=True,
        choices=[status.value for status in ApplicationStatus],
    )

    followups = sub.add_parser("followups-due")
    _add_tracker_arg(followups)
    followups.add_argument("--on", required=False, help="YYYY-MM-DD")

    dashboard = sub.add_parser("dashboard")
    _add_tracker_arg(dashboard)

    interview = sub.add_parser("build-interview-pack")
    _add_tracker_arg(interview)
    interview.add_argument("--application-id", required=True)

    outreach = sub.add_parser("build-outreach-leads")
    _add_tracker_arg(outreach)
    outreach.add_argument(
        "--refresh-contacts",
        action="store_true",
        help="Re-run Firecrawl contact discovery even when contacts already exist.",
    )

    sync_openclaw = sub.add_parser("sync-openclaw-workspace")
    _add_tracker_arg(sync_openclaw)
    sync_openclaw.add_argument(
        "--workspace-dir",
        required=False,
        help="Target OpenClaw workspace directory. Defaults to ~/.openclaw/workspace.",
    )
    sync_openclaw.add_argument(
        "--repo-root",
        required=False,
        help="ADB_HCL repo root used for tool guidance. Defaults to the current package workspace.",
    )

    gcp_bundle = sub.add_parser("build-gcp-sync-bundle")
    gcp_bundle.add_argument("--adb-root", required=False, help="ADB_HCL repo root. Defaults to the current repo.")
    gcp_bundle.add_argument(
        "--athena-root",
        required=False,
        help="Athena-Public repo root. Defaults to <adb-root>/Athena-Public.",
    )
    gcp_bundle.add_argument(
        "--openclaw-root",
        required=False,
        help="Local OpenClaw state root. Defaults to ~/.openclaw.",
    )
    gcp_bundle.add_argument(
        "--output",
        required=False,
        help="Output tar.gz path. Defaults to deploy/gcp_vm/.dist/openclaw-athena-sync.tar.gz.",
    )
    return parser


def _build_pipeline(settings: Settings, tracker_backend: str) -> JobAutomationPipeline:
    tracker = _build_tracker(settings, tracker_backend)
    sources = _build_sources(settings)
    sheet_intelligence = _build_sheet_intelligence(settings)
    resume_profile = ResumeProfileStore(
        data_dir=settings.data_dir,
        gcs_bucket=settings.gcs_bucket,
        gcs_prefix=settings.gcs_artifacts_prefix,
        gcp_project_id=settings.gcp_project_id,
    ).load()
    scorer = FitScorer(
        must_apply_threshold=settings.must_apply_threshold,
        good_fit_threshold=settings.good_fit_threshold,
        company_focus_keywords=settings.company_focus_keywords,
        sheet_intelligence=sheet_intelligence,
        resume_profile_keywords=resume_profile.keywords if resume_profile else [],
    )
    artifact_generator = ApplicationArtifactGenerator(
        artifacts_root=settings.artifacts_dir,
        resume_dir=settings.resume_dir,
        gcs_bucket=settings.gcs_bucket,
        gcs_prefix=settings.gcs_artifacts_prefix,
        gcp_project_id=settings.gcp_project_id,
    )
    jd_parser = _build_jd_parser(settings)
    enricher = _build_enricher(settings)
    return JobAutomationPipeline(
        sources=sources,
        tracker=tracker,
        scorer=scorer,
        artifact_generator=artifact_generator,
        jd_parser=jd_parser,
        company_enricher=enricher,
        region_filters=settings.region_filters,
        title_include_keywords=settings.title_include_keywords,
        title_exclude_keywords=settings.title_exclude_keywords,
    )


def _build_sources(settings: Settings) -> List:
    sources = []
    if settings.use_mock_source and settings.mock_jobs_file.exists():
        sources.append(MockJobSource(settings.mock_jobs_file))
    if settings.apify_api_token and settings.apify_dataset_ids:
        sources.append(
            ApifyJobSource(
                settings.apify_api_token,
                settings.apify_dataset_ids,
                fetch_limit=settings.apify_fetch_limit,
            )
        )
    if settings.firecrawl_api_key and settings.firecrawl_career_urls:
        sources.append(
            FirecrawlJobSource(
                settings.firecrawl_api_key,
                settings.firecrawl_career_urls,
                max_links_per_domain=settings.firecrawl_max_links_per_domain,
            )
        )
    return sources


def _add_tracker_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tracker",
        choices=["airtable", "json", "google_sheets"],
        default=None,
    )


def _build_tracker(settings: Settings, tracker_backend: str):
    if tracker_backend == "airtable":
        if not settings.airtable_api_token or not settings.airtable_base_id:
            raise RuntimeError(
                "Airtable tracker selected but AIRTABLE_API_TOKEN/AIRTABLE_BASE_ID not configured."
            )
        table_config = AirtableTableConfig(
            jobs=settings.airtable_table_jobs,
            fit_scores=settings.airtable_table_fit_scores,
            applications=settings.airtable_table_applications,
            companies=settings.airtable_table_companies,
            contacts=settings.airtable_table_contacts,
            documents=settings.airtable_table_documents,
            activity_log=settings.airtable_table_activity_log,
        )
        return AirtableTrackingRepository(
            api_token=settings.airtable_api_token,
            base_id=settings.airtable_base_id,
            tables=table_config,
        )
    if tracker_backend == "google_sheets":
        if not settings.google_sheets_spreadsheet_id:
            raise RuntimeError(
                "Google Sheets tracker selected but GOOGLE_SHEETS_SPREADSHEET_ID is not configured."
            )
        from .tracking.google_sheets import (
            GoogleSheetsTableConfig,
            GoogleSheetsTrackingRepository,
        )

        sheets = GoogleSheetsTableConfig(
            jobs=settings.google_sheets_sheet_jobs,
            fit_scores=settings.google_sheets_sheet_fit_scores,
            applications=settings.google_sheets_sheet_applications,
            companies=settings.google_sheets_sheet_companies,
            contacts=settings.google_sheets_sheet_contacts,
            documents=settings.google_sheets_sheet_documents,
            activity_log=settings.google_sheets_sheet_activity_log,
        )
        return GoogleSheetsTrackingRepository(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_file=settings.google_sheets_credentials_file,
            sheets=sheets,
        )
    return LocalJSONTrackingRepository(root_dir=settings.data_dir)


def _build_jd_parser(settings: Settings):
    if settings.google_ai_studio_api_key:
        return GeminiJDParser(
            api_key=settings.google_ai_studio_api_key,
            model=settings.google_ai_studio_model,
        )
    return RuleBasedJDParser()


def _build_enricher(settings: Settings) -> CompanyEnricher:
    if settings.perplexity_api_key:
        return PerplexityCompanyEnricher(
            api_key=settings.perplexity_api_key,
            model=settings.perplexity_model,
        )
    return CompanyEnricher()


def _build_sheet_intelligence(settings: Settings):
    if not settings.sheet_intelligence_enabled:
        return None
    if not (settings.keyword_spreadsheet_id or settings.jd_repository_spreadsheet_id):
        return None
    return load_google_sheet_intelligence(
        credentials_file=settings.google_sheets_credentials_file,
        keyword_spreadsheet_id=settings.keyword_spreadsheet_id,
        jd_repository_spreadsheet_id=settings.jd_repository_spreadsheet_id,
        max_benchmark_jds=settings.sheet_intelligence_max_jds,
    )


if __name__ == "__main__":
    main()
