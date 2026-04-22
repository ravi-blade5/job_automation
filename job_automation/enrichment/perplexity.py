from __future__ import annotations

import json
import re
from typing import Dict

from ..http_client import HttpClientError, request_json
from ..models import CompanyContextRecord, utc_now_iso


class CompanyEnricher:
    def enrich(self, company: str, job_description: str) -> CompanyContextRecord:
        return CompanyContextRecord(
            company=company,
            funding_signal="unknown",
            business_direction="unknown",
            ai_maturity="unknown",
            enriched_at=utc_now_iso(),
        )


class PerplexityCompanyEnricher(CompanyEnricher):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key.strip()
        self.model = model.strip() or "sonar"

    def enrich(self, company: str, job_description: str) -> CompanyContextRecord:
        if not self.api_key:
            return super().enrich(company, job_description)

        prompt = (
            "Return strict JSON with keys funding_signal, business_direction, ai_maturity. "
            "Provide concise values (max 20 words each) for this company hiring context.\n"
            f"Company: {company}\nJob context: {job_description[:1200]}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a concise analyst that returns valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = request_json(
                method="POST",
                url="https://api.perplexity.ai/chat/completions",
                headers=headers,
                payload=payload,
            )
            content = _extract_content(response.body)
            parsed = _safe_json(content)
            return CompanyContextRecord(
                company=company,
                funding_signal=str(parsed.get("funding_signal", "unknown")).strip(),
                business_direction=str(parsed.get("business_direction", "unknown")).strip(),
                ai_maturity=str(parsed.get("ai_maturity", "unknown")).strip(),
                enriched_at=utc_now_iso(),
            )
        except (HttpClientError, ValueError, KeyError, TypeError):
            return super().enrich(company, job_description)


def _extract_content(body: Dict[str, object]) -> str:
    choices = body.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return ""
    return str(message.get("content", "")).strip()


def _safe_json(text: str) -> Dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).strip()
        cleaned = cleaned.rstrip("`").strip()
    if not cleaned:
        return {}
    return json.loads(cleaned)

