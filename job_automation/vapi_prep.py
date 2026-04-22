from __future__ import annotations

from pathlib import Path

from .models import ApplicationRecord, JobIngestRecord


class VapiInterviewPrep:
    def __init__(self, artifacts_root: Path):
        self.artifacts_root = artifacts_root
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def build_mock_screen_pack(
        self,
        application: ApplicationRecord,
        job: JobIngestRecord,
    ) -> str:
        app_dir = self.artifacts_root / application.application_id
        app_dir.mkdir(parents=True, exist_ok=True)
        path = app_dir / "vapi_mock_screen_pack.txt"
        prompt = (
            f"Role: {job.title_raw} at {job.company}\n"
            f"Track: {application.role_track.value}\n\n"
            "Use this for recruiter mock calls:\n"
            "1) 60-second pitch\n"
            "2) Why this role/company\n"
            "3) Two quantified achievements\n"
            "4) Compensation expectation framing\n"
            "5) Availability and notice period\n\n"
            "Question Set:\n"
            "- Walk me through your current role and impact.\n"
            "- What GenAI outcomes have you shipped in production contexts?\n"
            "- Tell me about partner ecosystem decisions and commercial outcomes.\n"
            "- How do you prioritize roadmap under delivery constraints?\n"
            "- Describe a difficult stakeholder alignment scenario and result.\n"
        )
        path.write_text(prompt, encoding="utf-8")
        return str(path.resolve())

