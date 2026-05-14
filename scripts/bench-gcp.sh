#!/usr/bin/env bash
# scripts/bench-gcp.sh — provision Wake on GCP, run k6 benchmark, tear down.
#
# Usage: GCP_PROJECT_ID=my-project ./scripts/bench-gcp.sh [VERSION_TAG]
#
# Requires: terraform, helm, kubectl, k6, gcloud CLI auth'd.

set -euo pipefail

VERSION="${1:-latest}"
PROJECT_ID="${GCP_PROJECT_ID:?set GCP_PROJECT_ID}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF="$ROOT/terraform/gcp"
TS=$(date +%Y%m%d_%H%M%S)
OUT="$ROOT/docs/sbom/bench-gcp-$TS"
mkdir -p "$OUT"

echo "=== Wake GCP bench [$VERSION] project=$PROJECT_ID ==="

cd "$TF"

export TF_VAR_project_id="$PROJECT_ID"
export TF_VAR_backup_bucket="wake-bench-$(uuidgen | tr A-Z a-z | head -c 8)"
export TF_VAR_region="${GCP_REGION:-us-central1}"

terraform init -upgrade
terraform apply -auto-approve

# Configure kubectl
$(terraform output -raw kubeconfig_cmd)

helm install wake "$ROOT/deploy/helm/wake" \
  --set auth.apiKey="$(openssl rand -hex 32)" \
  --set auth.oauthStateSecret="$(openssl rand -hex 32)" \
  --set api.replicas=3 \
  --set worker.replicas=5 \
  --wait --timeout 10m

BASE_URL=$(kubectl get svc wake-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
export WAKE_API_URL="http://$BASE_URL"
export WAKE_API_KEY=$(kubectl get secret wake-api-key -o jsonpath='{.data.api_key}' | base64 -d)

k6 run --out json="$OUT/k6-results.json" "$ROOT/tests/load/k6/wake-api.js"

helm uninstall wake
terraform destroy -auto-approve

echo "=== Done. Results: $OUT/ ==="
