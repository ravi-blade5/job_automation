FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JOB_AUTOMATION_TRACKER=google_sheets \
    JOB_AUTOMATION_DATA_DIR=/tmp/job_automation/data \
    JOB_AUTOMATION_ARTIFACTS_DIR=/tmp/job_automation/artifacts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "python -m job_automation.webapp --host 0.0.0.0 --port ${PORT:-8080} --tracker ${JOB_AUTOMATION_TRACKER:-google_sheets}"]
