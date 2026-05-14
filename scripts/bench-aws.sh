#!/usr/bin/env bash
# scripts/bench-aws.sh — provision Wake on AWS, run k6 benchmark, tear down.
#
# Usage: ./scripts/bench-aws.sh [VERSION_TAG]
#
# Requires: terraform, helm, kubectl, k6, aws CLI configured.

set -euo pipefail

VERSION="${1:-latest}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF="$ROOT/terraform/aws"
TS=$(date +%Y%m%d_%H%M%S)
OUT="$ROOT/docs/sbom/bench-aws-$TS"
mkdir -p "$OUT"

echo "=== Wake AWS bench [$VERSION] ==="

cd "$TF"

# Provision
export TF_VAR_backup_s3_bucket="wake-bench-$(uuidgen | tr A-Z a-z | head -c 8)"
terraform init -upgrade
terraform apply -auto-approve

# Install Wake
KUBECONFIG_CMD=$(terraform output -raw kubeconfig_cmd)
eval "$KUBECONFIG_CMD"

helm install wake "$ROOT/deploy/helm/wake" \
  --set auth.apiKey="$(openssl rand -hex 32)" \
  --set auth.oauthStateSecret="$(openssl rand -hex 32)" \
  --set api.replicas=3 \
  --set worker.replicas=5 \
  --set postgres.external.url="$(terraform output -raw postgres_endpoint)" \
  --wait --timeout 10m

# Run k6 benchmark
BASE_URL=$(kubectl get svc wake-api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
export WAKE_API_URL="http://$BASE_URL"
export WAKE_API_KEY=$(kubectl get secret wake-api-key -o jsonpath='{.data.api_key}' | base64 -d)

k6 run --out json="$OUT/k6-results.json" "$ROOT/tests/load/k6/wake-api.js"

# Tear down
helm uninstall wake
terraform destroy -auto-approve

echo "=== Done. Results: $OUT/ ==="
