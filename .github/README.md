# Manual publish workflow

Run **Publish and deploy** from GitHub Actions and choose `dev` or `prod`. The workflow tests the backend, builds and pushes both application images to GHCR using the application commit SHA as the tag, then updates that environment's image tags in `olomg48/receipts_infra`. For `dev`, it also mirrors PostgreSQL 17 Alpine to `ghcr.io/olomg48/receipt-tracker-postgres:17-alpine`.

Add an Actions secret named `INFRA_REPO_TOKEN` with Contents read/write access to the infrastructure repository. The workflow's `GITHUB_TOKEN` needs package write permission. GHCR packages must be public for unauthenticated k3s pulls, or the namespace must have an image-pull Secret.

The PostgreSQL image mirror uses the upstream Docker Official Image as its base during the build. The dev cluster itself pulls the mirrored GHCR image.

Argo CD deploys the change after syncing the selected overlay. The workflow does not contact the cluster directly. It does not run database migrations.
