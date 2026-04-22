from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class HttpResponse:
    status_code: int
    body: Dict[str, Any]
    raw: str


class HttpClientError(RuntimeError):
    pass


def request_json(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 60,
) -> HttpResponse:
    body_bytes = None
    request_headers: Dict[str, str] = {}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    req = Request(
        url=url,
        data=body_bytes,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = _safe_json(raw)
            return HttpResponse(status_code=response.status, body=parsed, raw=raw)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HttpClientError(
            f"HTTP {exc.code} for {method.upper()} {url}: {raw[:400]}"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise HttpClientError(
            f"Timeout for {method.upper()} {url}: {exc}"
        ) from exc
    except URLError as exc:
        raise HttpClientError(f"Network error for {method.upper()} {url}: {exc}") from exc


def _safe_json(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"items": parsed}
    except json.JSONDecodeError:
        return {"raw": raw}
