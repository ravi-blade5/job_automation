import unittest

from job_automation.job_automation.sources.apify_source import (
    _extract_items,
    _map_apify_item,
)


class ApifySourceTests(unittest.TestCase):
    def test_map_item_with_nested_company(self) -> None:
        item = {
            "jobTitle": "Senior Product Manager, AI",
            "company": {"name": "Example Corp"},
            "jobLocation": "Bengaluru",
            "jobUrl": "https://jobs.example.com/123",
            "jobId": "123",
            "description": "Own roadmap and GTM.",
        }
        record = _map_apify_item(item)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("Senior Product Manager, AI", record.title_raw)
        self.assertEqual("Example Corp", record.company)
        self.assertEqual("https://jobs.example.com/123", record.job_url)

    def test_map_item_without_company_but_with_url(self) -> None:
        item = {
            "title": "GenAI Solutions Lead",
            "url": "https://careers.acme.ai/jobs/abc",
            "description": "Lead GenAI solutions.",
        }
        record = _map_apify_item(item)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("GenAI Solutions Lead", record.title_raw)
        self.assertEqual("Careers", record.company)

    def test_extract_items_multiple_shapes(self) -> None:
        body_1 = {"items": [{"a": 1}]}
        body_2 = {"data": [{"b": 2}]}
        body_3 = {"results": [{"c": 3}]}
        self.assertEqual(1, len(_extract_items(body_1)))
        self.assertEqual(1, len(_extract_items(body_2)))
        self.assertEqual(1, len(_extract_items(body_3)))


if __name__ == "__main__":
    unittest.main()

