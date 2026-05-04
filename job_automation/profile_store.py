from __future__ import annotations

import base64
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List
from xml.etree import ElementTree

from .resume_tailor import KEYWORD_CATALOG


PROFILE_RELATIVE_PATH = Path("resume_profile") / "current_profile.json"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

STOPWORDS = {
    "about",
    "across",
    "after",
    "also",
    "and",
    "are",
    "based",
    "been",
    "being",
    "business",
    "can",
    "candidate",
    "customer",
    "delivery",
    "for",
    "from",
    "has",
    "have",
    "into",
    "management",
    "manager",
    "more",
    "not",
    "product",
    "project",
    "resume",
    "role",
    "team",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "with",
    "work",
    "worked",
    "working",
}


@dataclass(frozen=True)
class ResumeProfile:
    filename: str
    text: str
    keywords: List[str]
    updated_at: str
    gcs_uri: str = ""

    @property
    def is_active(self) -> bool:
        return bool(self.text.strip() and self.keywords)

    def to_dict(self) -> Dict[str, object]:
        return {
            "filename": self.filename,
            "text": self.text,
            "keywords": list(self.keywords),
            "keyword_count": len(self.keywords),
            "updated_at": self.updated_at,
            "gcs_uri": self.gcs_uri,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "ResumeProfile":
        keywords_raw = raw.get("keywords", []) or []
        if isinstance(keywords_raw, str):
            try:
                parsed = json.loads(keywords_raw)
                keywords_raw = parsed if isinstance(parsed, list) else [keywords_raw]
            except json.JSONDecodeError:
                keywords_raw = [keywords_raw]
        return cls(
            filename=str(raw.get("filename", "")).strip(),
            text=str(raw.get("text", "")).strip(),
            keywords=[str(item).strip() for item in keywords_raw if str(item).strip()],
            updated_at=str(raw.get("updated_at", "")).strip(),
            gcs_uri=str(raw.get("gcs_uri", "")).strip(),
        )


class ResumeProfileStore:
    def __init__(
        self,
        *,
        data_dir: Path,
        gcs_bucket: str = "",
        gcs_prefix: str = "artifacts",
        gcp_project_id: str = "",
    ) -> None:
        self.data_dir = data_dir
        self.profile_path = data_dir / PROFILE_RELATIVE_PATH
        self.gcs_bucket = gcs_bucket.strip().removeprefix("gs://").rstrip("/")
        self.gcs_prefix = gcs_prefix.strip().strip("/") or "artifacts"
        self.gcp_project_id = gcp_project_id.strip()

    def save(
        self,
        *,
        filename: str,
        content_base64: str = "",
        text: str = "",
    ) -> ResumeProfile:
        filename = _safe_filename(filename) or "resume_profile.txt"
        raw_bytes = _decode_upload(content_base64)
        extracted_text = _extract_resume_text(filename, raw_bytes, text)
        if len(extracted_text) < 80:
            raise ValueError("Could not extract enough resume text. Upload a text-readable PDF, DOCX, TXT, or paste text.")
        keywords = derive_resume_keywords(extracted_text)
        if not keywords:
            raise ValueError("No usable resume keywords were extracted.")

        profile = ResumeProfile(
            filename=filename,
            text=extracted_text,
            keywords=keywords,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        gcs_uri = self._upload_profile_json()
        if gcs_uri:
            profile = ResumeProfile(
                filename=profile.filename,
                text=profile.text,
                keywords=profile.keywords,
                updated_at=profile.updated_at,
                gcs_uri=gcs_uri,
            )
            self.profile_path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        return profile

    def load(self) -> ResumeProfile | None:
        if self.profile_path.is_file():
            return ResumeProfile.from_dict(json.loads(self.profile_path.read_text(encoding="utf-8")))
        if self.gcs_bucket:
            self._download_profile_json()
            if self.profile_path.is_file():
                return ResumeProfile.from_dict(json.loads(self.profile_path.read_text(encoding="utf-8")))
        return None

    def summary(self) -> Dict[str, object]:
        profile = self.load()
        if not profile:
            return {
                "is_active": False,
                "filename": "",
                "keyword_count": 0,
                "keywords": [],
                "updated_at": "",
                "gcs_uri": "",
            }
        return {
            "is_active": profile.is_active,
            "filename": profile.filename,
            "keyword_count": len(profile.keywords),
            "keywords": profile.keywords[:24],
            "updated_at": profile.updated_at,
            "gcs_uri": profile.gcs_uri,
        }

    def _blob_name(self) -> str:
        return f"{self.gcs_prefix}/resume_profile/current_profile.json"

    def _upload_profile_json(self) -> str:
        if not self.gcs_bucket or not self.profile_path.exists():
            return ""
        try:
            from google.cloud import storage  # type: ignore
        except Exception:
            return ""
        client = storage.Client(project=self.gcp_project_id or None)
        blob_name = self._blob_name()
        blob = client.bucket(self.gcs_bucket).blob(blob_name)
        blob.upload_from_filename(str(self.profile_path), content_type="application/json")
        return f"gs://{self.gcs_bucket}/{blob_name}"

    def _download_profile_json(self) -> None:
        try:
            from google.cloud import storage  # type: ignore
        except Exception:
            return
        client = storage.Client(project=self.gcp_project_id or None)
        blob = client.bucket(self.gcs_bucket).blob(self._blob_name())
        if not blob.exists(client):
            return
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(self.profile_path))


def derive_resume_keywords(text: str, limit: int = 80) -> List[str]:
    normalized = text.lower()
    keywords: List[str] = []
    for label, aliases in KEYWORD_CATALOG:
        if any(alias in normalized for alias in aliases):
            keywords.append(label.lower())
            keywords.extend(alias for alias in aliases if alias in normalized)

    tokens = [
        token
        for token in re.findall(r"[a-z][a-z0-9+#.-]{2,}", normalized)
        if token not in STOPWORDS and not token.isdigit()
    ]
    common = [token for token, _count in Counter(tokens).most_common(120)]
    return _dedupe_keywords([*keywords, *common], limit=limit)


def _decode_upload(content_base64: str) -> bytes:
    if not content_base64:
        return b""
    try:
        payload = content_base64.split(",", 1)[-1]
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("Uploaded resume content must be base64 encoded.") from exc
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Resume upload is too large. Keep it under 8 MB.")
    return raw


def _extract_resume_text(filename: str, raw_bytes: bytes, pasted_text: str) -> str:
    if pasted_text.strip() and not raw_bytes:
        return _normalize_text(pasted_text)
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        return _normalize_text(raw_bytes.decode("utf-8", errors="ignore"))
    if suffix == ".pdf":
        return _extract_pdf_text(raw_bytes)
    if suffix == ".docx":
        return _extract_docx_text(raw_bytes)
    if pasted_text.strip():
        return _normalize_text(pasted_text)
    raise ValueError("Unsupported resume format. Use PDF, DOCX, TXT, or MD.")


def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise ValueError("PDF extraction is unavailable because pypdf is not installed.") from exc
    reader = PdfReader(BytesIO(raw_bytes))
    text_parts = [(page.extract_text() or "") for page in reader.pages]
    return _normalize_text("\n".join(text_parts))


def _extract_docx_text(raw_bytes: bytes) -> str:
    paragraphs: List[str] = []
    with zipfile.ZipFile(BytesIO(raw_bytes)) as docx:
        xml = docx.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        if texts:
            paragraphs.append("".join(texts))
    return _normalize_text("\n".join(paragraphs))


def _dedupe_keywords(values: Iterable[str], *, limit: int) -> List[str]:
    seen = set()
    result = []
    for value in values:
        item = re.sub(r"\s+", " ", str(value).strip().lower())
        if len(item) < 3 or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _safe_filename(filename: str) -> str:
    name = Path(str(filename or "")).name
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", name).strip()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
