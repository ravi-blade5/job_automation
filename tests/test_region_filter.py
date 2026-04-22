import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.artifacts import ApplicationArtifactGenerator
from job_automation.job_automation.enrichment.jd_parser import RuleBasedJDParser
from job_automation.job_automation.enrichment.perplexity import CompanyEnricher
from job_automation.job_automation.pipeline import JobAutomationPipeline
from job_automation.job_automation.scoring import FitScorer
from job_automation.job_automation.sources.mock_source import MockJobSource
from job_automation.job_automation.tracking.local_json import LocalJSONTrackingRepository


class RegionFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.resume_dir = self.root / "resume"
        self.resume_dir.mkdir(parents=True, exist_ok=True)
        (self.resume_dir / "resume_variant_a_ai_product_manager.md").write_text("A", encoding="utf-8")
        (self.resume_dir / "resume_variant_b_genai_product_solutions_lead.md").write_text("B", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_only_target_regions_are_ingested(self) -> None:
        jobs_path = self.root / "jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "external_id": "in-1",
                        "title_raw": "AI Product Manager",
                        "company": "IndiaCo",
                        "location": "Bengaluru, India",
                        "remote_type": "hybrid",
                        "job_url": "https://example.com/in",
                        "description_text": "Roadmap and GTM",
                        "date_posted": "2026-03-30",
                    },
                    {
                        "external_id": "us-1",
                        "title_raw": "AI Product Manager",
                        "company": "USCo",
                        "location": "Austin, USA",
                        "remote_type": "onsite",
                        "job_url": "https://example.com/us",
                        "description_text": "Roadmap and GTM",
                        "date_posted": "2026-03-30",
                    },
                ]
            ),
            encoding="utf-8",
        )

        pipeline = JobAutomationPipeline(
            sources=[MockJobSource(jobs_path)],
            tracker=LocalJSONTrackingRepository(self.root / "data"),
            scorer=FitScorer(must_apply_threshold=40, good_fit_threshold=30),
            artifact_generator=ApplicationArtifactGenerator(self.root / "artifacts", self.resume_dir),
            jd_parser=RuleBasedJDParser(),
            company_enricher=CompanyEnricher(),
            region_filters=["India", "Remote", "APAC"],
        )
        ingested, deduped = pipeline.ingest_and_dedupe()
        self.assertEqual(2, ingested)
        self.assertEqual(1, deduped)

    def test_title_focus_filters_out_off_target_roles(self) -> None:
        jobs_path = self.root / "title_focus_jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "external_id": "pm-1",
                        "title_raw": "AI Product Manager",
                        "company": "TargetCo",
                        "location": "Bengaluru, India",
                        "remote_type": "hybrid",
                        "job_url": "https://example.com/pm",
                        "description_text": "Enterprise AI roadmap and customer discovery",
                        "date_posted": "2026-03-30",
                    },
                    {
                        "external_id": "acct-1",
                        "title_raw": "Senior Accountant",
                        "company": "NoiseCo",
                        "location": "Bengaluru, India",
                        "remote_type": "hybrid",
                        "job_url": "https://example.com/accountant",
                        "description_text": "Finance closing and reporting",
                        "date_posted": "2026-03-30",
                    },
                ]
            ),
            encoding="utf-8",
        )

        pipeline = JobAutomationPipeline(
            sources=[MockJobSource(jobs_path)],
            tracker=LocalJSONTrackingRepository(self.root / "focused_data"),
            scorer=FitScorer(must_apply_threshold=40, good_fit_threshold=30),
            artifact_generator=ApplicationArtifactGenerator(self.root / "focused_artifacts", self.resume_dir),
            jd_parser=RuleBasedJDParser(),
            company_enricher=CompanyEnricher(),
            region_filters=["India", "Remote", "APAC"],
            title_include_keywords=["ai product", "product manager", "genai"],
            title_exclude_keywords=["accountant"],
        )
        ingested, deduped = pipeline.ingest_and_dedupe()
        self.assertEqual(2, ingested)
        self.assertEqual(1, deduped)

    def test_apac_region_alias_keeps_singapore_role(self) -> None:
        jobs_path = self.root / "apac_jobs.json"
        jobs_path.write_text(
            json.dumps(
                [
                    {
                        "external_id": "sg-1",
                        "title_raw": "GenAI Product Manager",
                        "company": "TargetCo",
                        "location": "Singapore",
                        "remote_type": "hybrid",
                        "job_url": "https://example.com/sg",
                        "description_text": "Enterprise AI roadmap and partner ecosystem",
                        "date_posted": "2026-03-30",
                    },
                    {
                        "external_id": "uk-1",
                        "title_raw": "GenAI Product Manager",
                        "company": "NoiseCo",
                        "location": "London, United Kingdom",
                        "remote_type": "hybrid",
                        "job_url": "https://example.com/uk",
                        "description_text": "Enterprise AI roadmap and partner ecosystem",
                        "date_posted": "2026-03-30",
                    },
                ]
            ),
            encoding="utf-8",
        )

        pipeline = JobAutomationPipeline(
            sources=[MockJobSource(jobs_path)],
            tracker=LocalJSONTrackingRepository(self.root / "apac_data"),
            scorer=FitScorer(must_apply_threshold=40, good_fit_threshold=30),
            artifact_generator=ApplicationArtifactGenerator(self.root / "apac_artifacts", self.resume_dir),
            jd_parser=RuleBasedJDParser(),
            company_enricher=CompanyEnricher(),
            region_filters=["India", "Remote", "APAC"],
            title_include_keywords=["genai", "product manager"],
            title_exclude_keywords=[],
        )
        ingested, deduped = pipeline.ingest_and_dedupe()
        self.assertEqual(2, ingested)
        self.assertEqual(1, deduped)


if __name__ == "__main__":
    unittest.main()
