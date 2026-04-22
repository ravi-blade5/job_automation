# Operating Workflow

## Daily Windows

Run at `08:30`, `13:30`, `20:30` local time (`Asia/Kolkata` by default):

```powershell
python -m job_automation.cli run-daily --tracker google_sheets
```

## Human-Approved Apply Flow

1. View queue:
```powershell
python -m job_automation.cli list-review-queue --tracker airtable
```
2. Build the manual-outreach export with public emails:
```powershell
python -m job_automation.cli build-outreach-leads --tracker airtable --refresh-contacts
```
This writes `job_automation/artifacts/outreach/manual_outreach_leads_<timestamp>.csv`
and `.json` with job, department, public contact email, source URL, and cover-letter focus.
3. Approve or reject:
```powershell
python -m job_automation.cli approve --application-id <id> --tracker airtable
python -m job_automation.cli reject --application-id <id> --tracker airtable
```
4. Generate artifacts (approved only):
```powershell
python -m job_automation.cli generate-artifacts --application-id <id> --tracker airtable
```
5. After manual portal submission, mark applied:
```powershell
python -m job_automation.cli mark-applied --application-id <id> --tracker airtable
```
6. Follow-up reminders:
```powershell
python -m job_automation.cli followups-due --tracker airtable
```
7. Build interview rehearsal pack:
```powershell
python -m job_automation.cli build-interview-pack --application-id <id> --tracker airtable
```

## Weekly Review

```powershell
python -m job_automation.cli dashboard --tracker airtable
```

Replace `airtable` with `google_sheets` if using Sheets as backend.

Track:

- Applications/week
- Interview rate
- Offer rate
- Source-wise conversion
- Median response time
