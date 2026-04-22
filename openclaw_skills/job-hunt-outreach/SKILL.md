---
name: job-hunt-outreach
description: Read Ravi's mirrored job-hunt workspace data, refresh the local `job_automation` pipeline on request, and turn tracked jobs into manual-outreach shortlists, contact summaries, and cover-letter angles. Use when Ravi asks to refresh job leads, review `job_hunt/` files, shortlist relevant roles, inspect public contact emails, or tailor manual outreach and cover letters from the OpenClaw workspace mirror.
---

# Job Hunt Outreach

## Overview

Use this skill to work from Ravi's mirrored `job_hunt/` data inside the OpenClaw workspace instead of asking him to re-paste job details into chat.
Refresh the mirror only when Ravi asks for fresh data or when the existing summary is obviously stale.
When you refresh, prefer a true fresh-source run: launch new Apify runs first, then ingest the resulting datasets, then rebuild outreach data, then sync the updated mirror back into the workspace.

## Workflow

1. If Ravi is following up on a refresh with `status`, `what is the status`, `is it done`, `did refresh finish`, or similar language, read `job_hunt/status/latest_refresh_status.md` first.
2. Read `job_hunt/summary/latest_outreach_summary.md` first for the current mirrored data state.
3. If you need row-level detail, read `job_hunt/outreach/latest_manual_outreach_leads.json`.
4. If you need tracker state, read the narrowest file that answers the question:
   - `job_hunt/tracker/review_queue.json`
   - `job_hunt/tracker/applications.json`
   - `job_hunt/tracker/contacts.json`
   - `job_hunt/tracker/jobs.json`
5. If Ravi asks for a refresh, or the mirror is stale relative to the conversation, run the generated refresh wrapper under `scripts/` immediately when `exec` is available. Do not just describe the command.
6. A normal refresh should launch fresh Apify runs, then ingest and sync. A contact-forcing refresh should additionally re-run Firecrawl contact discovery.
7. During a long-running refresh, use `job_hunt/status/latest_refresh_status.md` for progress updates instead of generic workspace memory.
8. After a refresh, re-read `job_hunt/status/latest_refresh_status.md` and `job_hunt/summary/latest_outreach_summary.md` before making recommendations.

## Refresh Commands

If the `exec` tool is available, prefer these exact commands from the workspace root.

Use PowerShell on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File "skills/job-hunt-outreach/scripts/refresh_job_hunt.ps1"
```

Use Bash or a direct Python invocation on Linux/macOS:

```bash
bash "skills/job-hunt-outreach/scripts/refresh_job_hunt.sh"
```

Use these versions when Ravi explicitly wants fresh contact discovery:

```powershell
powershell -ExecutionPolicy Bypass -File "skills/job-hunt-outreach/scripts/refresh_job_hunt.ps1" -RefreshContacts
```

```bash
bash "skills/job-hunt-outreach/scripts/refresh_job_hunt.sh" --refresh-contacts
```

If `exec` is unavailable, give Ravi those exact commands instead of paraphrasing them.

## Output Expectations

When Ravi asks for job recommendations or outreach help, return:

- role title
- company
- department or team hint
- multiple relevant public contacts from the hiring-side team when present
- for each contact: name, role, public email, and source URL
- short reason the role fits Ravi
- 3 cover-letter angles
- any confidence warning if the contact looks weak

When filtering, prefer:

- public recruiting or hiring emails
- multiple contacts within the relevant team over a single generic inbox
- company domains over people-directory results
- roles that fit AI solution expert, GenAI solutions, solutions consulting, customer engineering, presales, AI product, or enterprise AI strategy work
- roles with a clear department hint and a usable source URL
- AI / GenAI employers and enterprise AI teams in India or Singapore

Flag low confidence when:

- the email is missing
- the source URL is a people directory or generic lead database
- the email domain does not clearly match the employer or an obvious recruiting vendor
- the contact looks unrelated to hiring

## Guardrails

- Do not send emails automatically.
- Do not claim a contact is verified if it only came from a low-confidence directory.
- Treat `job_hunt/` as the source of truth for this workflow inside OpenClaw.
- Treat `job_hunt/status/latest_refresh_status.md` as the source of truth for in-flight or just-finished refresh progress.
- Prefer explicit file reads over vague memory claims.
- Keep manual outreach manual. Draft, rank, and summarize, but ask before any outbound action.

## Good Requests

- `Refresh my job hunt mirror and tell me the 10 best outreach-ready roles.`
- `Read the job_hunt files and shortlist AI product roles with public recruiting emails.`
- `For these leads, give me department hints and 3 cover-letter angles each.`
- `Show me which contacts look low confidence and should be skipped.`

## Resource

- `scripts/refresh_job_hunt.py`: cross-platform pipeline runner with explicit repo/workspace arguments.
- `scripts/refresh_job_hunt.ps1`: Windows wrapper rendered during workspace sync.
- `scripts/refresh_job_hunt.sh`: Linux/macOS wrapper rendered during workspace sync.
