import csv
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from job_automation.job_automation.artifacts import ApplicationArtifactGenerator
from job_automation.job_automation.enrichment.jd_parser import RuleBasedJDParser
from job_automation.job_automation.enrichment.perplexity import CompanyEnricher
from job_automation.job_automation.http_client import HttpResponse
from job_automation.job_automation.models import (
    ContactChannel,
    ContactRecord,
    JobIngestRecord,
)
from job_automation.job_automation.outreach import (
    FirecrawlContactFinder,
    ManualOutreachLeadBuilder,
    _extract_contacts_from_markdown,
    infer_department_hint,
)
from job_automation.job_automation.pipeline import JobAutomationPipeline
from job_automation.job_automation.scoring import FitScorer
from job_automation.job_automation.sources.mock_source import MockJobSource
from job_automation.job_automation.tracking.local_json import LocalJSONTrackingRepository


class _FakeFinder:
    def discover(self, job: JobIngestRecord):
        return [
            ContactRecord.create(
                job_id=job.job_id,
                company=job.company,
                contact_value="careers@alpha.ai",
                channel=ContactChannel.EMAIL,
                role="Recruiting / Talent",
                department="Recruiting / Talent",
                source_url="https://alpha.ai/careers/contact",
                notes="Public recruiting email found on careers contact page.",
            )
        ]


class OutreachTests(unittest.TestCase):
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
                        "company": "Alpha AI",
                        "location": "India",
                        "remote_type": "hybrid",
                        "job_url": "https://alpha.ai/careers/ai-product-manager",
                        "description_text": "Own roadmap, GTM, stakeholder alignment, GenAI strategy, and partner ecosystem.",
                        "date_posted": "2026-03-30",
                    }
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def _build_pipeline(self) -> JobAutomationPipeline:
        tracker = LocalJSONTrackingRepository(self.data_dir)
        source = MockJobSource(self.mock_path)
        scorer = FitScorer(must_apply_threshold=40, good_fit_threshold=30)
        generator = ApplicationArtifactGenerator(self.artifacts_dir, self.resume_dir)
        return JobAutomationPipeline(
            sources=[source],
            tracker=tracker,
            scorer=scorer,
            artifact_generator=generator,
            jd_parser=RuleBasedJDParser(),
            company_enricher=CompanyEnricher(),
        )

    def test_extract_contacts_from_markdown_prefers_recruiting_email(self) -> None:
        job = JobIngestRecord(
            job_id="job_1",
            source="company_site",
            title_raw="AI Product Manager",
            company="Alpha AI",
            location="India",
            remote_type="hybrid",
            job_url="https://alpha.ai/careers/ai-product-manager",
            description_text="Own roadmap and GTM execution.",
            date_posted="2026-04-01",
            scraped_at="2026-04-01T00:00:00+00:00",
        )
        markdown = """
        # Careers Contact
        Reach our Talent Acquisition team at careers@alpha.ai
        for questions about the AI Product Manager opening.
        """
        contacts = _extract_contacts_from_markdown(job, markdown, "https://alpha.ai/careers/contact")
        self.assertEqual(1, len(contacts))
        self.assertEqual("careers@alpha.ai", contacts[0].contact_value)
        self.assertEqual("Recruiting / Talent", contacts[0].role)
        self.assertEqual("Recruiting / Talent", contacts[0].department)

    def test_extract_contacts_skips_personal_and_fake_asset_emails(self) -> None:
        job = JobIngestRecord(
            job_id="job_1b",
            source="company_site",
            title_raw="AI Solution Expert",
            company="Alpha AI",
            location="Singapore",
            remote_type="hybrid",
            job_url="https://alpha.ai/careers/ai-solution-expert",
            description_text="Lead solution design and customer workshops.",
            date_posted="2026-04-01",
            scraped_at="2026-04-01T00:00:00+00:00",
        )
        markdown = """
        Reach talent acquisition at careers@alpha.ai.
        For GenAI solution questions contact solutions@alpha.ai.
        Ignore r@gmail.com and home-women-1@3x.webp.
        """
        contacts = _extract_contacts_from_markdown(job, markdown, "https://alpha.ai/team")
        values = {item.contact_value for item in contacts}
        self.assertIn("careers@alpha.ai", values)
        self.assertIn("solutions@alpha.ai", values)
        self.assertNotIn("r@gmail.com", values)
        self.assertNotIn("home-women-1@3x.webp", values)

    @patch("job_automation.job_automation.outreach.request_json")
    def test_firecrawl_contact_finder_uses_search_results(self, mock_request_json) -> None:
        mock_request_json.return_value = HttpResponse(
            status_code=200,
            body={
                "data": [
                    {
                        "url": "https://alpha.ai/careers/contact",
                        "title": "Alpha AI Careers Contact",
                        "description": "Reach the recruiting team",
                        "markdown": "Talent Acquisition\nEmail careers@alpha.ai for hiring questions.",
                    }
                ]
            },
            raw="",
        )
        finder = FirecrawlContactFinder(api_key="fc_test")
        job = JobIngestRecord(
            job_id="job_1",
            source="apify",
            title_raw="AI Product Manager",
            company="Alpha AI",
            location="India",
            remote_type="hybrid",
            job_url="https://jobs.example.com/alpha-1",
            description_text="Own roadmap and GTM execution.",
            date_posted="2026-04-01",
            scraped_at="2026-04-01T00:00:00+00:00",
        )
        contacts = finder.discover(job)
        self.assertEqual(1, len(contacts))
        self.assertEqual("careers@alpha.ai", contacts[0].contact_value)

    def test_manual_outreach_export_builds_combined_csv(self) -> None:
        pipeline = self._build_pipeline()
        pipeline.run_daily()
        builder = ManualOutreachLeadBuilder(
            tracker=pipeline.tracker,
            artifacts_root=self.artifacts_dir,
            contact_finder=_FakeFinder(),
        )
        result = builder.build_export(refresh_contacts=True)

        self.assertEqual(1, result.contacts_discovered)
        self.assertTrue(result.csv_path.exists())
        self.assertTrue(result.json_path.exists())

        contacts = pipeline.tracker.list_contacts()
        self.assertEqual(1, len(contacts))
        self.assertEqual("careers@alpha.ai", contacts[0].contact_value)

        with result.csv_path.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(1, len(rows))
        self.assertEqual("careers@alpha.ai", rows[0]["contact_email"])
        self.assertEqual("Recruiting / Talent", rows[0]["department_hint"])
        self.assertIn("product strategy", rows[0]["cover_letter_focus"].lower())

    def test_department_hint_for_product_role(self) -> None:
        job = JobIngestRecord(
            job_id="job_2",
            source="mock",
            title_raw="Senior AI Product Manager",
            company="Beta",
            location="Remote",
            remote_type="remote",
            job_url="https://beta.example/jobs/2",
            description_text="Drive roadmap, GTM, and stakeholder alignment for enterprise AI products.",
            date_posted="2026-04-01",
            scraped_at="2026-04-01T00:00:00+00:00",
        )
        self.assertEqual("Product / Strategy", infer_department_hint(job))

    def test_department_hint_for_solution_expert_role(self) -> None:
        job = JobIngestRecord(
            job_id="job_3",
            source="mock",
            title_raw="Senior AI Solution Expert",
            company="Gamma",
            location="Singapore",
            remote_type="hybrid",
            job_url="https://gamma.example/jobs/3",
            description_text="Own customer workshops, solution architecture, and presales support for GenAI programs.",
            date_posted="2026-04-01",
            scraped_at="2026-04-01T00:00:00+00:00",
        )
        self.assertEqual("Solutions / Presales", infer_department_hint(job))


if __name__ == "__main__":
    unittest.main()
