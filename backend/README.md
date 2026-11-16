# Receipt Tracker API

The API is a Python 3.12 FastAPI service. Its container exposes:

- `GET /health/live` for Kubernetes liveness probes.
- `GET /health/ready` for readiness probes; this checks PostgreSQL connectivity.
- Google OAuth endpoints under `/auth/google/` and `/auth/me`.
- `POST /receipts` and `GET /receipts` for authenticated receipt upload and history.
- `GET /docs` for the interactive API documentation.

## Runtime configuration

Set `DATABASE_URL` at runtime to a SQLAlchemy PostgreSQL URL, for example:

```text
postgresql+psycopg://user:password@db.example.net:5432/receipts?sslmode=require
```

Set the following environment variables for the API and worker:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | External PostgreSQL connection string |
| `S3_ENDPOINT_URL` | Yes | MinIO/S3 endpoint, for example `https://minio.example.net:9000` |
| `S3_ACCESS_KEY_ID` | Yes | Private bucket access key |
| `S3_SECRET_ACCESS_KEY` | Yes | Private bucket secret key |
| `S3_BUCKET` | Yes | Existing private bucket for receipt files and processing artifacts |
| `S3_REGION` | No | S3 region; defaults to the SDK default |
| `SESSION_SECRET` | Yes | Long random key used to sign the login session cookie |
| `SESSION_COOKIE_SECURE` | Yes in production | Set to `true` when the app is served over HTTPS |
| `PUBLIC_APP_ORIGIN` | Yes | Exact browser origin, e.g. `https://receipts.example.net`, with no path or trailing slash |
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Yes | Exact registered callback URL, e.g. `https://receipts.example.net/api/auth/google/callback` |
| `INVITED_EMAILS` | Yes | Comma-separated allowlist of accounts permitted to sign in |
| `ADMIN_EMAILS` | No | Comma-separated accounts that receive the admin flag on first sign-in |
| `MISTRAL_API_KEY` | Yes for worker | Mistral API key shared by OCR and LLM calls |
| `MISTRAL_OCR_MODEL` | No | OCR model; defaults to `mistral-ocr-latest` |
| `MISTRAL_LLM_MODEL` | No | JSON extraction model; defaults to `mistral-small-latest` |

Create the S3 bucket and credentials through your infrastructure process. The application does not create buckets or make them public. Give the API and worker access only to the required private bucket. Never expose these secrets to the frontend or commit them to Git.

Uploads are limited to 10 MiB. The first supported combinations are Biedronka PDF and Lidl PNG. The API stores originals under `receipts/<receipt-id>/original.<extension>`, and the worker stores OCR Markdown and validated-output JSON alongside them. PostgreSQL stores the object keys and structured receipt/product data.

Google OAuth uses an invite-only email allowlist. Register the callback URL exactly as `GOOGLE_REDIRECT_URI`; the callback route is `/auth/google/callback` on the API and `/api/auth/google/callback` through the frontend Nginx proxy. Configure the same public origin in `PUBLIC_APP_ORIGIN`; cookie-authenticated upload and logout requests require it to match the browser's `Origin` header.

Run the API as the container's default command. Run the same image as a separate worker process with `python -m app.worker`; only the worker needs the Mistral API key. Keep secrets in the runtime secret manager.

## Database migrations

Apply migrations as a one-shot deployment task, not automatically when the API starts:

```text
alembic upgrade head
```

Revision `0002_processing_artifacts` adds object keys for the intermediate OCR and extraction results. Apply all migrations through `alembic upgrade head` before deploying the API and worker.

In Kubernetes, Argo CD can run a migration Job as a `PreSync` hook using the same image tag as the API release. The hook must finish successfully before Argo CD applies the updated application resources. Avoid having every API replica attempt migrations at startup.

## Local checks

Install the project and its test dependencies in a Python 3.12 environment, then run:

```text
pip install -e ".[test]"
pytest
```

Build the container from this directory:

```text
docker build -t receipt-tracker-backend:dev .
```
