from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List

from ..http_client import HttpClientError, request_json
from ..models import JobIngestRecord


@dataclass
class ParsedJD:
    normalized_title: str
    seniority: str
    required_skills: List[str]
    location_hint: str
    remote_hint: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "normalized_title": self.normalized_title,
            "seniority": self.seniority,
            "required_skills": list(self.required_skills),
            "location_hint": self.location_hint,
            "remote_hint": self.remote_hint,
        }


class RuleBasedJDParser:
    def parse(self, job: JobIngestRecord) -> ParsedJD:
        corpus = f"{job.title_raw} {job.description_text}".lower()
        skills = _extract_skills(corpus)
        seniority = "high" if any(x in corpus for x in ("lead", "senior", "principal", "head")) else "medium"
        if any(x in corpus for x in ("intern", "junior", "associate")):
            seniority = "low"
        remote_hint = "remote" if "remote" in corpus else (job.remote_type or "unknown")
        return ParsedJD(
            normalized_title=_normalize_title(job.title_raw),
            seniority=seniority,
            required_skills=skills,
            location_hint=job.location or "",
            remote_hint=remote_hint,
        )


class GeminiJDParser:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key.strip()
        self.model = model.strip() or "gemini-2.5-pro"
        self.fallback = RuleBasedJDParser()

    def parse(self, job: JobIngestRecord) -> ParsedJD:
        if not self.api_key:
            return self.fallback.parse(job)

        prompt = (
            "Extract normalized role information from this job description and return "
            "strict JSON with keys: normalized_title, seniority(high|medium|low), "
            "required_skills(array), location_hint, remote_hint.\n\n"
            f"Title: {job.title_raw}\nLocation: {job.location}\n"
            f"Description:\n{job.description_text[:8000]}"
        )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = request_json(method="POST", url=url, payload=payload)
            text = _extract_text(response.body)
            parsed = _safe_json(text)
            return ParsedJD(
                normalized_title=str(parsed.get("normalized_title", _normalize_title(job.title_raw))),
                seniority=str(parsed.get("seniority", "medium")).lower(),
                required_skills=[
                    str(item).strip()
                    for item in (parsed.get("required_skills", []) or [])
                    if str(item).strip()
                ],
                location_hint=str(parsed.get("location_hint", job.location or "")),
                remote_hint=str(parsed.get("remote_hint", job.remote_type or "unknown")),
            )
        except (HttpClientError, ValueError, KeyError, TypeError):
            return self.fallback.parse(job)


def _extract_text(body: Dict[str, object]) -> str:
    candidates = body.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return ""
    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )
    if not isinstance(parts, list):
        return ""
    for part in parts:
        if isinstance(part, dict) and str(part.get("text", "")).strip():
            return str(part["text"])
    return ""


def _safe_json(text: str) -> Dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).strip()
        cleaned = cleaned.rstrip("`").strip()
    if not cleaned:
        return {}
    return json.loads(cleaned)


def _normalize_title(raw_title: str) -> str:
    text = raw_title.lower()
    if "product manager" in text:
        return "Product Manager"
    if "solution" in text and "lead" in text:
        return "Solutions Lead"
    if "genai" in text or "ai" in text:
        return "AI Product / Solutions Role"
    return raw_title.strip()


def _extract_skills(corpus: str) -> List[str]:
    candidates = [
        "genai",
        "llm",
        "rag",
        "openai",
        "vertex ai",
        "python",
        "power bi",
        "agile",
        "roadmap",
        "stakeholder management",
        "jira",
        "prompt engineering",
        "go-to-market",
    ]
    return [item for item in candidates if item in corpus]

