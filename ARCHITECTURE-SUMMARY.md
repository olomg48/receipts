# Receipt Tracker — Architecture Summary

*Working document for review; not an implementation approval.*

## First-version topology

```text
Browser
  └─ Frontend ── HTTPS ──> Python API ──> External PostgreSQL SaaS
                                 │              ├─ users, receipts, items,
                                 │              │  products, review candidates
                                 │              └─ processing job queue
                                 ├─ private PDFs and processing artifacts in MinIO/S3
                                 ├─ Mistral OCR API (PDF/PNG → Markdown)
                                 └─ Mistral LLM API (Markdown → validated JSON)

k3s on one server (16 GB RAM, 4 Intel i5 cores)
  ├─ Frontend and Python API
  ├─ Python processing worker(s)
  ├─ Metabase: self-hosted BI
  └─ Existing Argo CD and monitoring
```

The application backend is planned in Python with FastAPI; the frontend is React and TypeScript. The first frontend slice has upload and product-review screens, but receipt upload, account sign-in, and review actions still require API implementation.

The app supports separate user accounts. Receipts are private to the account that uploaded them; the API must enforce ownership on every read and write. Google sign-in with invite-only access remains the proposed initial identity approach. PostgreSQL is hosted externally as a SaaS; it is not deployed on the k3s server.

## Receipt ingestion and processing

- Accept Biedronka PDF receipts and Lidl PNG receipts. Keep the upload pipeline extensible for other image/PDF variants.
- Save uploads in a private MinIO/S3 bucket and enqueue a processing job in PostgreSQL. Jobs track status, attempts, stage, and errors so the UI can report progress and failures.
- A Python worker sends the receipt file to the Mistral OCR API and receives Markdown. It then sends the extracted text to a Mistral LLM API to produce structured receipt JSON. Validate that JSON against an explicit schema before writing receipt data to the database.
- Do not run local OCR on the k3s server; both AI processing steps use the Mistral API and the same API key.
- The worker should retry transient failures safely, avoid duplicate receipt items on retries, and expose parse failures for correction rather than silently accepting malformed output.
- Biedronka JSON receipt ingestion is a later extension. No representative JSON samples are available yet, so the first version should focus on PDF/PNG and avoid assuming the future JSON schema.

## Product catalog and admin review

The admin/review interface can initially be a protected section of the existing frontend, backed by authorized API endpoints. It does not need to be a separate microservice. Only designated administrators should be able to resolve product-code candidates.

Products are identified only by short codes; there is no separate full name or display name. Keep the raw product code extracted from each receipt separate from the canonical product catalog. When an unrecognized code appears, create or find a deduplicated pending candidate and show it in the admin queue. For example, `LechHvdrFree` could be reviewed and mapped to the accepted canonical product code `LechHydrFree`.

For each pending candidate, an administrator can:

1. Accept the extracted code as a new canonical product code.
2. Edit the code and create an accepted canonical product with that code.
3. Map the candidate/observed code to an existing canonical product.

Record the decision as a reusable code mapping, so later receipts with the same misspelling resolve automatically rather than creating another pending product. Preserve the original receipt code for traceability. Pending codes should not be treated as confirmed catalog products in reports; the UI should make unreviewed receipt items visible.

The initial schema separates canonical `products` (with a `code`) from reusable `product_code_candidates` (with the observed code). A candidate has a unique normalized code, a `pending` or `resolved` status, and (once resolved) a link to the canonical product plus the resolution type. Receipt items retain their raw codes and may link to both the candidate and canonical product. This avoids overwriting the original spelling when an administrator corrects or maps it.

## Authentication, privacy, and third-party APIs

- Use Google sign-in without requesting access to Gmail. Keep invite-only registration as the initial access model.
- The API must enforce account and admin authorization on every request; do not trust user IDs or product decisions supplied by the browser.
- Treat receipt images, extracted text, and purchase details as sensitive. Sending files/text to Mistral and an LLM provider means those providers process the data. Before implementation, review their retention, training, region, and data-processing terms and choose providers/settings appropriate for the app's users.
- Keep OAuth credentials, PostgreSQL credentials, session-signing secrets, and OCR/LLM API keys out of source control and frontend bundles. Store them as runtime secrets; encrypted GitOps secrets need a decryption key kept outside the repository.
- Use TLS for PostgreSQL and API connections; use a least-privilege application database role. Keep uploaded files private, define retention/deletion behavior, and encrypt off-server backups.
- Avoid logging receipt contents, extracted text, API keys, access tokens, or unnecessary personal information.

## Database, jobs, and reporting

PostgreSQL stores accounts, receipts, receipt items, discounts, canonical products, observed codes/aliases, review decisions, and processing jobs. `receipt_jobs` is a small durable work queue, not a separate service: after saving an uploaded receipt, the API inserts a pending job that points to that receipt. The worker claims a ready job in a short transaction (for example `FOR UPDATE SKIP LOCKED`), marks it `processing` with a time-limited lock, commits, then performs OCR and LLM API calls outside the transaction. It records the current stage and marks the job `done`, or records an error and schedules a retry by updating `available_at`; `attempts` limits repeated failures. If the worker crashes, the lock expires and the job can be reclaimed. The receipt's own `status` is what the frontend displays, while the job status/stage helps operate the background processing. This keeps uploads responsive and allows transient provider/network failures to be retried without losing queued work.

Metabase can connect to PostgreSQL using a read-only account. Keep it private behind authenticated access. Signed embedding can show charts in the app, but embedding and client-side filters are not by themselves row-level authorization. Decide whether dashboards are shared across users or isolated per user before exposing them; start with shared/admin-only reporting if that matches the privacy requirements.

## Resource and operational constraints

The 16 GB / 4-core server also runs k3s, Argo CD, monitoring, the app, and Metabase. External OCR avoids local OCR CPU/memory load, but outbound API calls add latency, cost, rate limits, and provider availability as dependencies. Start with one worker and bounded concurrency; set resource requests/limits and monitor memory, CPU, disk, queue age, failed jobs, and API errors. Persistent file storage on one server is not highly available; keep tested backups off-server.

## Open decisions and assumptions

1. **Samples and locale:** Obtain representative Lidl PNGs and Biedronka PDFs, including misspellings and discounts. Confirm the receipt language/locale and how it appears in the OCR output.
2. **LLM provider:** Select the provider/model, data-retention settings, and acceptable cost. Determine whether it can return schema-constrained JSON; still validate all output server-side.
3. **Product review permissions:** Identify which account(s) should have administrator privileges. Decide whether every new spelling should be reviewed or whether confident/known aliases may resolve automatically.
4. **Dashboard visibility:** Decide whether dashboards are shared across users or per-user before embedding.
5. **File retention and storage:** Confirm how long originals are retained, whether local k3s persistent storage is acceptable, and where encrypted backups will live.
6. **External PostgreSQL SaaS:** Confirm provider, TLS/network restrictions, backup/restore expectations, and data region.
7. **Cluster capacity:** Confirm available disk, current monitoring/Argo CD resource use, and ingress/TLS setup.

## Phased implementation outline

1. **Validate samples and providers:** Inspect real receipt files and OCR Markdown; choose the LLM API and review external data handling terms.
2. **Foundation:** Configure ingress/TLS, runtime secrets, private file storage, external PostgreSQL access, and backup/monitoring checks.
3. **Identity and schema:** Implement Google sign-in/invitations and schema for receipts, receipt items/discounts, canonical products, aliases/review candidates, and processing jobs.
4. **Ingestion pipeline:** Add PDF/PNG upload, Mistral OCR, LLM structured extraction, schema validation, retries/idempotency, and visible processing errors.
5. **Product review:** Add an admin-only candidate queue to accept, edit, or map observed product codes; persist mappings for future receipts.
6. **User interface and BI:** Build upload/status/history screens, then add private Metabase access and embedding only after dashboard visibility is settled.
7. **Validate and operate:** Test representative receipts, misspelling resolution, authorization boundaries, provider failures, restore procedures, and resource limits. Add Biedronka JSON ingestion once real examples and their schema are available.
