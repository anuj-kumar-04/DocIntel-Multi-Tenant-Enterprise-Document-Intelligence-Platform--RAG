#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# DocIntel Automated Deployment Script for Google Cloud Compute Engine (Ubuntu)
# ==============================================================================
# Usage:
#   ./deploy/gcp/deploy.sh [optional-domain.com] [optional-admin@domain.com]
# ==============================================================================

DOMAIN="${1:-}"
EMAIL="${2:-}"

echo "[1/6] Checking Docker & Docker Compose..."
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl git ufw openssl
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "Docker installed. Please log out and SSH back in, then re-run this script."
  exit 0
fi

echo "[2/6] Configuring UFW Host Firewall (SSH, HTTP, HTTPS only)..."
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow OpenSSH || true
  sudo ufw allow 80/tcp || true
  sudo ufw allow 443/tcp || true
  sudo ufw --force enable || true
fi

echo "[3/6] Verifying production .env configuration..."
if [ ! -f ".env" ]; then
  SECRET_KEY_VAL="$(openssl rand -hex 32)"
  DB_PASS="$(openssl rand -hex 24)"
  REDIS_PASS="$(openssl rand -hex 24)"
  S3_KEY="$(openssl rand -hex 12)"
  S3_SEC="$(openssl rand -hex 24)"

  if [ -n "$DOMAIN" ]; then
    PUBLIC_ORIGIN="https://${DOMAIN}"
  else
    EXT_IP="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || curl -s https://api.ipify.org || echo 'localhost')"
    PUBLIC_ORIGIN="http://${EXT_IP}"
  fi

  cp .env.prod.example .env
  sed -i "s|REPLACE_WITH_64_CHAR_HEX_FROM_OPENSSL_RAND_HEX_32|${SECRET_KEY_VAL}|g" .env
  sed -i "s|REPLACE_WITH_STRONG_DB_PASSWORD|${DB_PASS}|g" .env
  sed -i "s|REPLACE_WITH_STRONG_REDIS_PASSWORD|${REDIS_PASS}|g" .env
  sed -i "s|REPLACE_WITH_S3_ACCESS_KEY|${S3_KEY}|g" .env
  sed -i "s|REPLACE_WITH_S3_SECRET_KEY|${S3_SEC}|g" .env
  sed -i "s|https://your-domain.com|${PUBLIC_ORIGIN}|g" .env
  chmod 600 .env
  echo "[!] Created fresh .env with generated cryptographic keys for ${PUBLIC_ORIGIN}."
  echo "[!] Add your GROQ_API_KEY / GEMINI_API_KEY / LANGFUSE keys inside .env if needed."
else
  chmod 600 .env
fi

echo "[4/6] Configuring TLS / Nginx..."
if [ -n "$DOMAIN" ] && [ -n "$EMAIL" ]; then
  if ! command -v certbot >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y certbot
  fi
  docker compose -f docker-compose.prod.yml stop nginx 2>/dev/null || true
  sudo certbot certonly --standalone --non-interactive --agree-tos -m "$EMAIL" -d "$DOMAIN"
  sed "s|__DOMAIN__|${DOMAIN}|g" infra/nginx/nginx.ssl.conf.template > infra/nginx/nginx.conf
  echo "[OK] HTTPS configured for ${DOMAIN}."
fi

echo "[5/6] Building and starting hardened production containers..."
docker compose -f docker-compose.prod.yml --env-file .env up -d --build

echo "[6/6] Waiting for API health check..."
sleep 8
docker compose -f docker-compose.prod.yml ps
echo ""
echo "Deployment complete! Check health endpoint: curl -fsS http://localhost/health"
