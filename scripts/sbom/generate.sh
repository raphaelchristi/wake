#!/usr/bin/env bash
# scripts/sbom/generate.sh — orchestrates CycloneDX SBOM generation for Wake.
#
# Generates a SBOM per shipped artifact:
#   - wake (server)
#   - wake-frontend (dashboard)
#   - wake-ai-client (Python SDK)
#   - @wake-ai/client (TS SDK)
#
# Outputs to docs/sbom/*.cdx.json
#
# Usage: ./scripts/sbom/generate.sh [VERSION]
# Where VERSION (optional) is the release tag, used only in metadata.

set -euo pipefail

VERSION="${1:-$(git describe --tags --always)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/docs/sbom"
mkdir -p "$OUT"

echo "Generating SBOMs for Wake @ $VERSION"

# --- Server (Python) -----------------------------------------------------
if command -v cyclonedx-py >/dev/null 2>&1; then
  echo "→ Python (server)"
  cyclonedx-py environment \
    --output-file "$OUT/wake-python.cdx.json" || \
    echo "  WARN: server SBOM failed (continuing)"
else
  echo "SKIP: cyclonedx-py not installed (pip install cyclonedx-bom)"
fi

# --- Frontend (npm) ------------------------------------------------------
if command -v cyclonedx-npm >/dev/null 2>&1 && [ -d "$ROOT/frontend" ]; then
  echo "→ Frontend (npm)"
  ( cd "$ROOT/frontend" && cyclonedx-npm \
    --output-file "$OUT/wake-frontend.cdx.json" ) || \
    echo "  WARN: frontend SBOM failed"
else
  echo "SKIP: frontend SBOM (cyclonedx-npm missing)"
fi

# --- Python SDK ---------------------------------------------------------
if command -v cyclonedx-py >/dev/null 2>&1 && [ -d "$ROOT/sdks/python" ]; then
  echo "→ SDK Python"
  ( cd "$ROOT/sdks/python" && cyclonedx-py environment \
    --output-file "$OUT/wake-sdk-py.cdx.json" ) || \
    echo "  WARN: sdk-py SBOM failed"
fi

# --- TS SDK -------------------------------------------------------------
if command -v cyclonedx-npm >/dev/null 2>&1 && [ -d "$ROOT/sdks/typescript" ]; then
  echo "→ SDK TypeScript"
  ( cd "$ROOT/sdks/typescript" && cyclonedx-npm \
    --output-file "$OUT/wake-sdk-ts.cdx.json" ) || \
    echo "  WARN: sdk-ts SBOM failed"
fi

# --- Catalog (npm) ------------------------------------------------------
if command -v cyclonedx-npm >/dev/null 2>&1 && [ -d "$ROOT/catalog" ]; then
  echo "→ Catalog (npm)"
  ( cd "$ROOT/catalog" && cyclonedx-npm \
    --output-file "$OUT/wake-catalog.cdx.json" ) || \
    echo "  WARN: catalog SBOM failed"
fi

echo ""
echo "SBOMs generated in $OUT/"
ls -lh "$OUT/"
