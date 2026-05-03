from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence
from urllib.parse import quote

from .http_client import HttpClientError, request_json

DEFAULT_SPEC_PATH = Path(__file__).resolve().parents[1] / "docs" / "apify_targeted_ravi_03042026.json"
DEFAULT_ACTOR_IDS = {
    "linkedin": "hKByXkMQaC5Qt9UMN",
    "indeed": "hMvNSpz3JnHgl5jkh",
}
FINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


@dataclass(frozen=True)
class ApifyRefreshResult:
    provider: str
    actor_id: str | None
    task_ids: List[str]
    successful_dataset_ids: List[str]
    used_existing_dataset_ids: bool
    updated_env: bool
    summary_path: Path
    runs: List[Dict[str, object]]
    generated_at: datetime


def refresh_apify_datasets(
    *,
    api_token: str,
    env_path: Path,
    summary_dir: Path,
    existing_dataset_ids: Sequence[str] | None = None,
    provider: str = "linkedin",
    spec_path: Path | None = None,
    task_ids: Sequence[str] | None = None,
    wait_seconds: int = 300,
    generated_at: datetime | None = None,
) -> ApifyRefreshResult:
    token = api_token.strip()
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is not configured.")

    generated_at = generated_at or datetime.now(UTC)
    provider = provider.strip().lower() or "linkedin"
    task_ids = [item.strip() for item in (task_ids or []) if str(item).strip()]
    existing_dataset_ids = [item.strip() for item in (existing_dataset_ids or []) if str(item).strip()]
    summary_dir.mkdir(parents=True, exist_ok=True)

    runs: List[Dict[str, object]] = []
    actor_id: str | None = None

    if task_ids:
        for task_id in task_ids:
            run = _call_task(
                token=token,
                task_id=task_id,
                wait_seconds=wait_seconds,
            )
            runs.append(
                {
                    "task_id": task_id,
                    "dataset_id": str(run.get("defaultDatasetId", "")).strip(),
                    "status": str(run.get("status", "")).upper(),
                    "run_id": str(run.get("id", "")).strip(),
                }
            )
    else:
        actor_id = DEFAULT_ACTOR_IDS.get(provider)
        if not actor_id:
            raise RuntimeError(f"Unsupported Apify provider: {provider}")
        spec = _load_targeted_spec(spec_path or DEFAULT_SPEC_PATH)
        queries = [str(item).strip() for item in spec.get("queries", []) if str(item).strip()]
        locations = [str(item).strip() for item in spec.get("locations", []) if str(item).strip()]
        max_results = int(spec.get("max_results_per_run", 8) or 8)
        if not queries or not locations:
            raise RuntimeError("Apify spec must contain non-empty queries and locations.")
        if provider == "linkedin":
            run = _call_linkedin_actor(
                token=token,
                actor_id=actor_id,
                queries=queries,
                locations=locations,
                max_results_per_search=max_results,
                wait_seconds=wait_seconds,
            )
            runs.append(
                {
                    "query": ", ".join(queries),
                    "location": ", ".join(locations),
                    "dataset_id": str(run.get("defaultDatasetId", "")).strip(),
                    "status": str(run.get("status", "")).upper(),
                    "run_id": str(run.get("id", "")).strip(),
                }
            )
        else:
            for query in queries:
                for location in locations:
                    run = _call_actor(
                        token=token,
                        actor_id=actor_id,
                        provider=provider,
                        query=query,
                        location=location,
                        max_results=max_results,
                        wait_seconds=wait_seconds,
                    )
                    runs.append(
                        {
                            "query": query,
                            "location": location,
                            "dataset_id": str(run.get("defaultDatasetId", "")).strip(),
                            "status": str(run.get("status", "")).upper(),
                            "run_id": str(run.get("id", "")).strip(),
                        }
                    )

    successful_dataset_ids = _dedupe_preserve_order(
        [
            str(item.get("dataset_id", "")).strip()
            for item in runs
            if _is_usable_dataset_status(str(item.get("status", "")).upper())
            and str(item.get("dataset_id", "")).strip()
        ]
    )
    used_existing_dataset_ids = False
    updated_env = False
    dataset_ids_to_write = successful_dataset_ids
    if not dataset_ids_to_write and existing_dataset_ids:
        dataset_ids_to_write = list(existing_dataset_ids)
        used_existing_dataset_ids = True

    if dataset_ids_to_write:
        _update_env_dataset_ids(env_path, dataset_ids_to_write)
        updated_env = True

    summary_path = summary_dir / f"apify_refresh_{generated_at.strftime('%Y%m%d_%H%M%S')}.json"
    summary_path.write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "provider": provider,
                "actor_id": actor_id,
                "task_ids": task_ids,
                "successful_dataset_ids": successful_dataset_ids,
                "used_existing_dataset_ids": used_existing_dataset_ids,
                "updated_env": updated_env,
                "runs": runs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return ApifyRefreshResult(
        provider=provider,
        actor_id=actor_id,
        task_ids=list(task_ids),
        successful_dataset_ids=successful_dataset_ids,
        used_existing_dataset_ids=used_existing_dataset_ids,
        updated_env=updated_env,
        summary_path=summary_path,
        runs=runs,
        generated_at=generated_at,
    )


def _load_targeted_spec(path: Path) -> Dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Apify spec file not found: {resolved}")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Apify spec must be a JSON object.")
    return payload


def _call_actor(
    *,
    token: str,
    actor_id: str,
    provider: str,
    query: str,
    location: str,
    max_results: int,
    wait_seconds: int,
) -> Dict[str, Any]:
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

    response = request_json("POST", url, payload=payload, timeout_seconds=max(wait_seconds, 60))
    data = _extract_data_dict(response.body)
    status = str(data.get("status", "")).upper()
    if status not in FINAL_RUN_STATUSES and data.get("id"):
        data = _wait_for_run(token=token, run_id=str(data["id"]), wait_seconds=wait_seconds)
    return data


def _call_linkedin_actor(
    *,
    token: str,
    actor_id: str,
    queries: Sequence[str],
    locations: Sequence[str],
    max_results_per_search: int,
    wait_seconds: int,
) -> Dict[str, Any]:
    urls = [
        (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={quote(query)}&location={quote(location)}"
        )
        for query in queries
        for location in locations
    ]
    url = (
        f"https://api.apify.com/v2/acts/{quote(actor_id, safe='')}/runs"
        f"?token={token}&waitForFinish=30"
    )
    payload = {
        "urls": urls,
        "maxResults": max(1, max_results_per_search) * len(urls),
        "proxy": {"useApifyProxy": True},
    }
    response = request_json("POST", url, payload=payload, timeout_seconds=max(wait_seconds, 60))
    data = _extract_data_dict(response.body)
    status = str(data.get("status", "")).upper()
    if status not in FINAL_RUN_STATUSES and data.get("id"):
        data = _wait_for_run(token=token, run_id=str(data["id"]), wait_seconds=wait_seconds)
    return data


def _call_task(*, token: str, task_id: str, wait_seconds: int) -> Dict[str, Any]:
    url = (
        f"https://api.apify.com/v2/actor-tasks/{quote(task_id, safe='')}/runs"
        f"?token={token}&waitForFinish=30"
    )
    response = request_json("POST", url, timeout_seconds=max(wait_seconds, 60))
    data = _extract_data_dict(response.body)
    status = str(data.get("status", "")).upper()
    if status not in FINAL_RUN_STATUSES and data.get("id"):
        data = _wait_for_run(token=token, run_id=str(data["id"]), wait_seconds=wait_seconds)
    return data


def _wait_for_run(*, token: str, run_id: str, wait_seconds: int) -> Dict[str, Any]:
    url = (
        f"https://api.apify.com/v2/actor-runs/{quote(run_id, safe='')}"
        f"?token={token}&waitForFinish={max(wait_seconds, 30)}"
    )
    response = request_json("GET", url, timeout_seconds=max(wait_seconds + 30, 60))
    return _extract_data_dict(response.body)


def _extract_data_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Apify response shape.")
    return data


def _is_usable_dataset_status(status: str) -> bool:
    return status not in {"", "FAILED", "ABORTED", "TIMED-OUT"}


def _update_env_dataset_ids(env_path: Path, dataset_ids: Sequence[str]) -> None:
    resolved = env_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f".env file not found: {resolved}")
    replacement = f"APIFY_DATASET_IDS={','.join(dataset_ids)}"
    lines = resolved.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines: List[str] = []
    for line in lines:
        if line.startswith("APIFY_DATASET_IDS="):
            new_lines.append(replacement)
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(replacement)
    resolved.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
