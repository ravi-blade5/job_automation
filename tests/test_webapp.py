import json
import shutil
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.artifacts import ApplicationArtifactGenerator
from job_automation.job_automation.enrichment.jd_parser import RuleBasedJDParser
from job_automation.job_automation.enrichment.perplexity import CompanyEnricher
from job_automation.job_automation.pipeline import JobAutomationPipeline
from job_automation.job_automation.scoring import FitScorer
from job_automation.job_automation.sources.mock_source import MockJobSource
from job_automation.job_automation.tracking.local_json import LocalJSONTrackingRepository
from job_automation.job_automation.webapp import (
    _parse_applied_on,
    _parse_target_status,
    _resolve_application_document,
    build_overview_payload,
)


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "data"
        self.artifacts_dir = self.root / "artifacts"
        self.resume_dir = self.root / "resume"
        self.resume_dir.mkdir(parents=True, exist_ok=True)
        (self.resume_dir / "resume_variant_a_ai_product_manager.md").write_text(
            "A",
            encoding="utf-8",
        )
        (self.resume_dir / "resume_variant_b_genai_product_solutions_lead.md").write_text(
            "B",
            encoding="utf-8",
        )
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
        self.pipeline = JobAutomationPipeline(
            sources=[MockJobSource(self.mock_path)],
            tracker=LocalJSONTrackingRepository(self.data_dir),
            scorer=FitScorer(must_apply_threshold=40, good_fit_threshold=30),
            artifact_generator=ApplicationArtifactGenerator(
                self.artifacts_dir,
                self.resume_dir,
            ),
            jd_parser=RuleBasedJDParser(),
            company_enricher=CompanyEnricher(),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_build_overview_payload_contains_review_items(self) -> None:
        self.pipeline.run_daily()

        payload = build_overview_payload(self.pipeline, "json")

        self.assertEqual("json", payload["tracker"])
        self.assertEqual(1, payload["summary"]["jobs_total"])
        self.assertEqual(1, payload["summary"]["applications_total"])
        self.assertEqual(1, payload["summary"]["review_queue_total"])
        self.assertEqual(1, len(payload["jobs"]))
        self.assertTrue(payload["activity"])
        review_item = payload["review_queue"][0]
        self.assertEqual("AI Product Manager", review_item["job"]["title_raw"])
        self.assertEqual("Alpha", review_item["job"]["company"])

    def test_parse_applied_on_defaults_to_today(self) -> None:
        self.assertEqual(date.today(), _parse_applied_on({}))

    def test_parse_applied_on_rejects_invalid_date(self) -> None:
        with self.assertRaises(ValueError):
            _parse_applied_on({"applied_on": "06-04-2026"})

    def test_parse_target_status_accepts_known_status(self) -> None:
        self.assertEqual("interview", _parse_target_status({"status": "interview"}).value)

    def test_parse_target_status_rejects_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            _parse_target_status({"status": "saved"})

    def test_resolve_application_document_returns_generated_file(self) -> None:
        self.pipeline.run_daily()
        application = self.pipeline.tracker.list_applications()[0]
        self.pipeline.approve_application(application.application_id)
        self.pipeline.generate_artifacts(application.application_id)

        document_path = _resolve_application_document(
            self.pipeline,
            application_id=application.application_id,
            document_type="resume_summary",
        )

        self.assertTrue(document_path.is_file())
        self.assertEqual("resume_summary.txt", document_path.name)


if __name__ == "__main__":
    unittest.main()
