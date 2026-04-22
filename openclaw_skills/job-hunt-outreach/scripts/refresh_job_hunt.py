from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=str(cwd), check=True)


def _python_bin_for_repo(repo_root: Path) -> str:
    candidate_paths = [
        repo_root / ".venv" / "Scripts" / "python.exe",
        repo_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return str(candidate)
    return os.environ.get("JOB_AUTOMATION_PYTHON", sys.executable or "python")


def _status_paths(workspace_dir: Path) -> tuple[Path, Path]:
    status_dir = workspace_dir / "job_hunt" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    return status_dir / "latest_refresh_status.json", status_dir / "latest_refresh_status.md"


def _write_status(
    *,
    workspace_dir: Path,
    state: str,
    stage: str,
    started_at: str,
    refresh_contacts: bool,
    apify_refresh_requested: bool,
    events: list[str],
    summary_path: Path | None = None,
    error: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    json_path, md_path = _status_paths(workspace_dir)
    payload = {
        "state": state,
        "stage": stage,
        "started_at": started_at,
        "updated_at": now,
        "refresh_contacts": refresh_contacts,
        "apify_refresh_requested": apify_refresh_requested,
        "summary_path": str(summary_path) if summary_path else "",
        "error": error or "",
        "events": events,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Job Hunt Refresh Status",
        "",
        f"- State: **{state}**",
        f"- Stage: **{stage}**",
        f"- Started at: `{started_at}`",
        f"- Updated at: `{now}`",
        f"- Fresh contact discovery: **{'yes' if refresh_contacts else 'no'}**",
        f"- Fresh Apify refresh requested: **{'yes' if apify_refresh_requested else 'no'}**",
    ]
    if summary_path:
        lines.append(f"- Summary file: `{summary_path}`")
    if error:
        lines.extend(["", "## Error", "", f"```text\n{error}\n```"])
    if events:
        lines.extend(["", "## Recent Events", ""])
        lines.extend(f"- {item}" for item in events[-12:])

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh job-hunt mirror inside an OpenClaw workspace.")
    parser.add_argument("--repo-root", required=True, help="ADB_HCL repo root that contains job_automation.")
    parser.add_argument(
        "--workspace-dir",
        required=True,
        help="Target OpenClaw workspace directory to mirror into.",
    )
    parser.add_argument(
        "--refresh-contacts",
        action="store_true",
        help="Force a fresh Firecrawl contact-discovery pass.",
    )
    parser.add_argument(
        "--skip-apify-refresh",
        action="store_true",
        help="Skip launching fresh Apify runs and only ingest from the currently configured dataset IDs.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    workspace_dir = Path(args.workspace_dir).expanduser().resolve()

    if not (repo_root / "job_automation").exists():
        raise SystemExit(f"job_automation repo not found under: {repo_root}")

    python_bin = _python_bin_for_repo(repo_root)
    started_at = datetime.now(UTC).isoformat()
    events = [f"Refresh wrapper started with interpreter `{python_bin}`."]
    _write_status(
        workspace_dir=workspace_dir,
        state="running",
        stage="starting",
        started_at=started_at,
        refresh_contacts=bool(args.refresh_contacts),
        apify_refresh_requested=not bool(args.skip_apify_refresh),
        events=events,
    )

    try:
        if not args.skip_apify_refresh:
            print("[job-hunt-outreach] Launching fresh Apify runs...")
            events.append("Launching fresh Apify runs and updating dataset IDs.")
            _write_status(
                workspace_dir=workspace_dir,
                state="running",
                stage="refreshing_apify",
                started_at=started_at,
                refresh_contacts=bool(args.refresh_contacts),
                apify_refresh_requested=True,
                events=events,
            )
            _run(
                [
                    python_bin,
                    "-m",
                    "job_automation.cli",
                    "refresh-apify-datasets",
                    "--repo-root",
                    str(repo_root),
                ],
                cwd=repo_root,
            )
            events.append("Fresh Apify runs completed.")

        print("[job-hunt-outreach] Running daily ingest...")
        events.append("Running daily ingest against the current dataset IDs.")
        _write_status(
            workspace_dir=workspace_dir,
            state="running",
            stage="running_daily_ingest",
            started_at=started_at,
            refresh_contacts=bool(args.refresh_contacts),
            apify_refresh_requested=not bool(args.skip_apify_refresh),
            events=events,
        )
        _run([python_bin, "-m", "job_automation.cli", "run-daily", "--tracker", "json"], cwd=repo_root)
        events.append("Daily ingest completed.")

        print("[job-hunt-outreach] Building outreach leads...")
        events.append(
            "Building outreach leads with fresh contact discovery."
            if args.refresh_contacts
            else "Building outreach leads with normal contact discovery."
        )
        _write_status(
            workspace_dir=workspace_dir,
            state="running",
            stage="building_outreach_leads",
            started_at=started_at,
            refresh_contacts=bool(args.refresh_contacts),
            apify_refresh_requested=not bool(args.skip_apify_refresh),
            events=events,
        )
        build_command = [python_bin, "-m", "job_automation.cli", "build-outreach-leads", "--tracker", "json"]
        if args.refresh_contacts:
            build_command.append("--refresh-contacts")
        _run(build_command, cwd=repo_root)
        events.append("Outreach leads export completed.")

        print("[job-hunt-outreach] Syncing into OpenClaw workspace...")
        events.append("Syncing refreshed job-hunt data into the OpenClaw workspace mirror.")
        _write_status(
            workspace_dir=workspace_dir,
            state="running",
            stage="syncing_workspace",
            started_at=started_at,
            refresh_contacts=bool(args.refresh_contacts),
            apify_refresh_requested=not bool(args.skip_apify_refresh),
            events=events,
        )
        _run(
            [
                python_bin,
                "-m",
                "job_automation.cli",
                "sync-openclaw-workspace",
                "--tracker",
                "json",
                "--workspace-dir",
                str(workspace_dir),
                "--repo-root",
                str(repo_root),
            ],
            cwd=repo_root,
        )
        summary_path = workspace_dir / "job_hunt" / "summary" / "latest_outreach_summary.md"
        events.append(f"Refresh complete. Updated summary at `{summary_path}`.")
        _write_status(
            workspace_dir=workspace_dir,
            state="succeeded",
            stage="complete",
            started_at=started_at,
            refresh_contacts=bool(args.refresh_contacts),
            apify_refresh_requested=not bool(args.skip_apify_refresh),
            events=events,
            summary_path=summary_path,
        )

        print(f"[job-hunt-outreach] Complete. Start with {summary_path}")
    except Exception as exc:
        error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        events.append(f"Refresh failed at stage `{events[-1] if events else 'unknown'}`.")
        _write_status(
            workspace_dir=workspace_dir,
            state="failed",
            stage="failed",
            started_at=started_at,
            refresh_contacts=bool(args.refresh_contacts),
            apify_refresh_requested=not bool(args.skip_apify_refresh),
            events=events,
            error=error_text,
        )
        raise


if __name__ == "__main__":
    main()
