import base64
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.profile_store import (
    ResumeProfileStore,
    derive_resume_keywords,
)


class ResumeProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        self.data_dir = self.root / "data"
        self.store = ResumeProfileStore(data_dir=self.data_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_saves_text_resume_profile(self) -> None:
        resume_text = (
            "AI Product Manager with GenAI roadmap, RAG setup, prompt optimization, "
            "model evaluation, responsible AI governance, product strategy, GTM, "
            "partner onboarding, Python, Power BI, and enterprise SaaS experience."
        )
        encoded = base64.b64encode(resume_text.encode("utf-8")).decode("ascii")

        profile = self.store.save(filename="resume.txt", content_base64=encoded)

        self.assertTrue(profile.is_active)
        self.assertGreater(len(profile.keywords), 0)
        self.assertIn("rag", profile.keywords)
        self.assertTrue((self.data_dir / "resume_profile" / "current_profile.json").is_file())

    def test_derives_keywords_from_resume_text(self) -> None:
        keywords = derive_resume_keywords(
            "Enterprise AI consultant with RAG, agentic AI, model evaluation, cloud architecture, and API integration."
        )

        self.assertIn("rag", keywords)
        self.assertIn("agentic ai", keywords)
        self.assertIn("api integration", keywords)

    def test_rejects_too_short_resume(self) -> None:
        encoded = base64.b64encode(b"short").decode("ascii")
        with self.assertRaises(ValueError):
            self.store.save(filename="resume.txt", content_base64=encoded)


if __name__ == "__main__":
    unittest.main()
