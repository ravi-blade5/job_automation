#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${JOB_AUTOMATION_REPO_ROOT:-}"
WORKSPACE_DIR="${JOB_AUTOMATION_WORKSPACE_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
PYTHON_BIN="${JOB_AUTOMATION_PYTHON:-python3}"

REFRESH_CONTACTS_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --workspace-dir)
      WORKSPACE_DIR="$2"
      shift 2
      ;;
    --refresh-contacts)
      REFRESH_CONTACTS_ARGS+=("--refresh-contacts")
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$REPO_ROOT" ]]; then
  echo "Set JOB_AUTOMATION_REPO_ROOT before running this script." >&2
  exit 1
fi

exec "$PYTHON_BIN" \
  "$SCRIPT_DIR/refresh_job_hunt.py" \
  --repo-root "$REPO_ROOT" \
  --workspace-dir "$WORKSPACE_DIR" \
  "${REFRESH_CONTACTS_ARGS[@]}"
