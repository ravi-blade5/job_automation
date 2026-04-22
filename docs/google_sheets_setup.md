# Google Sheets Tracker Setup

## 1. Create Spreadsheet

Create a spreadsheet for this system and copy its ID from URL:

`https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`

## 2. Enable APIs in Google Cloud

Enable these APIs in your project:

- Google Sheets API
- Google Drive API

## 3. Create Service Account

1. Create a service account in Google Cloud IAM.
2. Create and download a JSON key for that service account.
3. Save the file locally, for example:

`G:\Antigravity\ADB_HCL\job_automation\google_service_account.json`

## 4. Share Spreadsheet with Service Account

Open the spreadsheet and share with the service account email from JSON key
(`...@...iam.gserviceaccount.com`) with `Editor` access.

## 5. Configure `.env`

Set:

```env
JOB_AUTOMATION_TRACKER=google_sheets
GOOGLE_SHEETS_SPREADSHEET_ID=<SPREADSHEET_ID>
GOOGLE_SHEETS_CREDENTIALS_FILE=./job_automation/google_service_account.json
GOOGLE_SHEETS_SHEET_JOBS=Jobs
GOOGLE_SHEETS_SHEET_FIT_SCORES=FitScores
GOOGLE_SHEETS_SHEET_APPLICATIONS=Applications
GOOGLE_SHEETS_SHEET_COMPANIES=Companies
GOOGLE_SHEETS_SHEET_CONTACTS=Contacts
GOOGLE_SHEETS_SHEET_DOCUMENTS=Documents
GOOGLE_SHEETS_SHEET_ACTIVITY_LOG=ActivityLog
```

## 6. Install Dependencies

```powershell
pip install -r job_automation/requirements.txt
```

## 7. Run

```powershell
python -m job_automation.cli run-daily --tracker google_sheets
python -m job_automation.cli list-review-queue --tracker google_sheets
python -m job_automation.cli build-outreach-leads --tracker google_sheets --refresh-contacts
```

The `Contacts` sheet is auto-managed by the CLI and now stores job-linked public outreach contacts, including `job_id`, `department`, `source_url`, and `discovered_at`.
