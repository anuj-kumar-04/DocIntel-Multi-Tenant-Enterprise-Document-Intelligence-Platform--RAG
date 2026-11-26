# Deploying DocIntel to Google Cloud (GCE + Production Hardening)

This guide deploys **DocIntel** securely onto a **Google Cloud Compute Engine (VM)** using [`docker-compose.prod.yml`](../../docker-compose.prod.yml) and Nginx reverse proxy.

---

## 1. Create a Hardened Google Cloud VM

In **Google Cloud Console → Compute Engine → VM Instances**:
1. **Machine Type:** `e2-standard-2` (2 vCPU, **8 GB RAM** recommended for `pgvector` HNSW + local `bge-small` / `bge-reranker` models + Next.js).
2. **OS & Disk:** Ubuntu 24.04 LTS, **50 GB SSD** (`pd-balanced` or `pd-ssd`).
3. **Firewall:** Check **Allow HTTP traffic** and **Allow HTTPS traffic**.
4. **Static IP & DNS (Recommended):** Reserve a Static External IP in **VPC Network → IP Addresses** and point your domain's `A` record to it.

> [!IMPORTANT]
> **Keep internal ports closed in GCP Firewall:** Do **NOT** open `5432` (PostgreSQL), `6379` (Redis), `8000` (FastAPI), `3000` (Next.js), or `9000` (MinIO/SeaweedFS). Only ports `80`, `443`, and `22` (SSH restricted to your IP or Identity-Aware Proxy) should be reachable.

---

## 2. Upload the Project to Your GCP Server

### Option A: Clone from GitHub (Recommended)
SSH into your GCP VM:
```bash
gcloud compute ssh docintel-prod --zone=us-central1-a
```
Clone the repository:
```bash
git clone <YOUR_GITHUB_REPO_URL> docintel
cd docintel
```

### Option B: Direct SCP from Windows (No Git Required)
From Windows PowerShell in this project directory:
```powershell
gcloud compute scp --recurse --exclude="node_modules|.venv|.git|.pytest_cache" . <USER>@<VM_NAME>:~/docintel --zone=<ZONE>
```

---

## 3. Run the Turnkey Production Deploy Script

On your GCP server inside `~/docintel`:

### With a Domain + Automatic Let's Encrypt HTTPS:
```bash
chmod +x deploy/gcp/deploy.sh
./deploy/gcp/deploy.sh docintel.yourdomain.com admin@yourdomain.com
```

### Or IP-Only Testing Mode (HTTP on Port 80):
```bash
chmod +x deploy/gcp/deploy.sh
./deploy/gcp/deploy.sh
```

The script automatically:
* Installs Docker & Docker Compose (if missing)
* Enables UFW host firewall (`22`, `80`, `443`)
* Generates cryptographic `SECRET_KEY`, database, Redis, and S3 credentials into `.env` (`chmod 600`)
* Issues a TLS certificate via Certbot (when domain + email are supplied)
* Builds and starts `db`, `redis`, `minio`, `api` (Gunicorn 4 workers), `worker`, `frontend`, and `nginx`

---

## 4. Optional GCP Native Upgrades

* **Google Cloud Storage (GCS) instead of local SeaweedFS:** Generate S3 HMAC keys in **Cloud Storage → Settings → Interoperability** and set `S3_ENDPOINT_URL=https://storage.googleapis.com` in `.env`.
* **Native PostgreSQL Row-Level Security (RLS):** Apply [`infra/postgres/rls_policies.sql`](../../infra/postgres/rls_policies.sql) when connecting with a non-superuser application database role.
* **Verify Deployment:**
  ```bash
  docker compose -f docker-compose.prod.yml ps
  curl -i http://localhost/health
  ```
