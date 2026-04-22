# Setup Steps

1. Copy env template:
```powershell
Copy-Item .\job_automation\.env.example .\job_automation\.env
```

2. Fill credentials in `.env`:
- `AIRTABLE_API_TOKEN`, `AIRTABLE_BASE_ID`
- `APIFY_API_TOKEN`, `APIFY_DATASET_IDS`
- `FIRECRAWL_API_KEY` for public-contact discovery
- `FIRECRAWL_CAREER_URLS` only if you also want company-site job ingestion
- `GOOGLE_AI_STUDIO_API_KEY`
- `PERPLEXITY_API_KEY`

3. Create Airtable tables and fields from `docs/airtable_schema.md`.

4. Dry-run with local JSON tracker first:
```powershell
python -m job_automation.cli run-daily --tracker json
python -m job_automation.cli build-outreach-leads --tracker json --refresh-contacts
```

5. Switch to Airtable:
```powershell
python -m job_automation.cli run-daily --tracker airtable
python -m job_automation.cli build-outreach-leads --tracker airtable --refresh-contacts
```

6. Or use Google Sheets:
```powershell
python -m job_automation.cli run-daily --tracker google_sheets
python -m job_automation.cli build-outreach-leads --tracker google_sheets --refresh-contacts
```
Follow: `docs/google_sheets_setup.md`

The outreach export produces timestamped CSV/JSON files in `job_automation/artifacts/outreach/`.
Those files are the best review surface if you want to email relevant contacts manually rather than auto-apply.
