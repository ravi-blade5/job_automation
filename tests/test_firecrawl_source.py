import unittest

from job_automation.job_automation.sources.firecrawl_source import (
    _derive_external_id,
    _extract_links_from_map_response,
    _filter_job_links,
    _is_specific_job_url,
    _looks_like_non_job_title,
    _normalize_remote_type,
)


class FirecrawlSourceTests(unittest.TestCase):
    def test_extract_links_from_map_response_shapes(self) -> None:
        body = {
            "links": ["https://example.com/jobs/1"],
            "data": [{"url": "https://boards.greenhouse.io/acme/jobs/123"}],
        }
        links = _extract_links_from_map_response(body)
        self.assertIn("https://example.com/jobs/1", links)
        self.assertIn("https://boards.greenhouse.io/acme/jobs/123", links)

    def test_filter_job_links_discards_non_job_links(self) -> None:
        links = [
            "https://acme.com/about",
            "https://acme.com/careers/backend-engineer",
            "https://www.linkedin.com/company/acme",
            "https://jobs.lever.co/acme/abc123",
        ]
        filtered = _filter_job_links(links, "https://acme.com/careers")
        self.assertIn("https://acme.com/careers/backend-engineer", filtered)
        self.assertIn("https://jobs.lever.co/acme/abc123", filtered)
        self.assertNotIn("https://acme.com/about", filtered)
        self.assertNotIn("https://www.linkedin.com/company/acme", filtered)

    def test_derive_external_id_prefers_query_job_id(self) -> None:
        job_url = "https://company.myworkdayjobs.com/en-US/roles/job?jobId=12345"
        external_id = _derive_external_id(job_url, "GenAI Product Lead")
        self.assertIn("jobid:12345", external_id)

    def test_normalize_remote_type(self) -> None:
        self.assertEqual("remote", _normalize_remote_type("Remote - India"))
        self.assertEqual("hybrid", _normalize_remote_type("Hybrid"))
        self.assertEqual("onsite", _normalize_remote_type("On-site"))
        self.assertEqual("unknown", _normalize_remote_type(""))

    def test_specific_job_url_filters_generic_pages(self) -> None:
        self.assertFalse(_is_specific_job_url("https://www.anthropic.com/jobs"))
        self.assertTrue(
            _is_specific_job_url("https://www.anthropic.com/careers/jobs/5025624008")
        )

    def test_closed_job_title_is_rejected(self) -> None:
        self.assertTrue(
            _looks_like_non_job_title("The job you are looking for is no longer open.")
        )
        self.assertFalse(_looks_like_non_job_title("Senior Product Manager, GenAI"))


if __name__ == "__main__":
    unittest.main()
