import unittest

from job_automation.job_automation.enrichment.jd_parser import RuleBasedJDParser
from job_automation.job_automation.models import JobIngestRecord, RoleTrack
from job_automation.job_automation.scoring import FitScorer


class ScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scorer = FitScorer(must_apply_threshold=80, good_fit_threshold=65)
        self.parser = RuleBasedJDParser()

    def test_missing_salary_and_location_still_scores(self) -> None:
        job = JobIngestRecord(
            job_id="job_1",
            source="mock",
            title_raw="GenAI Product Lead",
            company="TestCo",
            location="",
            remote_type="remote",
            job_url="https://example.com/genai",
            description_text="Lead GenAI roadmap, RAG evaluation, and prompt engineering for enterprise workflows.",
            date_posted="2026-03-30",
            scraped_at="2026-03-30T00:00:00Z",
        )
        parsed = self.parser.parse(job)
        self.assertTrue(parsed.normalized_title)
        score = self.scorer.score(job, RoleTrack.GENAI_LEAD)
        self.assertGreaterEqual(score.fit_score, 0)

    def test_same_job_scores_differently_across_tracks(self) -> None:
        job = JobIngestRecord(
            job_id="job_2",
            source="mock",
            title_raw="AI Product Manager",
            company="Delta",
            location="India",
            remote_type="hybrid",
            job_url="https://example.com/pm",
            description_text=(
                "Own product strategy, roadmap, GTM and stakeholder management for "
                "GenAI workflows with RAG and OpenAI API."
            ),
            date_posted="2026-03-30",
            scraped_at="2026-03-30T00:00:00Z",
        )
        ai_pm = self.scorer.score(job, RoleTrack.AI_PM)
        genai = self.scorer.score(job, RoleTrack.GENAI_LEAD)
        self.assertNotEqual(ai_pm.fit_score, genai.fit_score)

    def test_relevant_title_without_description_still_gets_good_fit(self) -> None:
        job = JobIngestRecord(
            job_id="job_3",
            source="apify",
            title_raw="GenAI Solutions Lead",
            company="ExampleCo",
            location="India",
            remote_type="remote",
            job_url="https://example.com/lead",
            description_text="",
            date_posted="2026-04-01",
            scraped_at="2026-04-01T00:00:00Z",
        )
        scorer = FitScorer(must_apply_threshold=68, good_fit_threshold=48)
        score = scorer.score(job, RoleTrack.GENAI_LEAD)
        self.assertGreaterEqual(score.fit_score, 45)
        self.assertEqual("good_fit", score.decision.value)

    def test_preferred_company_gets_score_boost(self) -> None:
        job = JobIngestRecord(
            job_id="job_4",
            source="apify",
            title_raw="AI Product Manager",
            company="Databricks",
            location="Singapore",
            remote_type="hybrid",
            job_url="https://example.com/databricks-ai-pm",
            description_text="Own roadmap, GTM, stakeholder alignment, and enterprise AI adoption.",
            date_posted="2026-04-12",
            scraped_at="2026-04-12T00:00:00Z",
        )
        baseline = FitScorer(must_apply_threshold=80, good_fit_threshold=65)
        focused = FitScorer(
            must_apply_threshold=80,
            good_fit_threshold=65,
            company_focus_keywords=["databricks", "snowflake"],
            company_focus_bonus=12,
        )

        baseline_score = baseline.score(job, RoleTrack.AI_PM)
        focused_score = focused.score(job, RoleTrack.AI_PM)

        self.assertGreater(focused_score.fit_score, baseline_score.fit_score)
        self.assertIn("preferred_company_match", focused_score.reason_codes)

    def test_solution_expert_title_scores_for_genai_track(self) -> None:
        job = JobIngestRecord(
            job_id="job_5",
            source="mock",
            title_raw="Senior AI Solution Expert",
            company="Fractal",
            location="India",
            remote_type="hybrid",
            job_url="https://example.com/solution-expert",
            description_text=(
                "Lead customer workshops, solution design, GenAI architecture, demos, and presales discovery "
                "for enterprise AI programs."
            ),
            date_posted="2026-04-12",
            scraped_at="2026-04-12T00:00:00Z",
        )
        score = self.scorer.score(job, RoleTrack.GENAI_LEAD)
        self.assertGreaterEqual(score.fit_score, 60)
        self.assertIn("strong_title_alignment", score.reason_codes)

    def test_uploaded_resume_profile_boosts_relevant_jobs(self) -> None:
        job = JobIngestRecord(
            job_id="job_6",
            source="mock",
            title_raw="AI Product Manager",
            company="ExampleAI",
            location="India",
            remote_type="remote",
            job_url="https://example.com/profile-fit",
            description_text=(
                "Own GenAI roadmap, RAG setup, model evaluation, prompt optimization, "
                "responsible AI governance, partner pilots, Python analytics, and KPI tracking."
            ),
            date_posted="2026-05-01",
            scraped_at="2026-05-01T00:00:00Z",
        )
        baseline = FitScorer(must_apply_threshold=80, good_fit_threshold=65)
        profiled = FitScorer(
            must_apply_threshold=80,
            good_fit_threshold=65,
            resume_profile_keywords=[
                "genai",
                "rag",
                "model evaluation",
                "prompt optimization",
                "responsible ai",
                "partner",
                "python",
                "kpi",
            ],
        )

        baseline_score = baseline.score(job, RoleTrack.AI_PM)
        profiled_score = profiled.score(job, RoleTrack.AI_PM)

        self.assertGreater(profiled_score.fit_score, baseline_score.fit_score)
        self.assertTrue(
            any(reason.startswith("resume_profile_match:") for reason in profiled_score.reason_codes)
        )


if __name__ == "__main__":
    unittest.main()
