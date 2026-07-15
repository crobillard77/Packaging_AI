# Packaging AI API — runbook

See the full plan in [`Project_API.md`](Project_API.md). This file covers **how to run** the implemented API.

## Install

```powershell
cd D:\DEV\Projects\Packaging_AI
.\.venv\Scripts\Activate.ps1
pip install -e ".[api]"
# or: pip install fastapi "uvicorn[standard]" pyodbc
```

Also install **ODBC Driver 18 for SQL Server** on the API host when using SQL job store.

## Environment

| Variable | Purpose |
|----------|---------|
| `PACKAGING_AI_API_KEYS` | Comma-separated API keys (required for job routes) |
| `PACKAGING_AI_SQL_CONNECTION` | ODBC connection string (SQL Auth) |
| `PACKAGING_AI_JOB_STORE` | `sql` (default) or `memory` (local smoke tests) |
| `PACKAGING_AI_API_HOST` | Default `127.0.0.1` |
| `PACKAGING_AI_API_PORT` | Default `8000` |

Example SQL connection string:

```text
Driver={ODBC Driver 18 for SQL Server};Server=WIN-GPHHMLE0KE0,1433;Database=PackagingAI;Uid=packaging_ai;Pwd=***;Encrypt=yes;TrustServerCertificate=yes;
```

Create the database (optional — API can create tables if the login can):

```powershell
# Run API/schema.sql in SSMS, or let ensure_schema create tables in an existing DB.
```

## Local run (memory store smoke test)

```powershell
$env:PACKAGING_AI_API_KEYS = "dev-key-change-me"
$env:PACKAGING_AI_JOB_STORE = "memory"
python -m packaging_ai.api
```

```powershell
curl http://127.0.0.1:8000/health
curl -H "X-API-Key: dev-key-change-me" -H "Content-Type: application/json" `
  -d "{\"folder_path\":\"D:\\absolute\\path\\to\\installers\",\"auto_confirm\":true}" `
  http://127.0.0.1:8000/v1/jobs
```

## Production (SQL + IIS)

1. Set `PACKAGING_AI_JOB_STORE=sql` and `PACKAGING_AI_SQL_CONNECTION`.
2. Run uvicorn as a Windows Service (NSSM) on `127.0.0.1:8000`.
3. IIS ARR reverse-proxy HTTPS → `http://127.0.0.1:8000` (see `Project_API.md` §6).
4. Do not expose port 8000 publicly.

Console script (after install):

```powershell
packaging-ai-api
```

## Clarification flow

1. `POST /v1/jobs`
2. Poll `GET /v1/jobs/{id}` until `awaiting_clarification` or terminal
3. `POST /v1/jobs/{id}/clarify` with `meta` / `uninstall_paste` / `confirm` / `abort`
4. Poll until `succeeded`; then `GET /v1/jobs/{id}/artifacts`
