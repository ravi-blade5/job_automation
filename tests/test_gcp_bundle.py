import json
import shutil
import tarfile
import unittest
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.gcp_bundle import (
    build_gcp_sync_bundle,
    render_cloud_openclaw_config,
)


class GCPBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.adb_root = self.root / "adb"
        self.athena_root = self.adb_root / "Athena-Public"
        self.job_root = self.adb_root / "job_automation"
        self.openclaw_root = self.root / "openclaw"

        (self.athena_root / "docs").mkdir(parents=True, exist_ok=True)
        (self.athena_root / ".git").mkdir(parents=True, exist_ok=True)
        (self.athena_root / ".venv").mkdir(parents=True, exist_ok=True)
        (self.athena_root / "docs" / "README.md").write_text("# Athena\n", encoding="utf-8")
        (self.athena_root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (self.athena_root / ".venv" / "ignore.txt").write_text("skip\n", encoding="utf-8")

        (self.job_root / "job_automation").mkdir(parents=True, exist_ok=True)
        (self.job_root / "__pycache__").mkdir(parents=True, exist_ok=True)
        (self.job_root / "README.md").write_text("# Jobs\n", encoding="utf-8")
        (self.job_root / "job_automation" / "cli.py").write_text("print('ok')\n", encoding="utf-8")
        (self.job_root / "__pycache__" / "bad.pyc").write_bytes(b"skip")

        self.openclaw_root.mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "workspace").mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "workspace" / ".git").mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "workspace" / ".openclaw").mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "agents" / "main" / "agent").mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "credentials").mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "extensions" / "openclaw-web-search").mkdir(parents=True, exist_ok=True)
        (self.openclaw_root / "workspace" / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (self.openclaw_root / "workspace" / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (self.openclaw_root / "workspace" / ".openclaw" / "workspace-state.json").write_text("{}", encoding="utf-8")
        (self.openclaw_root / "agents" / "main" / "agent" / "auth-profiles.json").write_text(
            '{"version":1,"profiles":{"openai:default":{"provider":"openai","mode":"api_key"}}}',
            encoding="utf-8",
        )
        (self.openclaw_root / "credentials" / "openai.json").write_text("{}", encoding="utf-8")
        (self.openclaw_root / "extensions" / "openclaw-web-search" / "manifest.json").write_text(
            "{}",
            encoding="utf-8",
        )
        (self.adb_root / ".env").write_text("APIFY_API_TOKEN=test\n", encoding="utf-8")

        self.local_config = {
            "agents": {
                "defaults": {"workspace": "C:\\Users\\ravik\\.openclaw\\workspace"},
                "list": [
                    {"id": "main", "model": "openai/gpt-5.4"},
                    {"id": "telegram", "model": "openai/gpt-5.4-mini-2026-03-17", "workspace": "C:\\Users\\ravik\\.openclaw\\workspace"},
                ],
            },
            "plugins": {
                "installs": {
                    "openclaw-web-search": {
                        "installPath": "C:\\Users\\ravik\\.openclaw\\extensions\\openclaw-web-search"
                    }
                }
            },
        }
        (self.openclaw_root / "openclaw.json").write_text(json.dumps(self.local_config), encoding="utf-8")

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def test_render_cloud_openclaw_config_rewrites_workspace_and_extension_paths(self) -> None:
        payload = render_cloud_openclaw_config(self.local_config)

        self.assertEqual("/home/openclaw/.openclaw/workspace", payload["agents"]["defaults"]["workspace"])
        self.assertEqual(
            "/home/openclaw/.openclaw/workspace",
            payload["agents"]["list"][1]["workspace"],
        )
        self.assertEqual("openai/gpt-5.4", payload["agents"]["defaults"]["model"]["primary"])
        self.assertNotIn("openclaw-web-search", payload["plugins"].get("allow", []))
        self.assertNotIn("openclaw-web-search", payload["plugins"].get("installs", {}))

    def test_build_gcp_sync_bundle_packages_linux_ready_snapshot(self) -> None:
        output_path = self.root / "dist" / "openclaw-athena-sync.tar.gz"
        result = build_gcp_sync_bundle(
            adb_root=self.adb_root,
            athena_root=self.athena_root,
            openclaw_root=self.openclaw_root,
            output_path=output_path,
        )

        self.assertTrue(result.output_path.exists())
        self.assertTrue(result.manifest_path.exists())

        with tarfile.open(result.output_path, "r:gz") as archive:
            names = set(archive.getnames())

        self.assertIn("bundle/openclaw/openclaw.json", names)
        self.assertIn("bundle/openclaw/workspace/AGENTS.md", names)
        self.assertIn("bundle/openclaw/agents/main/agent/auth-profiles.json", names)
        self.assertIn("bundle/openclaw/credentials/openai.json", names)
        self.assertIn("bundle/openclaw/extensions/openclaw-web-search/manifest.json", names)
        self.assertIn("bundle/adb_hcl/Athena-Public/docs/README.md", names)
        self.assertIn("bundle/adb_hcl/job_automation/README.md", names)
        self.assertIn("bundle/adb_hcl/.env", names)
        self.assertNotIn("bundle/openclaw/workspace/.git/config", names)
        self.assertNotIn("bundle/openclaw/workspace/.openclaw/workspace-state.json", names)
        self.assertNotIn("bundle/adb_hcl/Athena-Public/.git/config", names)
        self.assertNotIn("bundle/adb_hcl/Athena-Public/.venv/ignore.txt", names)
        self.assertNotIn("bundle/adb_hcl/job_automation/__pycache__/bad.pyc", names)


if __name__ == "__main__":
    unittest.main()
