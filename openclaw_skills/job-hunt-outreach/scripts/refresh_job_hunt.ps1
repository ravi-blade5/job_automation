[CmdletBinding()]
param(
    [switch]$RefreshContacts,
    [string]$RepoRoot = $env:JOB_AUTOMATION_REPO_ROOT,
    [string]$WorkspaceDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $WorkspaceDir) {
    $WorkspaceDir = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
}
if (-not $RepoRoot) {
    throw "Set JOB_AUTOMATION_REPO_ROOT or pass -RepoRoot."
}

$pythonBin = if ($env:JOB_AUTOMATION_PYTHON) { $env:JOB_AUTOMATION_PYTHON } else { "python" }
$args = @(
    (Join-Path $scriptDir "refresh_job_hunt.py"),
    "--repo-root", $RepoRoot,
    "--workspace-dir", $WorkspaceDir
)
if ($RefreshContacts.IsPresent) {
    $args += "--refresh-contacts"
}

& $pythonBin @args
