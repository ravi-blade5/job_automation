from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Dict

from .models import ApplicationRecord, FitScoreRecord, JobIngestRecord


class ApplicationArtifactGenerator:
    def __init__(
        self,
        artifacts_root: Path,
        resume_dir: Path,
        gcs_bucket: str = "",
        gcs_prefix: str = "artifacts",
        gcp_project_id: str = "",
    ):
        self.artifacts_root = artifacts_root
        self.resume_dir = resume_dir
        self.gcs_bucket = gcs_bucket.strip().removeprefix("gs://").rstrip("/")
        self.gcs_prefix = gcs_prefix.strip().strip("/") or "artifacts"
        self.gcp_project_id = gcp_project_id.strip()
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        application: ApplicationRecord,
        job: JobIngestRecord,
        fit_score: FitScoreRecord,
    ) -> Dict[str, str]:
        app_dir = self.artifacts_root / application.application_id
        app_dir.mkdir(parents=True, exist_ok=True)

        summary_path = app_dir / "resume_summary.txt"
        cover_path = app_dir / "cover_note_120_words.txt"
        referral_path = app_dir / "referral_message_3_lines.txt"

        summary_text = self._render_summary(job, fit_score, application.resume_variant)
        cover_text = self._render_cover_note(job, application.resume_variant)
        referral_text = self._render_referral(job)

        summary_path.write_text(summary_text, encoding="utf-8")
        cover_path.write_text(cover_text, encoding="utf-8")
        referral_path.write_text(referral_text, encoding="utf-8")

        resume_variant_path = (
            self.resume_dir / "resume_variant_a_ai_product_manager.md"
            if application.resume_variant == "A"
            else self.resume_dir / "resume_variant_b_genai_product_solutions_lead.md"
        )
        self._mirror_to_gcs(
            application.application_id,
            {
                "resume_variant": resume_variant_path,
                "resume_summary": summary_path,
                "cover_note": cover_path,
                "referral_message": referral_path,
            },
        )

        return {
            "resume_variant": str(resume_variant_path.resolve()),
            "resume_summary": str(summary_path.resolve()),
            "cover_note": str(cover_path.resolve()),
            "referral_message": str(referral_path.resolve()),
        }

    def _mirror_to_gcs(self, application_id: str, files: Dict[str, Path]) -> None:
        if not self.gcs_bucket:
            return
        try:
            from google.cloud import storage  # type: ignore
        except Exception:
            return

        client = storage.Client(project=self.gcp_project_id or None)
        bucket = client.bucket(self.gcs_bucket)
        for document_type, path in files.items():
            if not path.exists():
                continue
            blob_name = f"{self.gcs_prefix}/{application_id}/{document_type}{path.suffix}"
            blob = bucket.blob(blob_name)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            blob.upload_from_filename(str(path), content_type=content_type)

    def _render_summary(
        self,
        job: JobIngestRecord,
        fit_score: FitScoreRecord,
        resume_variant: str,
    ) -> str:
        track_label = "AI Product Manager" if resume_variant == "A" else "GenAI Product/Solutions Lead"
        return (
            f"Target Role: {track_label}\n"
            f"Job: {job.title_raw} at {job.company}\n"
            f"Fit Score: {fit_score.fit_score} ({fit_score.decision.value})\n\n"
            "Positioning Highlights:\n"
            "- Led GenAI roadmap and analyst-facing narrative ownership in enterprise contexts.\n"
            "- Qualified and operationalized 25+ strategic partners into delivery-ready channels.\n"
            "- Demonstrated rapid time-to-value with cross-functional launches and workflow automation.\n"
            "- Strong blend of product strategy, stakeholder alignment, and AI implementation governance.\n"
        )

    def _render_cover_note(self, job: JobIngestRecord, resume_variant: str) -> str:
        variant_line = (
            "I bring outcome-led AI product strategy and GTM execution across enterprise workflows."
            if resume_variant == "A"
            else "I bring hands-on GenAI solution leadership across architecture, governance, and deployment."
        )
        draft = (
            f"I am excited to apply for the {job.title_raw} role at {job.company}. "
            f"{variant_line} "
            "In recent roles, I have driven roadmap definition, stakeholder workshops, and measurable AI outcomes "
            "across domains including telecom, media, and financial services. "
            "I combine business prioritization with practical execution, from partner ecosystem building to "
            "delivery acceleration and operational dashboards. "
            "I would value the opportunity to contribute to your team and help scale high-impact AI initiatives."
        )
        return _trim_to_words(draft, 120)

    def _render_referral(self, job: JobIngestRecord) -> str:
        line_1 = f"Hi, I'm exploring the {job.title_raw} opening at {job.company}."
        line_2 = "My background is in AI product strategy, GenAI solution design, and enterprise delivery impact."
        line_3 = "If relevant, I'd appreciate a quick referral or guidance on the right hiring contact."
        return "\n".join([line_1, line_2, line_3])


def _trim_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).strip()
