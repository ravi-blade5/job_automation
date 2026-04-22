# Airtable Schema (Source of Truth)

Create these tables in one base:

1. `Jobs`
2. `FitScores`
3. `Applications`
4. `Companies`
5. `Contacts`
6. `Documents`
7. `ActivityLog`

## Jobs

- `job_id` (single line text, unique key)
- `source` (single select: linkedin, company_site, naukri, other, mock, apify)
- `title_raw` (single line text)
- `company` (single line text)
- `location` (single line text)
- `remote_type` (single select: onsite, hybrid, remote, unknown)
- `job_url` (url)
- `description_text` (long text)
- `date_posted` (date)
- `scraped_at` (date+time)

## FitScores

- `fit_id` (single line text, unique key, format: `job_id::role_track`)
- `job_id` (single line text)
- `role_track` (single select: ai_pm, genai_lead)
- `fit_score` (number)
- `must_have_match_pct` (number)
- `domain_match_pct` (number)
- `seniority_match` (single select: high, medium, low)
- `decision` (single select: must_apply, good_fit, low_fit)
- `reason_codes` (long text; JSON array string)

## Applications

- `application_id` (single line text, unique key)
- `job_id` (single line text)
- `status` (single select: new, screening, applied, interview, offer, rejected, closed)
- `resume_variant` (single select: A, B)
- `cover_note_version` (single line text)
- `owner_action` (single select: approve, hold, reject)
- `applied_on` (date)
- `next_followup_on` (date)
- `role_track` (single select: ai_pm, genai_lead)
- `decision` (single select: must_apply, good_fit, low_fit)
- `fit_score` (number)
- `followup_dates` (long text; JSON array string)
- `documents` (long text; JSON object string)
- `created_at` (date+time)
- `updated_at` (date+time)

## Companies

- `company` (single line text, unique key)
- `funding_signal` (single line text)
- `business_direction` (long text)
- `ai_maturity` (single line text)
- `enriched_at` (date+time)

## Contacts

- `contact_id` (single line text)
- `job_id` (single line text)
- `company` (single line text)
- `name` (single line text)
- `role` (single line text)
- `department` (single line text)
- `channel` (single select: linkedin, email, referral)
- `contact_value` (single line text)
- `source_url` (url or text)
- `notes` (long text)
- `discovered_at` (date+time)

## Documents

- `document_id` (single line text)
- `application_id` (single line text)
- `document_type` (single select: resume_variant, resume_summary, cover_note, referral_message)
- `path_or_url` (url or text)
- `created_at` (date+time)

## ActivityLog

- `activity_id` (single line text)
- `entity_type` (single select: pipeline, job, fit_score, application, followup, document)
- `entity_id` (single line text)
- `event` (single line text)
- `event_at` (date+time)
- `details` (long text)
