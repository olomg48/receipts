# Receipt Tracker API

The API is a Python 3.12 FastAPI service. Its container exposes:

- `GET /health/live` for Kubernetes liveness probes.
- `GET /health/ready` for readiness probes; this checks PostgreSQL and the configured Garage bucket.
- `POST /receipts` and `GET /receipts` for receipt upload and history.
- `GET /receipts/{receipt_id}` for receipt details and extracted product lines.
- `GET /analytics` for spending summaries across the single-owner app.
- Product review endpoints under `/admin/`.
- `GET /docs` for the interactive API documentation.

## Runtime configuration

Set `DATABASE_URL` at runtime to a SQLAlchemy PostgreSQL URL, for example:

```text
postgresql+psycopg://user:password@db.example.net:5432/receipts?sslmode=require
```

Set these variables for the API, worker, or both as indicated:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | External PostgreSQL connection string |
| `S3_ENDPOINT_URL` | Yes | Garage S3 API endpoint, for example `https://garage.example.net` |
| `S3_ACCESS_KEY_ID` | Yes | Private bucket access key |
| `S3_SECRET_ACCESS_KEY` | Yes | Private bucket secret key |
| `S3_BUCKET` | Yes | Existing private Garage bucket for receipt files and processing artifacts |
| `S3_REGION` | No | S3 signing region; defaults to `garage` |
| `PUBLIC_APP_ORIGIN` | Yes | Exact browser origin, e.g. `http://receipts.local`, used to reject cross-origin browser writes |
| `SINGLE_USER_EMAIL` | No | Email label for the internal owner row; defaults to `owner@local` |
| `MISTRAL_API_KEY` | Yes for worker | Mistral API key shared by OCR and LLM calls |
| `MISTRAL_OCR_MODEL` | No | OCR model; defaults to `mistral-ocr-latest` |
| `MISTRAL_LLM_MODEL` | No | JSON extraction model; defaults to `mistral-small-latest` |

Provision the Garage bucket and app-specific S3 credentials through your infrastructure/bootstrap process. The API and worker use Garage's S3-compatible API; they do not need the Garage admin token and do not create buckets. Configure the generated key with access only to the required private bucket. Never expose these credentials to the frontend or commit them to Git.

Uploads are limited to 10 MiB. The first supported combinations are Biedronka PDF and Lidl PNG. The API stores originals under `receipts/<receipt-id>/original.<extension>`, and the worker stores OCR Markdown and validated-output JSON alongside them. PostgreSQL stores the object keys and structured receipt/product data.

The app has no application-level login or user-level data separation. Anyone who can reach it can view receipts, upload files, and use product review. Restrict network access to trusted devices using your firewall, VPN, or cluster/network policy; `PUBLIC_APP_ORIGIN` is only a cross-origin browser-write safeguard, not authentication.

Run the API as the container's default command. Run the same image as a separate worker process with `python -m app.worker`; only the worker needs the Mistral API key. Keep secrets in the runtime secret manager.

The readiness endpoint returns `503` until both PostgreSQL and the configured Garage bucket are reachable using the app-specific S3 credentials. The worker also verifies bucket access before starting its processing loop.

`GET /admin/product-candidates` lists pending codes, `GET /admin/products` lists canonical codes, and `POST /admin/product-candidates/{candidate_id}/resolve` accepts a code, edits it into a canonical code, or maps it to an existing product. Resolving a code updates its receipt items and completes receipts with no remaining pending codes. These endpoints are not authenticated; restrict network access accordingly.

The analytics endpoint includes completed receipts only. All-time and 12-month totals remain separated by currency; product summaries cover the shared receipt history.

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
