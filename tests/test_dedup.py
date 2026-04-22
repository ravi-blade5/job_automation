import unittest

from job_automation.job_automation.dedup import dedupe_jobs
from job_automation.job_automation.models import JobIngestRecord


class DedupeTests(unittest.TestCase):
    def test_duplicate_job_urls_are_merged(self) -> None:
        job_old = JobIngestRecord(
            job_id="a1",
            source="mock",
            title_raw="AI Product Manager",
            company="Alpha",
            location="Bengaluru",
            remote_type="hybrid",
            job_url="https://example.com/jobs/1",
            description_text="older",
            date_posted="2026-03-28",
            scraped_at="2026-03-28T00:00:00Z",
        )
        job_new = JobIngestRecord(
            job_id="a2",
            source="mock",
            title_raw="AI Product Manager",
            company="Alpha",
            location="Bengaluru",
            remote_type="hybrid",
            job_url="https://example.com/jobs/1",
            description_text="newer",
            date_posted="2026-03-30",
            scraped_at="2026-03-30T00:00:00Z",
        )
        deduped = dedupe_jobs([job_old, job_new])
        self.assertEqual(1, len(deduped))
        self.assertEqual("a2", deduped[0].job_id)


if __name__ == "__main__":
    unittest.main()

