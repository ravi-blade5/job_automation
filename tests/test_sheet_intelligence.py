import unittest

from job_automation.job_automation.enrichment.sheet_intelligence import (
    SheetIntelligence,
    WeightedKeyword,
)
from job_automation.job_automation.models import JobIngestRecord, RoleTrack
from job_automation.job_automation.scoring import FitScorer


class SheetIntelligenceTests(unittest.TestCase):
    def test_keyword_bank_returns_coverage_and_top_matches(self) -> None:
        intelligence = SheetIntelligence(
            keywords=[
                WeightedKeyword("Product Strategy", weight=10),
                WeightedKeyword("Product Roadmap", weight=8),
                WeightedKeyword("Stakeholder Management / Alignment", weight=5),
                WeightedKeyword("RAG", weight=4),
            ],
            benchmark_jds=[
                "Own product strategy, product roadmap, stakeholder alignment, and RAG evaluation."
            ],
        )

        result = intelligence.match(
            "Lead product strategy, own roadmap, align stakeholders, and define RAG evaluation."
        )

        self.assertGreaterEqual(result.keyword_match_pct, 80)
        self.assertGreaterEqual(result.benchmark_match_pct, 25)
        self.assertIn("product strategy", result.matched_keywords)

    def test_sheet_intelligence_adds_fit_reason_code(self) -> None:
        job = JobIngestRecord(
            job_id="job_sheet_1",
            source="mock",
            title_raw="AI Product Manager",
            company="ExampleCo",
            location="India",
            remote_type="hybrid",
            job_url="https://example.com",
            description_text=(
                "Own product strategy, product roadmap, stakeholder alignment, "
                "customer discovery, and GenAI platform adoption."
            ),
            date_posted="2026-05-03",
            scraped_at="2026-05-03T00:00:00Z",
        )
        intelligence = SheetIntelligence(
            keywords=[
                WeightedKeyword("Product Strategy", weight=10),
                WeightedKeyword("Product Roadmap", weight=8),
                WeightedKeyword("Customer Discovery", weight=6),
            ]
        )
        baseline = FitScorer(must_apply_threshold=90, good_fit_threshold=60)
        enriched = FitScorer(
            must_apply_threshold=90,
            good_fit_threshold=60,
            sheet_intelligence=intelligence,
        )

        baseline_score = baseline.score(job, RoleTrack.AI_PM)
        enriched_score = enriched.score(job, RoleTrack.AI_PM)

        self.assertGreater(enriched_score.fit_score, baseline_score.fit_score)
        self.assertTrue(
            any(code.startswith("curated_keyword_match") for code in enriched_score.reason_codes)
        )


if __name__ == "__main__":
    unittest.main()
