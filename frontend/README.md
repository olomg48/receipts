# Receipt Tracker Frontend

React + TypeScript frontend, built with Vite and served as static files by Nginx.

The current UI is a deployable first slice, not yet connected to receipt or product-review API endpoints. It supports selecting/dropping PDF and PNG files for the upload screen, but does not upload or persist them. The API indicator checks `GET /api/health/ready`.

Nginx proxies `/api/*` to the Kubernetes Service `receipt-api:8000` and removes the `/api/` prefix. Ensure the backend Service uses that name in the same namespace, or adjust `nginx.conf`. The resolver is set to the default k3s CoreDNS Service IP (`10.43.0.10`); update it if your cluster uses a different `--cluster-dns` address. DNS resolution happens at request time so the frontend can start even before the API Service exists. For example, `/api/health/ready` is forwarded to the backend's `/health/ready`.

## Local development

```text
npm ci
npm run dev
```

The Vite development server serves the UI. API requests need a local proxy configuration or a same-origin API server.

## Build and container

```text
npm ci
npm run build
docker build -t receipt-tracker-frontend:dev .
```
