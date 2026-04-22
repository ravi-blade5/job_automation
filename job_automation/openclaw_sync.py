from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterable, List

from .tracking.repository import TrackingRepository

SYNC_START_MARKER = "<!-- JOB_HUNT_SYNC:START -->"
SYNC_END_MARKER = "<!-- JOB_HUNT_SYNC:END -->"
AGENTS_START_MARKER = "<!-- JOB_HUNT_AGENT_GUIDE:START -->"
AGENTS_END_MARKER = "<!-- JOB_HUNT_AGENT_GUIDE:END -->"
TOOLS_START_MARKER = "<!-- JOB_HUNT_TOOL_GUIDE:START -->"
TOOLS_END_MARKER = "<!-- JOB_HUNT_TOOL_GUIDE:END -->"
ATHENA_AGENTS_START_MARKER = "<!-- ATHENA_AGENT_GUIDE:START -->"
ATHENA_AGENTS_END_MARKER = "<!-- ATHENA_AGENT_GUIDE:END -->"
ATHENA_TOOLS_START_MARKER = "<!-- ATHENA_TOOL_GUIDE:START -->"
ATHENA_TOOLS_END_MARKER = "<!-- ATHENA_TOOL_GUIDE:END -->"
ATHENA_ASTROLOGY_MEMORY_START_MARKER = "<!-- ATHENA_ASTROLOGY_SYNC:START -->"
ATHENA_ASTROLOGY_MEMORY_END_MARKER = "<!-- ATHENA_ASTROLOGY_SYNC:END -->"
ATHENA_ASTROLOGY_AGENTS_START_MARKER = "<!-- ATHENA_ASTROLOGY_AGENT_GUIDE:START -->"
ATHENA_ASTROLOGY_AGENTS_END_MARKER = "<!-- ATHENA_ASTROLOGY_AGENT_GUIDE:END -->"
ATHENA_ASTROLOGY_TOOLS_START_MARKER = "<!-- ATHENA_ASTROLOGY_TOOL_GUIDE:START -->"
ATHENA_ASTROLOGY_TOOLS_END_MARKER = "<!-- ATHENA_ASTROLOGY_TOOL_GUIDE:END -->"


@dataclass(frozen=True)
class OpenClawSyncResult:
    workspace_dir: Path
    job_hunt_dir: Path
    status_dir: Path
    athena_dir: Path | None
    skill_path: Path | None
    athena_skill_path: Path | None
    latest_csv_path: Path | None
    latest_json_path: Path | None
    summary_path: Path
    refresh_status_path: Path
    refresh_status_json_path: Path
    readme_path: Path
    daily_memory_path: Path
    leads_total: int
    leads_with_email: int
    jobs_total: int
    applications_total: int
    contacts_total: int


def sync_to_openclaw_workspace(
    *,
    tracker: TrackingRepository,
    artifacts_root: Path,
    workspace_dir: Path | None = None,
    repo_root: Path | None = None,
    athena_root: Path | None = None,
    now_utc: datetime | None = None,
) -> OpenClawSyncResult:
    now_utc = now_utc or datetime.now(UTC)
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    athena_root = (athena_root or (repo_root / "Athena-Public")).resolve()
    workspace_dir = (workspace_dir or (Path.home() / ".openclaw" / "workspace")).resolve()
    job_hunt_dir = workspace_dir / "job_hunt"
    tracker_dir = job_hunt_dir / "tracker"
    outreach_dir = job_hunt_dir / "outreach"
    summary_dir = job_hunt_dir / "summary"
    status_dir = job_hunt_dir / "status"

    for path in (job_hunt_dir, tracker_dir, outreach_dir, summary_dir, status_dir):
        path.mkdir(parents=True, exist_ok=True)

    skill_path = _install_job_hunt_skill(workspace_dir, repo_root=repo_root)
    _update_agents_guide(workspace_dir, skill_path)
    _update_tools_guide(workspace_dir, repo_root=repo_root)
    athena_dir = _sync_athena_context(workspace_dir, athena_root=athena_root)
    athena_skill_path = _install_athena_skill(workspace_dir)
    _update_athena_agents_guide(workspace_dir, athena_dir=athena_dir, skill_path=athena_skill_path)
    _update_athena_tools_guide(
        workspace_dir,
        athena_dir=athena_dir,
        athena_root=athena_root,
        skill_path=athena_skill_path,
    )
    _sync_astrology_profiles(athena_dir=athena_dir, repo_root=repo_root)
    _update_athena_memory_guide(workspace_dir)
    _update_athena_astrology_agents_guide(workspace_dir, athena_dir=athena_dir)
    _update_athena_astrology_tools_guide(workspace_dir, athena_dir=athena_dir, repo_root=repo_root)

    latest_csv_source = _latest_matching_file(artifacts_root / "outreach", "*.csv")
    latest_json_source = _latest_matching_file(artifacts_root / "outreach", "*.json")

    latest_csv_path = None
    latest_json_path = None
    if latest_csv_source:
        latest_csv_path = outreach_dir / "latest_manual_outreach_leads.csv"
        shutil.copy2(latest_csv_source, latest_csv_path)
        shutil.copy2(latest_csv_source, outreach_dir / latest_csv_source.name)
    if latest_json_source:
        latest_json_path = outreach_dir / "latest_manual_outreach_leads.json"
        shutil.copy2(latest_json_source, latest_json_path)
        shutil.copy2(latest_json_source, outreach_dir / latest_json_source.name)

    jobs = [item.to_dict() for item in tracker.list_jobs()]
    fit_scores = [item.to_dict() for item in tracker.list_fit_scores()]
    applications = [item.to_dict() for item in tracker.list_applications()]
    review_queue = [item.to_dict() for item in tracker.list_review_queue()]
    companies = [item.to_dict() for item in tracker.list_company_context().values()]
    contacts = [item.to_dict() for item in tracker.list_contacts()]
    activity = [item.to_dict() for item in tracker.list_activity()]

    _write_json(tracker_dir / "jobs.json", jobs)
    _write_json(tracker_dir / "fit_scores.json", fit_scores)
    _write_json(tracker_dir / "applications.json", applications)
    _write_json(tracker_dir / "review_queue.json", review_queue)
    _write_json(tracker_dir / "companies.json", companies)
    _write_json(tracker_dir / "contacts.json", contacts)
    _write_json(tracker_dir / "activity_log.json", activity)

    leads = _load_leads(latest_json_source)
    leads_total = len(leads)
    leads_with_email = sum(1 for row in leads if str(row.get("contact_email", "")).strip())
    refresh_status_path, refresh_status_json_path = _ensure_refresh_status_files(status_dir)

    summary_path = summary_dir / "latest_outreach_summary.md"
    summary_path.write_text(
        _render_summary(
            synced_at=now_utc,
            latest_csv_path=latest_csv_path,
            latest_json_path=latest_json_path,
            refresh_status_path=refresh_status_path,
            jobs_total=len(jobs),
            applications_total=len(applications),
            contacts_total=len(contacts),
            leads=leads,
        ),
        encoding="utf-8",
    )

    readme_path = job_hunt_dir / "README.md"
    readme_path.write_text(
        _render_readme(
            synced_at=now_utc,
            source_repo_root=repo_root,
            latest_csv_path=latest_csv_path,
            latest_json_path=latest_json_path,
            refresh_status_path=refresh_status_path,
            summary_path=summary_path,
        ),
        encoding="utf-8",
    )

    daily_memory_path = _daily_memory_path(workspace_dir, now_utc.date())
    _update_daily_memory(
        daily_memory_path=daily_memory_path,
        synced_at=now_utc,
        summary_path=summary_path,
        leads_total=leads_total,
        leads_with_email=leads_with_email,
        jobs_total=len(jobs),
        applications_total=len(applications),
        contacts_total=len(contacts),
    )

    return OpenClawSyncResult(
        workspace_dir=workspace_dir,
        job_hunt_dir=job_hunt_dir,
        status_dir=status_dir,
        athena_dir=athena_dir,
        skill_path=skill_path,
        athena_skill_path=athena_skill_path,
        latest_csv_path=latest_csv_path,
        latest_json_path=latest_json_path,
        summary_path=summary_path,
        refresh_status_path=refresh_status_path,
        refresh_status_json_path=refresh_status_json_path,
        readme_path=readme_path,
        daily_memory_path=daily_memory_path,
        leads_total=leads_total,
        leads_with_email=leads_with_email,
        jobs_total=len(jobs),
        applications_total=len(applications),
        contacts_total=len(contacts),
    )


def _sync_athena_context(workspace_dir: Path, *, athena_root: Path) -> Path | None:
    context_root = athena_root / ".context"
    if not context_root.exists():
        return None

    athena_dir = workspace_dir / "athena"
    athena_dir.mkdir(parents=True, exist_ok=True)

    for name in ("CANONICAL.md", "project_state.md", "PROTOCOL_SUMMARIES.md", "TAG_INDEX.md"):
        source = context_root / name
        if source.exists():
            shutil.copy2(source, athena_dir / name)

    _mirror_tree(context_root / "memory_bank", athena_dir / "memory_bank")
    _mirror_tree(context_root / "memories" / "case_studies", athena_dir / "memories" / "case_studies")
    _mirror_tree(context_root / "memories" / "session_logs", athena_dir / "memories" / "session_logs")

    readme_path = athena_dir / "README.md"
    readme_path.write_text(_render_athena_readme(athena_dir=athena_dir, athena_root=athena_root), encoding="utf-8")
    return athena_dir


def _sync_astrology_profiles(*, athena_dir: Path | None, repo_root: Path) -> Path | None:
    if athena_dir is None:
        return None

    source_dir = repo_root / "astrology_profiles"
    if not source_dir.exists():
        return None

    target_dir = athena_dir / "external" / "astrology_profiles"
    _mirror_tree(source_dir, target_dir)
    return target_dir


def _render_summary(
    *,
    synced_at: datetime,
    latest_csv_path: Path | None,
    latest_json_path: Path | None,
    refresh_status_path: Path,
    jobs_total: int,
    applications_total: int,
    contacts_total: int,
    leads: List[Dict[str, object]],
) -> str:
    lines = [
        "# Job Hunt Outreach Summary",
        "",
        f"- Synced at: `{synced_at.isoformat()}`",
        f"- Jobs tracked: **{jobs_total}**",
        f"- Applications tracked: **{applications_total}**",
        f"- Public contacts tracked: **{contacts_total}**",
        f"- Latest outreach CSV: `{latest_csv_path}`" if latest_csv_path else "- Latest outreach CSV: unavailable",
        f"- Latest outreach JSON: `{latest_json_path}`" if latest_json_path else "- Latest outreach JSON: unavailable",
        f"- Refresh status file: `{refresh_status_path}`",
        "",
        "## Top Leads With Email",
        "",
        "| Fit | Company | Role | Dept | Email | Source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in _top_leads(leads):
        lines.append(
            "| {fit} | {company} | {job} | {dept} | {email} | {source} |".format(
                fit=row.get("fit_score", ""),
                company=_escape_pipe(str(row.get("company", ""))),
                job=_escape_pipe(str(row.get("job_title", ""))),
                dept=_escape_pipe(str(row.get("department_hint", ""))),
                email=_escape_pipe(str(row.get("contact_email", ""))),
                source=_escape_pipe(str(row.get("contact_source_url", ""))),
            )
        )

    if not any(str(item.get("contact_email", "")).strip() for item in leads):
        lines.extend(
            [
                "| - | - | - | - | - | - |",
                "",
                "No public emails were available in the latest outreach export.",
            ]
        )

    lines.extend(
        [
            "",
            "## How Vik Should Use This",
            "",
            "- Use `job_hunt/summary/latest_outreach_summary.md` for a fast overview.",
            "- Use `job_hunt/status/latest_refresh_status.md` for in-flight or just-finished refresh progress.",
            "- Use `job_hunt/outreach/latest_manual_outreach_leads.json` for full row-level details.",
            "- Use `job_hunt/tracker/review_queue.json` to focus on jobs still awaiting approval.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_readme(
    *,
    synced_at: datetime,
    source_repo_root: Path,
    latest_csv_path: Path | None,
    latest_json_path: Path | None,
    refresh_status_path: Path,
    summary_path: Path,
) -> str:
    lines = [
        "# Job Hunt Workspace Mirror",
        "",
        f"This folder is synced from `{source_repo_root / 'job_automation'}`.",
        f"Last sync: `{synced_at.isoformat()}`",
        "",
        "## Contents",
        "",
        "- `summary/latest_outreach_summary.md`: human-readable summary for Vik.",
        "- `status/latest_refresh_status.md`: current or most recent refresh-progress status for long-running updates.",
        "- `status/latest_refresh_status.json`: machine-readable refresh status payload.",
        "- `outreach/latest_manual_outreach_leads.csv`: latest spreadsheet-friendly export.",
        "- `outreach/latest_manual_outreach_leads.json`: latest row-level JSON export.",
        "- `tracker/jobs.json`: tracked jobs.",
        "- `tracker/applications.json`: tracked applications.",
        "- `tracker/review_queue.json`: applications still awaiting action.",
        "- `tracker/contacts.json`: discovered public contacts.",
        "",
        "## Latest Files",
        "",
        f"- Summary: `{summary_path}`",
        f"- Refresh status: `{refresh_status_path}`",
        f"- Latest CSV: `{latest_csv_path}`" if latest_csv_path else "- Latest CSV: unavailable",
        f"- Latest JSON: `{latest_json_path}`" if latest_json_path else "- Latest JSON: unavailable",
    ]
    return "\n".join(lines) + "\n"


def _update_daily_memory(
    *,
    daily_memory_path: Path,
    synced_at: datetime,
    summary_path: Path,
    leads_total: int,
    leads_with_email: int,
    jobs_total: int,
    applications_total: int,
    contacts_total: int,
) -> None:
    if daily_memory_path.exists():
        content = daily_memory_path.read_text(encoding="utf-8")
    else:
        daily_memory_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"# {daily_memory_path.stem}\n\n"

    block = "\n".join(
        [
            SYNC_START_MARKER,
            "## Job Hunt Sync",
            "",
            f"- Latest sync copied job-hunt data into `job_hunt/` at `{synced_at.isoformat()}`.",
            f"- Jobs tracked: **{jobs_total}**",
            f"- Applications tracked: **{applications_total}**",
            f"- Public contacts tracked: **{contacts_total}**",
            f"- Outreach leads: **{leads_total}** total, **{leads_with_email}** with public email",
            f"- Start with `job_hunt/summary/latest_outreach_summary.md` for the current shortlist.",
            f"- Summary file: `{summary_path}`",
            f"- Full export mirror lives under `job_hunt/outreach/` and tracker JSONs live under `job_hunt/tracker/`.",
            SYNC_END_MARKER,
        ]
    )

    if SYNC_START_MARKER in content and SYNC_END_MARKER in content:
        before, remainder = content.split(SYNC_START_MARKER, 1)
        _, after = remainder.split(SYNC_END_MARKER, 1)
        updated = before.rstrip() + "\n\n" + block + after
    else:
        updated = content.rstrip() + "\n\n" + block + "\n"
    daily_memory_path.write_text(updated, encoding="utf-8")


def _update_agents_guide(workspace_dir: Path, skill_path: Path | None) -> None:
    path = workspace_dir / "AGENTS.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# AGENTS.md\n\n"

    skill_line = (
        f"- First read `{skill_path.relative_to(workspace_dir).as_posix()}/SKILL.md` for job-hunt requests."
        if skill_path
        else "- First read `skills/job-hunt-outreach/SKILL.md` for job-hunt requests."
    )
    block = "\n".join(
        [
            AGENTS_START_MARKER,
            "## Job Hunt Workflow",
            "",
            "- When Ravi asks about jobs, applications, recruiting contacts, outreach, or cover letters, use the job-hunt workflow.",
            skill_line,
            "- Start with `job_hunt/summary/latest_outreach_summary.md` for the current shortlist.",
            "- For refresh follow-ups like `status`, `is it done`, or `what is the status`, read `job_hunt/status/latest_refresh_status.md` before answering.",
            "- Use `job_hunt/outreach/latest_manual_outreach_leads.json` for row-level lead data.",
            "- Use `job_hunt/tracker/review_queue.json`, `applications.json`, and `contacts.json` only as needed.",
            f"- If Ravi asks for fresh data and the `exec` tool is available, run `{_refresh_command(workspace_dir=workspace_dir, repo_root=None, refresh_contacts=False)}`.",
            "- Keep outreach manual. Draft, rank, and summarize, but do not send emails automatically.",
            AGENTS_END_MARKER,
        ]
    )
    path.write_text(_replace_or_append_block(content, AGENTS_START_MARKER, AGENTS_END_MARKER, block), encoding="utf-8")


def _update_tools_guide(workspace_dir: Path, *, repo_root: Path) -> None:
    path = workspace_dir / "TOOLS.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# TOOLS.md\n\n"

    mirror_path = workspace_dir / "job_hunt"
    skill_path = workspace_dir / "skills" / "job-hunt-outreach" / "SKILL.md"
    scripts_dir = workspace_dir / "skills" / "job-hunt-outreach" / "scripts"
    status_path = mirror_path / "status" / "latest_refresh_status.md"
    refresh_command = _refresh_command(workspace_dir=workspace_dir, repo_root=repo_root, refresh_contacts=False)
    refresh_contacts_command = _refresh_command(
        workspace_dir=workspace_dir,
        repo_root=repo_root,
        refresh_contacts=True,
    )

    block = "\n".join(
        [
            TOOLS_START_MARKER,
            "## Job Hunt Paths",
            "",
            f"- Job hunt mirror: `{mirror_path}`",
            f"- Job hunt skill: `{skill_path}`",
            f"- Refresh scripts: `{scripts_dir}`",
            f"- Refresh status file: `{status_path}`",
            f"- Job automation repo root: `{repo_root}`",
            "",
            "Refresh command:",
            "",
            f"```{_command_fence(workspace_dir)}",
            refresh_command,
            "```",
            "",
            "Refresh with contact discovery:",
            "",
            f"```{_command_fence(workspace_dir)}",
            refresh_contacts_command,
            "```",
            TOOLS_END_MARKER,
        ]
    )
    path.write_text(_replace_or_append_block(content, TOOLS_START_MARKER, TOOLS_END_MARKER, block), encoding="utf-8")


def _update_athena_agents_guide(workspace_dir: Path, *, athena_dir: Path | None, skill_path: Path | None) -> None:
    path = workspace_dir / "AGENTS.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# AGENTS.md\n\n"

    athena_root = athena_dir or (workspace_dir / "athena")
    skill_line = (
        f"- First read `{skill_path.relative_to(workspace_dir).as_posix()}/SKILL.md` for Athena-backed requests."
        if skill_path
        else "- First read `skills/athena-context-router/SKILL.md` for Athena-backed requests."
    )
    block = "\n".join(
        [
            ATHENA_AGENTS_START_MARKER,
            "## Athena Workflow",
            "",
            "- When Ravi asks about prior context, validated timelines, case studies, stable preferences, dossiers, or astrology, use the Athena workflow first.",
            skill_line,
            f"- Start with `{(athena_root / 'README.md').relative_to(workspace_dir).as_posix()}` for the mirror layout.",
            f"- Prefer `{(athena_root / 'memory_bank' / 'activeContext.md').relative_to(workspace_dir).as_posix()}` and the rest of `memory_bank/` before digging into session logs.",
            f"- Use `{(athena_root / 'CANONICAL.md').relative_to(workspace_dir).as_posix()}` for stable canonical facts when available.",
            f"- Use `{(athena_root / 'memories' / 'case_studies').relative_to(workspace_dir).as_posix()}` for reusable examples and `{(athena_root / 'memories' / 'session_logs').relative_to(workspace_dir).as_posix()}` only for chronology or provenance checks.",
            "- Distinguish stable memory from session evidence. Prefer the narrowest file set that answers the request.",
            ATHENA_AGENTS_END_MARKER,
        ]
    )
    path.write_text(
        _replace_or_append_block(content, ATHENA_AGENTS_START_MARKER, ATHENA_AGENTS_END_MARKER, block),
        encoding="utf-8",
    )


def _update_athena_tools_guide(
    workspace_dir: Path,
    *,
    athena_dir: Path | None,
    athena_root: Path,
    skill_path: Path | None,
) -> None:
    path = workspace_dir / "TOOLS.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# TOOLS.md\n\n"

    athena_mirror = athena_dir or (workspace_dir / "athena")
    skill_text = (
        str(skill_path.relative_to(workspace_dir))
        if skill_path
        else "skills/athena-context-router/SKILL.md"
    )
    block = "\n".join(
        [
            ATHENA_TOOLS_START_MARKER,
            "## Athena Paths",
            "",
            f"- Athena workspace mirror: `{athena_mirror}`",
            f"- Athena source root: `{athena_root}`",
            f"- Athena router skill: `{skill_text}`",
            f"- Memory bank: `{athena_mirror / 'memory_bank'}`",
            f"- Active context: `{athena_mirror / 'memory_bank' / 'activeContext.md'}`",
            f"- User context: `{athena_mirror / 'memory_bank' / 'userContext.md'}`",
            f"- Case studies: `{athena_mirror / 'memories' / 'case_studies'}`",
            f"- Session logs: `{athena_mirror / 'memories' / 'session_logs'}`",
            f"- Canonical memory: `{athena_mirror / 'CANONICAL.md'}`",
            "",
            "Use Athena mirror files when the request depends on prior validated work rather than only the current chat.",
            ATHENA_TOOLS_END_MARKER,
        ]
    )
    path.write_text(
        _replace_or_append_block(content, ATHENA_TOOLS_START_MARKER, ATHENA_TOOLS_END_MARKER, block),
        encoding="utf-8",
    )


def _update_athena_memory_guide(workspace_dir: Path) -> None:
    path = workspace_dir / "MEMORY.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# MEMORY.md\n\n"

    block = "\n".join(
        [
            ATHENA_ASTROLOGY_MEMORY_START_MARKER,
            "## Athena And Astrology",
            "",
            "- For astrology, dossier-heavy, or prior-case requests, consult `athena/` before relying only on the current prompt.",
            "- External astrology dossier mirror lives at `athena/external/astrology_profiles/`.",
            "- Use the age-biased questioning heuristic by default:",
            "  - under 32: marriage and relationship",
            "  - 30+: children",
            "  - 35+: money and wealth structure",
            "  - 45+: peace of mind and family settlement",
            "  - 55-60+: health",
            "- Ask sibling count, birth order, and major family structure facts early when relevant.",
            "- Treat spouse, newborn, and new household entrants as family-system activators, not simplistic blame sources.",
            ATHENA_ASTROLOGY_MEMORY_END_MARKER,
        ]
    )
    path.write_text(
        _replace_or_append_block(
            content,
            ATHENA_ASTROLOGY_MEMORY_START_MARKER,
            ATHENA_ASTROLOGY_MEMORY_END_MARKER,
            block,
        ),
        encoding="utf-8",
    )


def _update_athena_astrology_agents_guide(workspace_dir: Path, *, athena_dir: Path | None) -> None:
    path = workspace_dir / "AGENTS.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# AGENTS.md\n\n"

    athena_root = athena_dir or (workspace_dir / "athena")
    block = "\n".join(
        [
            ATHENA_ASTROLOGY_AGENTS_START_MARKER,
            "## Astrology Workflow",
            "",
            "- For astrology requests, start with `athena/memory_bank/activeContext.md` and relevant `athena/memories/case_studies/` files.",
            f"- Use `{(athena_root / 'external' / 'astrology_profiles' / 'README.md').relative_to(workspace_dir).as_posix()}` and mirrored dossier files for person-specific context.",
            "- Keep separate: chart fact, validated event, and inference.",
            "- Ask age-based calibration questions and sibling/family-structure questions before deep prediction when they are missing.",
            "- Promote only stable takeaways, corrected misses, and validated timing patterns into memory.",
            ATHENA_ASTROLOGY_AGENTS_END_MARKER,
        ]
    )
    path.write_text(
        _replace_or_append_block(
            content,
            ATHENA_ASTROLOGY_AGENTS_START_MARKER,
            ATHENA_ASTROLOGY_AGENTS_END_MARKER,
            block,
        ),
        encoding="utf-8",
    )


def _update_athena_astrology_tools_guide(
    workspace_dir: Path,
    *,
    athena_dir: Path | None,
    repo_root: Path,
) -> None:
    path = workspace_dir / "TOOLS.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# TOOLS.md\n\n"

    athena_mirror = athena_dir or (workspace_dir / "athena")
    block = "\n".join(
        [
            ATHENA_ASTROLOGY_TOOLS_START_MARKER,
            "## Athena Astrology Paths",
            "",
            f"- Athena workspace mirror: `{athena_mirror}`",
            f"- Mirrored astrology dossiers: `{athena_mirror / 'external' / 'astrology_profiles'}`",
            f"- Source astrology dossiers: `{repo_root / 'astrology_profiles'}`",
            "",
            "Use the mirrored dossier set when prior astrology context is person-specific and more detailed than the case-study summaries.",
            ATHENA_ASTROLOGY_TOOLS_END_MARKER,
        ]
    )
    path.write_text(
        _replace_or_append_block(
            content,
            ATHENA_ASTROLOGY_TOOLS_START_MARKER,
            ATHENA_ASTROLOGY_TOOLS_END_MARKER,
            block,
        ),
        encoding="utf-8",
    )


def _top_leads(leads: List[Dict[str, object]], limit: int = 15) -> List[Dict[str, object]]:
    seen_jobs = set()
    ranked = sorted(
        leads,
        key=lambda row: (
            1 if str(row.get("contact_email", "")).strip() else 0,
            int(row.get("fit_score", 0) or 0),
        ),
        reverse=True,
    )
    result: List[Dict[str, object]] = []
    for row in ranked:
        if not str(row.get("contact_email", "")).strip():
            continue
        job_id = str(row.get("job_id", "")).strip()
        if not job_id or job_id in seen_jobs:
            continue
        seen_jobs.add(job_id)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def _load_leads(path: Path | None) -> List[Dict[str, object]]:
    if not path or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _latest_matching_file(folder: Path, pattern: str) -> Path | None:
    if not folder.exists():
        return None
    matches = sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _install_job_hunt_skill(workspace_dir: Path, *, repo_root: Path) -> Path | None:
    source = Path(__file__).resolve().parents[1] / "openclaw_skills" / "job-hunt-outreach"
    if not source.exists():
        return None
    target = workspace_dir / "skills" / "job-hunt-outreach"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    _render_refresh_wrappers(target, repo_root=repo_root, workspace_dir=workspace_dir)
    return target


def _install_athena_skill(workspace_dir: Path) -> Path | None:
    source = Path(__file__).resolve().parents[1] / "openclaw_skills" / "athena-context-router"
    if not source.exists():
        return None
    target = workspace_dir / "skills" / "athena-context-router"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _render_athena_readme(*, athena_dir: Path, athena_root: Path) -> str:
    lines = [
        "# Athena Mirror",
        "",
        f"This folder mirrors selected Athena context from `{athena_root}` into the OpenClaw workspace.",
        "",
        "## Start Here",
        "",
        "- `memory_bank/activeContext.md`: active high-signal context.",
        "- `memory_bank/userContext.md`: stable user preferences and recurring context.",
        "- `memory_bank/constraints.md`: important operating constraints.",
        "- `CANONICAL.md`: durable canonical memory view.",
        "- `memories/case_studies/`: reusable examples and validated prior work.",
        "- `memories/session_logs/`: exact chronology and provenance when needed.",
        "- `external/astrology_profiles/`: mirrored detailed astrology dossiers from the Antigravity workspace.",
        "",
        "## Retrieval Order",
        "",
        "1. `CANONICAL.md` when you need a stable source of truth.",
        "2. `memory_bank/` for current operational context.",
        "3. `memories/case_studies/` for examples or prior validated patterns.",
        "4. `external/astrology_profiles/` for person-specific dossier detail.",
        "5. `memories/session_logs/` only when exact chronology or provenance matters.",
        "",
        "Do not treat session logs as primary truth when a memory-bank or canonical file already answers the question.",
    ]
    return "\n".join(lines) + "\n"


def _mirror_tree(source_dir: Path, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if source_dir.exists():
        shutil.copytree(source_dir, target_dir)


def _render_refresh_wrappers(skill_dir: Path, *, repo_root: Path, workspace_dir: Path) -> None:
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    repo_root_text = str(repo_root)
    workspace_text = str(workspace_dir)
    python_script_name = "refresh_job_hunt.py"

    ps1_path = scripts_dir / "refresh_job_hunt.ps1"
    ps1_path.write_text(
        "\n".join(
            [
                "[CmdletBinding()]",
                "param(",
                "    [switch]$RefreshContacts",
                ")",
                "",
                '$ErrorActionPreference = "Stop"',
                "Set-StrictMode -Version Latest",
                "",
                '$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path',
                f'$repoRoot = "{repo_root_text}"',
                '$venvWin = Join-Path $repoRoot ".venv\\Scripts\\python.exe"',
                '$venvPosix = Join-Path $repoRoot ".venv\\bin\\python"',
                '$pythonBin = if ($env:JOB_AUTOMATION_PYTHON) { $env:JOB_AUTOMATION_PYTHON } elseif (Test-Path $venvWin) { $venvWin } elseif (Test-Path $venvPosix) { $venvPosix } else { "python" }',
                '$args = @(',
                f'    (Join-Path $scriptDir "{python_script_name}"),',
                f'    "--repo-root", "{repo_root_text}",',
                f'    "--workspace-dir", "{workspace_text}"',
                ")",
                "if ($RefreshContacts.IsPresent) {",
                '    $args += "--refresh-contacts"',
                "}",
                "& $pythonBin @args",
                "",
            ]
        ),
        encoding="utf-8",
    )

    sh_path = scripts_dir / "refresh_job_hunt.sh"
    sh_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
                f'REPO_ROOT="{repo_root_text}"',
                'if [[ -n "${JOB_AUTOMATION_PYTHON:-}" ]]; then',
                '  PYTHON_BIN="$JOB_AUTOMATION_PYTHON"',
                'elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then',
                '  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"',
                'elif [[ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]]; then',
                '  PYTHON_BIN="$REPO_ROOT/.venv/Scripts/python.exe"',
                'else',
                '  PYTHON_BIN="python3"',
                'fi',
                'ARGS=(',
                f'  "$SCRIPT_DIR/{python_script_name}"',
                f'  "--repo-root" "{repo_root_text}"',
                f'  "--workspace-dir" "{workspace_text}"',
                ")",
                'if [[ "${1:-}" == "--refresh-contacts" ]]; then',
                '  ARGS+=("--refresh-contacts")',
                "fi",
                'exec "$PYTHON_BIN" "${ARGS[@]}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        sh_path.chmod(0o755)
    except OSError:
        pass


def _replace_or_append_block(content: str, start_marker: str, end_marker: str, block: str) -> str:
    if start_marker in content and end_marker in content:
        before, remainder = content.split(start_marker, 1)
        _, after = remainder.split(end_marker, 1)
        return before.rstrip() + "\n\n" + block + after
    return content.rstrip() + "\n\n" + block + "\n"


def _write_json(path: Path, payload: Iterable[Dict[str, object]]) -> None:
    path.write_text(json.dumps(list(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _daily_memory_path(workspace_dir: Path, target_date: date) -> Path:
    return workspace_dir / "memory" / f"{target_date.isoformat()}.md"


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|")


def _is_windows_target(path: Path) -> bool:
    return isinstance(path, PureWindowsPath) or ":" in str(path)


def _command_fence(workspace_dir: Path) -> str:
    return "powershell" if _is_windows_target(workspace_dir) else "bash"


def _refresh_command(*, workspace_dir: Path, repo_root: Path | None, refresh_contacts: bool) -> str:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    repo_root_text = str(repo_root)
    workspace_text = str(workspace_dir)
    if _is_windows_target(workspace_dir):
        command = (
            'powershell -ExecutionPolicy Bypass -File '
            '"skills/job-hunt-outreach/scripts/refresh_job_hunt.ps1"'
        )
        if refresh_contacts:
            command += " -RefreshContacts"
        return command

    command = (
        'python3 "skills/job-hunt-outreach/scripts/refresh_job_hunt.py" '
        f'--repo-root "{repo_root_text}" --workspace-dir "{workspace_text}"'
    )
    if refresh_contacts:
        command += " --refresh-contacts"
    return command


def _ensure_refresh_status_files(status_dir: Path) -> tuple[Path, Path]:
    md_path = status_dir / "latest_refresh_status.md"
    json_path = status_dir / "latest_refresh_status.json"

    if not json_path.exists():
        json_path.write_text(
            json.dumps(
                {
                    "state": "idle",
                    "stage": "not_started",
                    "started_at": "",
                    "updated_at": "",
                    "refresh_contacts": False,
                    "apify_refresh_requested": False,
                    "summary_path": "",
                    "error": "",
                    "events": ["No job-hunt refresh has been recorded in this workspace yet."],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if not md_path.exists():
        md_path.write_text(
            "\n".join(
                [
                    "# Job Hunt Refresh Status",
                    "",
                    "- State: **idle**",
                    "- Stage: **not_started**",
                    "",
                    "No job-hunt refresh has been recorded in this workspace yet.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    return md_path, json_path
