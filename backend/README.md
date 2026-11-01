# Receipt Tracker API

The API is a Python 3.12 FastAPI service. Its container exposes:

- `GET /health/live` for Kubernetes liveness probes.
- `GET /health/ready` for readiness probes; this checks PostgreSQL connectivity.
- `GET /docs` for the interactive API documentation.

Set `DATABASE_URL` at runtime to a SQLAlchemy PostgreSQL URL, for example:

```text
postgresql+psycopg://user:password@db.example.net:5432/receipts?sslmode=require
```

Do not commit real database credentials. Supply them through the deployment's secret-management mechanism.

## Database migrations

Apply migrations as a one-shot deployment task, not automatically when the API starts:

```text
alembic upgrade head
```

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
