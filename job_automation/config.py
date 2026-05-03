import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


def _load_env_file_if_present() -> None:
    package_root = Path(__file__).resolve().parents[1]
    workspace_root = package_root.parent
    candidates = []
    for candidate in (
        workspace_root / ".env",
        package_root / ".env",
        Path.cwd() / ".env",
        Path.cwd() / "job_automation" / ".env",
    ):
        if candidate not in candidates:
            candidates.append(candidate)

    original_env_keys = set(os.environ.keys())
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if not key or key in original_env_keys:
                    continue
                if not value and key in os.environ:
                    continue
                os.environ[key] = value
        except OSError:
            continue


def _split_csv(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _as_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_airtable_base_id(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("app") and "/" not in value:
        return value
    match = re.search(r"(app[a-zA-Z0-9]+)", value)
    if match:
        return match.group(1)
    return value


def _materialize_env_file(env_name: str, default_target: str) -> Path | None:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    target = Path(os.getenv(f"{env_name}_FILE", default_target).strip()).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    return target


@dataclass(frozen=True)
class Settings:
    tracker_backend: str
    timezone: str
    daily_windows: List[str]
    region_filters: List[str]
    company_focus_keywords: List[str]
    title_include_keywords: List[str]
    title_exclude_keywords: List[str]

    mock_jobs_file: Path
    use_mock_source: bool

    apify_api_token: str
    apify_dataset_ids: List[str]
    apify_fetch_limit: int
    apify_task_ids: List[str]
    apify_refresh_provider: str
    apify_refresh_spec_file: Path
    apify_run_wait_seconds: int

    firecrawl_api_key: str
    firecrawl_career_urls: List[str]
    firecrawl_max_links_per_domain: int

    google_ai_studio_api_key: str
    google_ai_studio_model: str

    perplexity_api_key: str
    perplexity_model: str

    airtable_api_token: str
    airtable_base_id: str
    airtable_table_jobs: str
    airtable_table_fit_scores: str
    airtable_table_applications: str
    airtable_table_companies: str
    airtable_table_contacts: str
    airtable_table_documents: str
    airtable_table_activity_log: str

    google_sheets_spreadsheet_id: str
    google_sheets_credentials_file: Path
    google_sheets_sheet_jobs: str
    google_sheets_sheet_fit_scores: str
    google_sheets_sheet_applications: str
    google_sheets_sheet_companies: str
    google_sheets_sheet_contacts: str
    google_sheets_sheet_documents: str
    google_sheets_sheet_activity_log: str

    sheet_intelligence_enabled: bool
    keyword_spreadsheet_id: str
    jd_repository_spreadsheet_id: str
    sheet_intelligence_max_jds: int

    must_apply_threshold: int
    good_fit_threshold: int

    gcp_project_id: str
    gcs_bucket: str
    gcs_artifacts_prefix: str

    data_dir: Path
    artifacts_dir: Path
    resume_dir: Path
    templates_dir: Path


def load_settings() -> Settings:
    _load_env_file_if_present()

    data_dir = Path(
        os.getenv("JOB_AUTOMATION_DATA_DIR", "./job_automation/data").strip()
    ).resolve()
    artifacts_dir = Path(
        os.getenv("JOB_AUTOMATION_ARTIFACTS_DIR", "./job_automation/artifacts").strip()
    ).resolve()
    package_root = Path(__file__).resolve().parents[1]
    resume_dir = package_root / "resume"
    templates_dir = package_root / "job_automation" / "templates"

    data_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    default_apify_spec_file = package_root / "docs" / "apify_targeted_ravi_03042026.json"
    google_credentials_file = _materialize_env_file(
        "GOOGLE_SHEETS_CREDENTIALS_JSON",
        "/tmp/job_automation/google_service_account.json",
    ) or Path(
        os.getenv(
            "GOOGLE_SHEETS_CREDENTIALS_FILE",
            "./job_automation/google_service_account.json",
        ).strip()
    ).resolve()

    return Settings(
        tracker_backend=os.getenv("JOB_AUTOMATION_TRACKER", "json").strip().lower(),
        timezone=os.getenv("JOB_AUTOMATION_TIMEZONE", "Asia/Kolkata").strip(),
        daily_windows=_split_csv(
            os.getenv("JOB_AUTOMATION_DAILY_WINDOWS", "08:30,13:30,20:30").strip()
        ),
        region_filters=_split_csv(
            os.getenv("JOB_AUTOMATION_REGION_FILTERS", "India,Singapore").strip()
        ),
        company_focus_keywords=_split_csv(
            os.getenv("JOB_AUTOMATION_COMPANY_FOCUS_KEYWORDS", "").strip()
        ),
        title_include_keywords=_split_csv(
            os.getenv(
                "JOB_AUTOMATION_TITLE_INCLUDE_KEYWORDS",
                (
                    "ai solution expert,genai solution expert,solutions expert,genai,enterprise ai,"
                    "ai platform,product manager,product owner,product lead,technical product manager,"
                    "solutions lead,solutions consultant,solution consultant,solution architect,"
                    "customer engineer,sales engineer,technical consultant,ai strategy,presales"
                ),
            ).strip()
        ),
        title_exclude_keywords=_split_csv(
            os.getenv(
                "JOB_AUTOMATION_TITLE_EXCLUDE_KEYWORDS",
                (
                    "designer,accountant,communications,marketing,assistant,"
                    "planner,travel,real estate,imaging specialist,financial analyst,"
                    "office manager,account manager,sales executive,internship"
                ),
            ).strip()
        ),
        mock_jobs_file=Path(
            os.getenv(
                "JOB_AUTOMATION_MOCK_JOBS_FILE",
                "./job_automation/docs/sample_jobs.json",
            ).strip()
        ).resolve(),
        use_mock_source=_as_bool("JOB_AUTOMATION_USE_MOCK_SOURCE", False),
        apify_api_token=os.getenv("APIFY_API_TOKEN", "").strip(),
        apify_dataset_ids=_split_csv(os.getenv("APIFY_DATASET_IDS", "").strip()),
        apify_fetch_limit=_as_int("JOB_AUTOMATION_APIFY_FETCH_LIMIT", 25),
        apify_task_ids=_split_csv(os.getenv("APIFY_TASK_IDS", "").strip()),
        apify_refresh_provider=os.getenv("JOB_AUTOMATION_APIFY_PROVIDER", "linkedin").strip().lower(),
        apify_refresh_spec_file=Path(
            os.getenv(
                "JOB_AUTOMATION_APIFY_SPEC_FILE",
                str(default_apify_spec_file),
            ).strip()
        ).resolve(),
        apify_run_wait_seconds=_as_int("JOB_AUTOMATION_APIFY_RUN_WAIT_SECONDS", 300),
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", "").strip(),
        firecrawl_career_urls=_split_csv(
            os.getenv("FIRECRAWL_CAREER_URLS", "").strip()
        ),
        firecrawl_max_links_per_domain=_as_int(
            "FIRECRAWL_MAX_LINKS_PER_DOMAIN", 12
        ),
        google_ai_studio_api_key=os.getenv("GOOGLE_AI_STUDIO_API_KEY", "").strip(),
        google_ai_studio_model=os.getenv(
            "GOOGLE_AI_STUDIO_MODEL", "gemini-2.5-pro"
        ).strip(),
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY", "").strip(),
        perplexity_model=os.getenv("PERPLEXITY_MODEL", "sonar").strip(),
        airtable_api_token=os.getenv("AIRTABLE_API_TOKEN", "").strip(),
        airtable_base_id=_normalize_airtable_base_id(
            os.getenv("AIRTABLE_BASE_ID", "").strip()
        ),
        airtable_table_jobs=os.getenv("AIRTABLE_TABLE_JOBS", "Jobs").strip(),
        airtable_table_fit_scores=os.getenv(
            "AIRTABLE_TABLE_FIT_SCORES", "FitScores"
        ).strip(),
        airtable_table_applications=os.getenv(
            "AIRTABLE_TABLE_APPLICATIONS", "Applications"
        ).strip(),
        airtable_table_companies=os.getenv(
            "AIRTABLE_TABLE_COMPANIES", "Companies"
        ).strip(),
        airtable_table_contacts=os.getenv("AIRTABLE_TABLE_CONTACTS", "Contacts").strip(),
        airtable_table_documents=os.getenv(
            "AIRTABLE_TABLE_DOCUMENTS", "Documents"
        ).strip(),
        airtable_table_activity_log=os.getenv(
            "AIRTABLE_TABLE_ACTIVITY_LOG", "ActivityLog"
        ).strip(),
        google_sheets_spreadsheet_id=os.getenv(
            "GOOGLE_SHEETS_SPREADSHEET_ID", ""
        ).strip(),
        google_sheets_credentials_file=google_credentials_file,
        google_sheets_sheet_jobs=os.getenv("GOOGLE_SHEETS_SHEET_JOBS", "Jobs").strip(),
        google_sheets_sheet_fit_scores=os.getenv(
            "GOOGLE_SHEETS_SHEET_FIT_SCORES", "FitScores"
        ).strip(),
        google_sheets_sheet_applications=os.getenv(
            "GOOGLE_SHEETS_SHEET_APPLICATIONS", "Applications"
        ).strip(),
        google_sheets_sheet_companies=os.getenv(
            "GOOGLE_SHEETS_SHEET_COMPANIES", "Companies"
        ).strip(),
        google_sheets_sheet_contacts=os.getenv(
            "GOOGLE_SHEETS_SHEET_CONTACTS", "Contacts"
        ).strip(),
        google_sheets_sheet_documents=os.getenv(
            "GOOGLE_SHEETS_SHEET_DOCUMENTS", "Documents"
        ).strip(),
        google_sheets_sheet_activity_log=os.getenv(
            "GOOGLE_SHEETS_SHEET_ACTIVITY_LOG", "ActivityLog"
        ).strip(),
        sheet_intelligence_enabled=_as_bool("JOB_AUTOMATION_ENABLE_SHEET_INTELLIGENCE", False),
        keyword_spreadsheet_id=os.getenv(
            "JOB_AUTOMATION_KEYWORD_SPREADSHEET_ID", ""
        ).strip(),
        jd_repository_spreadsheet_id=os.getenv(
            "JOB_AUTOMATION_JD_REPOSITORY_SPREADSHEET_ID", ""
        ).strip(),
        sheet_intelligence_max_jds=_as_int(
            "JOB_AUTOMATION_SHEET_INTELLIGENCE_MAX_JDS", 100
        ),
        must_apply_threshold=_as_int("JOB_AUTOMATION_MUST_APPLY_THRESHOLD", 75),
        good_fit_threshold=_as_int("JOB_AUTOMATION_GOOD_FIT_THRESHOLD", 60),
        gcp_project_id=os.getenv(
            "GCP_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "")
        ).strip(),
        gcs_bucket=os.getenv("JOB_AUTOMATION_GCS_BUCKET", "")
        .strip()
        .removeprefix("gs://")
        .rstrip("/"),
        gcs_artifacts_prefix=os.getenv(
            "JOB_AUTOMATION_GCS_ARTIFACTS_PREFIX", "artifacts"
        )
        .strip()
        .strip("/"),
        data_dir=data_dir,
        artifacts_dir=artifacts_dir,
        resume_dir=resume_dir,
        templates_dir=templates_dir,
    )
