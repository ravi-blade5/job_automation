from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

CLOUD_OPENCLAW_HOME = "/home/openclaw/.openclaw"
CLOUD_OPENCLAW_WORKSPACE = f"{CLOUD_OPENCLAW_HOME}/workspace"
CLOUD_OPENCLAW_EXTENSIONS = f"{CLOUD_OPENCLAW_HOME}/extensions"

ADB_EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "dist",
    "build",
    "_tmp",
}
ADB_EXCLUDED_FILE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3"}
ADB_EXCLUDED_FILE_NAMES = {".DS_Store", "Thumbs.db", ".coverage"}
OPENCLAW_WORKSPACE_EXCLUDED_DIR_NAMES = {".git", ".openclaw", "__pycache__"}
OPENCLAW_WORKSPACE_EXCLUDED_FILE_SUFFIXES = {".pyc", ".pyo", ".log"}


@dataclass(frozen=True)
class GCPBundleResult:
    output_path: Path
    manifest_path: Path
    files_included: int
    generated_at: datetime


def build_gcp_sync_bundle(
    *,
    adb_root: Path,
    athena_root: Path,
    openclaw_root: Path,
    output_path: Path,
    generated_at: datetime | None = None,
) -> GCPBundleResult:
    generated_at = generated_at or datetime.now(UTC)
    adb_root = adb_root.resolve()
    athena_root = athena_root.resolve()
    openclaw_root = openclaw_root.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    local_config_path = openclaw_root / "openclaw.json"
    if not local_config_path.exists():
        raise FileNotFoundError(f"OpenClaw config not found: {local_config_path}")
    local_config = json.loads(local_config_path.read_text(encoding="utf-8-sig"))
    cloud_config = render_cloud_openclaw_config(local_config)

    files_included = 0
    with tarfile.open(output_path, "w:gz") as archive:
        files_included += _add_json_blob(
            archive,
            arcname="bundle/openclaw/openclaw.json",
            payload=cloud_config,
        )
        files_included += _add_optional_tree(
            archive,
            source_dir=openclaw_root / "workspace",
            arc_root="bundle/openclaw/workspace",
            include_filter=_include_openclaw_workspace_file,
        )
        for folder_name in ("agents", "credentials", "extensions", "identity"):
            files_included += _add_optional_tree(
                archive,
                source_dir=openclaw_root / folder_name,
                arc_root=f"bundle/openclaw/{folder_name}",
                include_filter=lambda _: True,
            )

        files_included += _add_optional_tree(
            archive,
            source_dir=athena_root,
            arc_root="bundle/adb_hcl/Athena-Public",
            include_filter=_include_adb_file,
        )
        files_included += _add_optional_tree(
            archive,
            source_dir=adb_root / "job_automation",
            arc_root="bundle/adb_hcl/job_automation",
            include_filter=_include_adb_file,
        )
        files_included += _add_optional_tree(
            archive,
            source_dir=adb_root / "astrology_profiles",
            arc_root="bundle/adb_hcl/astrology_profiles",
            include_filter=_include_adb_file,
        )

        env_path = adb_root / ".env"
        if env_path.exists():
            archive.add(env_path, arcname="bundle/adb_hcl/.env", recursive=False)
            files_included += 1

    manifest = {
        "generated_at": generated_at.isoformat(),
        "adb_root": str(adb_root),
        "athena_root": str(athena_root),
        "openclaw_root": str(openclaw_root),
        "output_path": str(output_path),
        "files_included": files_included,
            "cloud_paths": {
            "openclaw_home": CLOUD_OPENCLAW_HOME,
            "openclaw_workspace": CLOUD_OPENCLAW_WORKSPACE,
            "openclaw_agents": f"{CLOUD_OPENCLAW_HOME}/agents",
            "athena_root": "/srv/adb_hcl/Athena-Public",
            "job_automation_root": "/srv/adb_hcl/job_automation",
            "astrology_profiles_root": "/srv/adb_hcl/astrology_profiles",
        },
    }
    manifest_path = _manifest_path(output_path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return GCPBundleResult(
        output_path=output_path,
        manifest_path=manifest_path,
        files_included=files_included,
        generated_at=generated_at,
    )


def render_cloud_openclaw_config(
    local_config: dict[str, Any],
    *,
    workspace_path: str = CLOUD_OPENCLAW_WORKSPACE,
    extensions_path: str = CLOUD_OPENCLAW_EXTENSIONS,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(local_config))

    defaults = payload.get("agents", {}).get("defaults", {})
    if defaults.get("workspace"):
        defaults["workspace"] = workspace_path
    main_model = _main_agent_model(payload)
    if main_model:
        model_defaults = defaults.setdefault("model", {})
        if isinstance(model_defaults, dict):
            model_defaults["primary"] = main_model

    for agent in payload.get("agents", {}).get("list", []):
        if isinstance(agent, dict) and agent.get("workspace"):
            agent["workspace"] = workspace_path

    tools = payload.get("tools", {})
    if isinstance(tools, dict):
        also_allow = tools.get("alsoAllow")
        if isinstance(also_allow, list):
            tools["alsoAllow"] = [
                entry
                for entry in also_allow
                if entry not in {"ollama_web_search", "ollama_web_fetch"}
            ]

    plugins = payload.get("plugins", {})
    if isinstance(plugins, dict):
        allow = plugins.get("allow")
        if isinstance(allow, list):
            plugins["allow"] = [entry for entry in allow if entry != "openclaw-web-search"]

        entries = plugins.get("entries")
        if isinstance(entries, dict):
            entries.pop("openclaw-web-search", None)

    installs = payload.get("plugins", {}).get("installs", {})
    for install in installs.values():
        if not isinstance(install, dict):
            continue
        install_path = install.get("installPath")
        if not install_path:
            continue
        install["installPath"] = str(PurePosixPath(extensions_path) / Path(install_path).name)
    if isinstance(installs, dict):
        installs.pop("openclaw-web-search", None)

    return payload


def _add_json_blob(archive: tarfile.TarFile, *, arcname: str, payload: dict[str, Any]) -> int:
    body = json.dumps(payload, indent=2).encode("utf-8")
    info = tarfile.TarInfo(name=arcname)
    info.size = len(body)
    info.mtime = int(datetime.now(UTC).timestamp())
    archive.addfile(info, fileobj=_BytesReader(body))
    return 1


def _add_optional_tree(
    archive: tarfile.TarFile,
    *,
    source_dir: Path,
    arc_root: str,
    include_filter,
) -> int:
    if not source_dir.exists():
        return 0

    added = 0
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        rel_path = path.relative_to(source_dir)
        if not include_filter(rel_path):
            continue
        archive.add(path, arcname=f"{arc_root}/{rel_path.as_posix()}", recursive=False)
        added += 1
    return added


def _include_adb_file(relative_path: Path) -> bool:
    if any(part in ADB_EXCLUDED_DIR_NAMES for part in relative_path.parts):
        return False
    if relative_path.name in ADB_EXCLUDED_FILE_NAMES:
        return False
    if relative_path.suffix.lower() in ADB_EXCLUDED_FILE_SUFFIXES:
        return False
    return True


def _include_openclaw_workspace_file(relative_path: Path) -> bool:
    if any(part in OPENCLAW_WORKSPACE_EXCLUDED_DIR_NAMES for part in relative_path.parts):
        return False
    if relative_path.suffix.lower() in OPENCLAW_WORKSPACE_EXCLUDED_FILE_SUFFIXES:
        return False
    return True


def _manifest_path(output_path: Path) -> Path:
    name = output_path.name
    if name.endswith(".tar.gz"):
        stem = name[: -len(".tar.gz")]
    else:
        stem = output_path.stem
    return output_path.with_name(f"{stem}.manifest.json")


class _BytesReader:
    def __init__(self, body: bytes):
        self._body = body
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _main_agent_model(payload: dict[str, Any]) -> str | None:
    agents = payload.get("agents", {}).get("list", [])
    if not isinstance(agents, list):
        return None
    for agent in agents:
        if isinstance(agent, dict) and agent.get("id") == "main" and agent.get("model"):
            return str(agent["model"])
    for agent in agents:
        if isinstance(agent, dict) and agent.get("model"):
            return str(agent["model"])
    return None
