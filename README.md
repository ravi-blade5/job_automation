# Automated Job Discovery + Human-Approved Application System

This module implements a production-ready starter workflow for:

- Multi-source job ingestion (`Apify`, `Firecrawl`, local mock input)
- Dual-track fit scoring (`AI Product Manager`, `GenAI Product/Solutions Lead`)
- Human-approved application workflow
- Manual outreach lead export with public hiring emails + department hints
- Google Sheets / Airtable tracking with JSON fallback
- Auto-generated application artifacts (resume summary, cover note, referral message)
- JD-to-LaTeX resume tailoring portal for AI PM, AI Solution Architect, and AI Consultant tracks
- Resume/profile upload for resume-aware job scoring before `Run Daily`
- Follow-up reminders and weekly dashboard metrics

## Quick Start

1. Copy `.env.example` to `.env` and fill keys.
2. For Google Sheets, follow `docs/google_sheets_setup.md`.
3. (Optional) Create Airtable base/tables using `docs/airtable_schema.md`.
4. Run with mock data first:

```powershell
python -m job_automation.cli run-daily --tracker json
python -m job_automation.cli list-review-queue --tracker json
```

5. Build a manual-outreach export:

```powershell
python -m job_automation.cli build-outreach-leads --tracker json --refresh-contacts
```

This writes timestamped CSV/JSON files under `job_automation/artifacts/outreach/` with:

- `job_title`
- `company`
- `job_url`
- `department_hint`
- `contact_email`
- `contact_source_url`
- `cover_letter_focus`

6. Approve and generate artifacts:

```powershell
python -m job_automation.cli approve --application-id <id> --tracker json
python -m job_automation.cli generate-artifacts --application-id <id> --tracker json
python -m job_automation.cli mark-applied --application-id <id> --tracker json
```

7. Start the lightweight browser app:

```powershell
python -m job_automation.webapp --tracker google_sheets --port 8787
```

The browser app now supports:

- Run-daily from the UI
- Searchable review queue, applications, jobs, and activity views
- Status progression and follow-up completion from the browser
- Artifact links served directly from the local app for quick review
- A Resume Tailor tab that accepts a pasted JD and generates a tailored `.tex` resume, PDF resume, 120-word cover note, 3-line referral message, and keyword report
- A resume/profile upload control that accepts PDF, DOCX, TXT, or MD and applies resume-aware scoring when `Run Daily` is clicked

8. Switch to Google Sheets by setting `JOB_AUTOMATION_TRACKER=google_sheets`.
9. Switch to Airtable by setting `JOB_AUTOMATION_TRACKER=airtable`.
10. Keep `JOB_AUTOMATION_USE_MOCK_SOURCE=false` for real job links only.

## Commands

- `run-daily`: ingestion + dedup + dual-track scoring + review queue build
- `list-review-queue`: jobs awaiting your approval
- `build-outreach-leads`: discovers public hiring emails with Firecrawl and exports a manual-outreach CSV/JSON
- `approve`: move an item into screening
- `reject`: mark item rejected (blocks artifact generation)
- `generate-artifacts`: creates summary/cover/referral docs for approved applications
- `mark-applied`: records submission and schedules follow-ups (+5 and +12 days)
- `followups-due`: shows due follow-ups for a date
- `dashboard`: conversion and funnel metrics
- `build-interview-pack`: creates a Vapi-ready recruiter mock screen prompt pack
- `webapp`: browser UI for run-daily, review queue, artifact generation, and manual-apply status tracking

The Resume Tailor feature uses the curated LaTeX templates in `resume/latex/` and safe positioning context in `resume/`.
It produces LaTeX source, a generated PDF, and supporting text artifacts.
Resume/profile upload extracts keywords from the uploaded profile and stores the active profile in the configured GCS bucket so hosted runs and scheduled runs can use the same candidate context.

Firecrawl ingestion uses `map + structured scrape` to discover job-detail URLs and derive stable job IDs.
Tune volume with `FIRECRAWL_MAX_LINKS_PER_DOMAIN` in `.env`.
Set `JOB_AUTOMATION_DEBUG_SOURCES=true` to print source-level diagnostics (Apify/Firecrawl mapping and fetch errors).
The outreach export uses Firecrawl search/scrape to find public recruiting emails. It only stores discovered public contacts; sending remains manual.

## Directory Layout

- `job_automation/`: package code
- `docs/`: setup and schema docs + mock input
- `resume/`: ATS resume variants
- `tests/`: unit/integration tests for core scenarios
