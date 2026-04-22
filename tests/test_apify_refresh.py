import json
import shutil
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from job_automation.job_automation.apify_refresh import refresh_apify_datasets


class ApifyRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.env_path = self.root / ".env"
        self.env_path.write_text("APIFY_DATASET_IDS=old1,old2\n", encoding="utf-8")
        self.summary_dir = self.root / "summaries"
        self.spec_path = self.root / "spec.json"
        self.spec_path.write_text(
            json.dumps(
                {
                    "queries": ["AI Product Manager"],
                    "locations": ["India"],
                    "max_results_per_run": 3,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    @patch("job_automation.job_automation.apify_refresh.request_json")
    def test_refresh_updates_env_with_new_dataset_ids(self, mock_request_json) -> None:
        mock_request_json.return_value.body = {
            "data": {
                "id": "run-1",
                "status": "SUCCEEDED",
                "defaultDatasetId": "fresh-dataset-1",
            }
        }

        result = refresh_apify_datasets(
            api_token="token",
            env_path=self.env_path,
            summary_dir=self.summary_dir,
            existing_dataset_ids=["old1", "old2"],
            provider="linkedin",
            spec_path=self.spec_path,
            generated_at=datetime(2026, 4, 12, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(["fresh-dataset-1"], result.successful_dataset_ids)
        self.assertFalse(result.used_existing_dataset_ids)
        self.assertTrue(result.updated_env)
        self.assertIn("APIFY_DATASET_IDS=fresh-dataset-1", self.env_path.read_text(encoding="utf-8"))
        self.assertTrue(result.summary_path.exists())

    @patch("job_automation.job_automation.apify_refresh.request_json")
    def test_refresh_falls_back_to_existing_dataset_ids(self, mock_request_json) -> None:
        mock_request_json.return_value.body = {
            "data": {
                "id": "run-1",
                "status": "FAILED",
                "defaultDatasetId": "",
            }
        }

        result = refresh_apify_datasets(
            api_token="token",
            env_path=self.env_path,
            summary_dir=self.summary_dir,
            existing_dataset_ids=["old1", "old2"],
            provider="linkedin",
            spec_path=self.spec_path,
            generated_at=datetime(2026, 4, 12, 12, 0, tzinfo=UTC),
        )

        self.assertEqual([], result.successful_dataset_ids)
        self.assertTrue(result.used_existing_dataset_ids)
        self.assertTrue(result.updated_env)
        self.assertIn("APIFY_DATASET_IDS=old1,old2", self.env_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
