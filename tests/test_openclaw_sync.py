import json
import shutil
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.artifacts import ApplicationArtifactGenerator
from job_automation.job_automation.enrichment.jd_parser import RuleBasedJDParser
from job_automation.job_automation.enrichment.perplexity import CompanyEnricher
from job_automation.job_automation.models import ContactChannel, ContactRecord, JobIngestRecord
from job_automation.job_automation.openclaw_sync import (
    AGENTS_END_MARKER,
    AGENTS_START_MARKER,
    ATHENA_AGENTS_END_MARKER,
    ATHENA_AGENTS_START_MARKER,
    ATHENA_TOOLS_END_MARKER,
    ATHENA_TOOLS_START_MARKER,
    SYNC_END_MARKER,
    SYNC_START_MARKER,
    TOOLS_END_MARKER,
    TOOLS_START_MARKER,
    sync_to_openclaw_workspace,
)
from job_automation.job_automation.outreach import ManualOutreachLeadBuilder
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


class OpenClawSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "data"
        self.artifacts_dir = self.root / "artifacts"
        self.resume_dir = self.root / "resume"
        self.workspace_dir = self.root / "openclaw_workspace"
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

    def test_sync_to_openclaw_workspace_copies_tracker_and_outreach_files(self) -> None:
        pipeline = self._build_pipeline()
        pipeline.run_daily()
        builder = ManualOutreachLeadBuilder(
            tracker=pipeline.tracker,
            artifacts_root=self.artifacts_dir,
            contact_finder=_FakeFinder(),
        )
        builder.build_export(refresh_contacts=True)

        result = sync_to_openclaw_workspace(
            tracker=pipeline.tracker,
            artifacts_root=self.artifacts_dir,
            workspace_dir=self.workspace_dir,
            now_utc=datetime(2026, 4, 12, 5, 30, tzinfo=UTC),
        )

        self.assertTrue((self.workspace_dir / "job_hunt" / "README.md").exists())
        self.assertTrue((self.workspace_dir / "AGENTS.md").exists())
        self.assertTrue((self.workspace_dir / "TOOLS.md").exists())
        self.assertTrue((self.workspace_dir / "skills" / "job-hunt-outreach" / "SKILL.md").exists())
        self.assertTrue((self.workspace_dir / "skills" / "athena-context-router" / "SKILL.md").exists())
        self.assertTrue(
            (self.workspace_dir / "skills" / "job-hunt-outreach" / "scripts" / "refresh_job_hunt.py").exists()
        )
        self.assertTrue(
            (self.workspace_dir / "skills" / "job-hunt-outreach" / "scripts" / "refresh_job_hunt.ps1").exists()
        )
        self.assertTrue(
            (self.workspace_dir / "skills" / "job-hunt-outreach" / "scripts" / "refresh_job_hunt.sh").exists()
        )
        self.assertTrue((self.workspace_dir / "job_hunt" / "status" / "latest_refresh_status.md").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "status" / "latest_refresh_status.json").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "summary" / "latest_outreach_summary.md").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "outreach" / "latest_manual_outreach_leads.csv").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "outreach" / "latest_manual_outreach_leads.json").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "tracker" / "jobs.json").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "tracker" / "applications.json").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "tracker" / "review_queue.json").exists())
        self.assertTrue((self.workspace_dir / "job_hunt" / "tracker" / "contacts.json").exists())
        self.assertTrue((self.workspace_dir / "athena" / "README.md").exists())
        self.assertTrue((self.workspace_dir / "athena" / "memory_bank" / "activeContext.md").exists())
        self.assertTrue((self.workspace_dir / "athena" / "memories" / "case_studies").exists())
        self.assertTrue((self.workspace_dir / "athena" / "memories" / "session_logs").exists())
        self.assertEqual(1, result.leads_total)
        self.assertEqual(1, result.leads_with_email)
        self.assertEqual(1, result.contacts_total)
        self.assertEqual(self.workspace_dir / "job_hunt" / "status", result.status_dir)
        self.assertEqual(
            self.workspace_dir / "job_hunt" / "status" / "latest_refresh_status.md",
            result.refresh_status_path,
        )
        self.assertEqual(
            self.workspace_dir / "job_hunt" / "status" / "latest_refresh_status.json",
            result.refresh_status_json_path,
        )
        self.assertEqual(
            self.workspace_dir / "skills" / "job-hunt-outreach",
            result.skill_path,
        )
        self.assertEqual(self.workspace_dir / "athena", result.athena_dir)
        self.assertEqual(
            self.workspace_dir / "skills" / "athena-context-router",
            result.athena_skill_path,
        )

        daily_memory = (self.workspace_dir / "memory" / "2026-04-12.md").read_text(encoding="utf-8")
        self.assertIn(SYNC_START_MARKER, daily_memory)
        self.assertIn(SYNC_END_MARKER, daily_memory)
        self.assertIn("Outreach leads: **1** total, **1** with public email", daily_memory)
        agents_text = (self.workspace_dir / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(AGENTS_START_MARKER, agents_text)
        self.assertIn(AGENTS_END_MARKER, agents_text)
        self.assertIn("skills/job-hunt-outreach/SKILL.md", agents_text)
        self.assertIn("job_hunt/status/latest_refresh_status.md", agents_text)
        self.assertIn(ATHENA_AGENTS_START_MARKER, agents_text)
        self.assertIn(ATHENA_AGENTS_END_MARKER, agents_text)
        self.assertIn("skills/athena-context-router/SKILL.md", agents_text)
        tools_text = (self.workspace_dir / "TOOLS.md").read_text(encoding="utf-8")
        self.assertIn(TOOLS_START_MARKER, tools_text)
        self.assertIn(TOOLS_END_MARKER, tools_text)
        self.assertIn("refresh_job_hunt.ps1", tools_text)
        self.assertIn("latest_refresh_status.md", tools_text)
        self.assertIn("job_automation", tools_text)
        self.assertIn(ATHENA_TOOLS_START_MARKER, tools_text)
        self.assertIn(ATHENA_TOOLS_END_MARKER, tools_text)
        self.assertIn("activeContext.md", tools_text)
        readme_text = (self.workspace_dir / "job_hunt" / "README.md").read_text(encoding="utf-8")
        self.assertIn("status/latest_refresh_status.md", readme_text)
        summary_text = (self.workspace_dir / "job_hunt" / "summary" / "latest_outreach_summary.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("job_hunt/status/latest_refresh_status.md", summary_text)

        second = sync_to_openclaw_workspace(
            tracker=pipeline.tracker,
            artifacts_root=self.artifacts_dir,
            workspace_dir=self.workspace_dir,
            now_utc=datetime(2026, 4, 12, 6, 0, tzinfo=UTC),
        )
        self.assertEqual(result.job_hunt_dir, second.job_hunt_dir)
        daily_memory_after = (self.workspace_dir / "memory" / "2026-04-12.md").read_text(encoding="utf-8")
        self.assertEqual(1, daily_memory_after.count(SYNC_START_MARKER))
        agents_after = (self.workspace_dir / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(1, agents_after.count(AGENTS_START_MARKER))
        self.assertEqual(1, agents_after.count(ATHENA_AGENTS_START_MARKER))
        tools_after = (self.workspace_dir / "TOOLS.md").read_text(encoding="utf-8")
        self.assertEqual(1, tools_after.count(TOOLS_START_MARKER))
        self.assertEqual(1, tools_after.count(ATHENA_TOOLS_START_MARKER))


if __name__ == "__main__":
    unittest.main()
