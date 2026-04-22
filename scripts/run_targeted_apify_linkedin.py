from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from job_automation.job_automation.config import load_settings  # noqa: E402


DEFAULT_SPEC_PATH = (
    WORKSPACE_ROOT / "job_automation" / "docs" / "apify_targeted_ravi_03042026.json"
)
ACTOR_IDS = {
    "linkedin": "hKByXkMQaC5Qt9UMN",
    "indeed": "hMvNSpz3JnHgl5jkh",
}
FINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run targeted Apify job searches and optionally update APIFY_DATASET_IDS."
    )
    parser.add_argument(
        "--spec",
        default=str(DEFAULT_SPEC_PATH),
        help="JSON file containing queries, locations, and max_results_per_run.",
    )
    parser.add_argument(
        "--update-env",
        action="store_true",
        help="Replace APIFY_DATASET_IDS in the workspace .env with the successful run dataset IDs.",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(ACTOR_IDS),
        default="linkedin",
        help="Apify actor provider to run.",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.apify_api_token:
        raise RuntimeError("APIFY_API_TOKEN is not configured.")

    spec_path = Path(args.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    queries = [str(item).strip() for item in spec.get("queries", []) if str(item).strip()]
    locations = [str(item).strip() for item in spec.get("locations", []) if str(item).strip()]
    max_results = int(spec.get("max_results_per_run", 8) or 8)
    if not queries or not locations:
        raise RuntimeError("Spec must contain non-empty queries and locations arrays.")

    runs = []
    for query in queries:
        for location in locations:
            run = _call_actor(
                token=settings.apify_api_token,
                provider=args.provider,
                query=query,
                location=location,
                max_results=max_results,
            )
            runs.append(
                {
                    "query": query,
                    "location": location,
                    "dataset_id": run["defaultDatasetId"],
                    "status": run["status"],
                    "run_id": run["id"],
                }
            )

    successful_dataset_ids = [
        item["dataset_id"]
        for item in runs
        if item.get("status", "").upper() == "SUCCEEDED" and item.get("dataset_id")
    ]

    if args.update_env:
        _update_env_dataset_ids(WORKSPACE_ROOT / ".env", successful_dataset_ids)

    backup_dir = WORKSPACE_ROOT / "job_automation" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    summary_path = backup_dir / (
        f"targeted_apify_runs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    summary_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "provider": args.provider,
                "actor_id": ACTOR_IDS[args.provider],
                "spec_path": str(spec_path),
                "successful_dataset_ids": successful_dataset_ids,
                "runs": runs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "successful_dataset_ids": successful_dataset_ids,
                "summary_path": str(summary_path),
                "run_count": len(runs),
            },
            indent=2,
        )
    )


def _call_actor(
    token: str,
    provider: str,
    query: str,
    location: str,
    max_results: int,
) -> dict:
    actor_id = ACTOR_IDS[provider]
    url = (
        f"https://api.apify.com/v2/acts/{quote(actor_id, safe='')}/runs"
        f"?token={token}&waitForFinish=30"
    )
    if provider == "linkedin":
        search_url = (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={quote(query)}&location={quote(location)}"
        )
        payload = {
            "urls": [search_url],
            "maxResults": max_results,
            "proxy": {"useApifyProxy": True},
        }
    else:
        payload = {
            "position": query,
            "country": "IN",
            "location": location,
            "maxItems": max_results,
            "parseCompanyDetails": False,
        }
    response = _request_json("POST", url, payload)
    data = response.get("data", response)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Apify response shape.")
    status = str(data.get("status", "")).upper()
    if status not in FINAL_RUN_STATUSES and data.get("id"):
        data = _wait_for_run(token, str(data["id"]))
    return data


def _wait_for_run(token: str, run_id: str, timeout_seconds: int = 300) -> dict:
    url = (
        f"https://api.apify.com/v2/actor-runs/{quote(run_id, safe='')}"
        f"?token={token}&waitForFinish={timeout_seconds}"
    )
    response = _request_json("GET", url)
    data = response.get("data", response)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Apify run poll response shape.")
    return data


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    body = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    request = Request(url=url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    return json.loads(raw)


def _update_env_dataset_ids(env_path: Path, dataset_ids: list[str]) -> None:
    if not env_path.exists():
        raise RuntimeError(f".env file not found: {env_path}")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    replacement = f"APIFY_DATASET_IDS={','.join(dataset_ids)}"
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("APIFY_DATASET_IDS="):
            new_lines.append(replacement)
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(replacement)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
