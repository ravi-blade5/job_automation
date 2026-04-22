import json
import shutil
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.artifacts import ApplicationArtifactGenerator
from job_automation.job_automation.enrichment.jd_parser import RuleBasedJDParser
from job_automation.job_automation.enrichment.perplexity import CompanyEnricher
from job_automation.job_automation.models import ApplicationStatus
from job_automation.job_automation.pipeline import JobAutomationPipeline
from job_automation.job_automation.scoring import FitScorer
from job_automation.job_automation.sources.mock_source import MockJobSource
from job_automation.job_automation.tracking.local_json import LocalJSONTrackingRepository


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "data"
        self.artifacts_dir = self.root / "artifacts"
        self.resume_dir = self.root / "resume"
        self.resume_dir.mkdir(parents=True, exist_ok=True)
        (self.resume_dir / "resume_variant_a_ai_product_manager.md").write_text("A", encoding="utf-8")
        (self.resume_dir / "resume_variant_b_genai_product_solutions_lead.md").write_text("B", encoding="utf-8")
        self.mock_path = self.root / "jobs.json"
        self.mock_path.write_text(
            json.dumps(
                [
                    {
                        "external_id": "alpha-1",
                        "title_raw": "AI Product Manager",
                        "company": "Alpha",
                        "location": "India",
                        "remote_type": "hybrid",
                        "job_url": "https://example.com/alpha-1",
                        "description_text": "Product strategy, roadmap, GTM, stakeholder, GenAI, RAG, OpenAI API.",
                        "date_posted": "2026-03-30",
                    }
                ]
            ),
            encoding="utf-8",
        )

        tracker = LocalJSONTrackingRepository(self.data_dir)
        source = MockJobSource(self.mock_path)
        scorer = FitScorer(must_apply_threshold=40, good_fit_threshold=30)
        generator = ApplicationArtifactGenerator(self.artifacts_dir, self.resume_dir)

        self.pipeline = JobAutomationPipeline(
            sources=[source],
            tracker=tracker,
            scorer=scorer,
            artifact_generator=generator,
            jd_parser=RuleBasedJDParser(),
            company_enricher=CompanyEnricher(),
        )

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def test_rejected_application_cannot_generate_artifacts(self) -> None:
        self.pipeline.run_daily()
        queue = self.pipeline.tracker.list_review_queue()
        self.assertEqual(1, len(queue))
        app = self.pipeline.reject_application(queue[0].application_id)
        self.assertEqual("rejected", app.status.value)
        with self.assertRaises(PermissionError):
            self.pipeline.generate_artifacts(app.application_id)

    def test_approved_application_generates_documents(self) -> None:
        self.pipeline.run_daily()
        queue = self.pipeline.tracker.list_review_queue()
        app = self.pipeline.approve_application(queue[0].application_id)
        generated = self.pipeline.generate_artifacts(app.application_id)

        self.assertIn("cover_note", generated)
        self.assertIn("resume_summary", generated)
        self.assertIn("referral_message", generated)

        docs = self.pipeline.tracker.list_documents(app.application_id)
        doc_types = {item.document_type for item in docs}
        self.assertTrue({"cover_note", "resume_summary", "referral_message"}.issubset(doc_types))

    def test_status_transition_validation(self) -> None:
        self.pipeline.run_daily()
        queue = self.pipeline.tracker.list_review_queue()
        app = queue[0]
        with self.assertRaises(ValueError):
            self.pipeline.advance_status(app.application_id, ApplicationStatus.OFFER)

    def test_followup_due_trigger(self) -> None:
        self.pipeline.run_daily()
        queue = self.pipeline.tracker.list_review_queue()
        app = self.pipeline.approve_application(queue[0].application_id)
        app = self.pipeline.mark_applied(app.application_id, applied_date=date(2026, 3, 1))
        due = self.pipeline.followups_due(on_date=date(2026, 3, 6))
        self.assertEqual(1, len(due))
        self.assertEqual(app.application_id, due[0].application_id)

    def test_dashboard_metrics(self) -> None:
        self.pipeline.run_daily()
        queue = self.pipeline.tracker.list_review_queue()
        app = self.pipeline.approve_application(queue[0].application_id)
        self.pipeline.mark_applied(app.application_id, applied_date=date(2026, 3, 1))
        self.pipeline.advance_status(app.application_id, ApplicationStatus.INTERVIEW)
        dashboard = self.pipeline.dashboard()
        self.assertGreaterEqual(dashboard["interview_rate_pct"], 100.0)
        self.assertGreaterEqual(dashboard["applications_total"], 1.0)


if __name__ == "__main__":
    unittest.main()
