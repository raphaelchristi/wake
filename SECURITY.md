# Security Policy

We take security seriously. This document covers supported versions, disclosure process, and supply-chain attestations.

## Supported versions

| Version | Supported |
|---|---|
| `v0.9.x` (current minor) | ✅ active |
| `v0.8.x` | ✅ security fixes only |
| `v0.7.x` | ⚠️ critical fixes only |
| `< v0.7` | ❌ unsupported |

## Reporting a vulnerability

**Do NOT open a public GitHub issue for security findings.**

Use one of:

1. **GitHub Security Advisory** (preferred):
   https://github.com/raphaelchristi/wake/security/advisories/new
2. **Email:** `security@wake-ai.dev`
3. **PGP-encrypted email:** fingerprint in `docs/SECURITY-DISCLOSURE.md`

### What to include

- Affected version(s) + commit SHA if possible
- Description of the issue + impact
- Reproducer (PoC) — minimal, no real exfiltrated data
- Suggested fix if you have one

### Response timeline

| Stage | SLA |
|---|---|
| Acknowledgement | < 48h |
| Initial assessment | < 5 business days |
| Fix in private branch | < 14 days for critical, 30 days for high, 90 days for medium |
| Public disclosure | After fix released + 7 days |

## Scope

**In scope:**

- API server (`src/wake/api/`) — auth bypass, RBAC bypass, tenant isolation breach
- Storage layer (`src/wake/store/`, `adapters/postgres-store/`) — SQL injection, data leak
- Sandbox runtime (`adapters/sandbox-runtime`) — escape, privilege escalation
- Vault adapter (`adapters/vault-infisical`) — token leakage, cross-tenant credential access
- Helm chart (`deploy/helm/wake`) — privilege escalation in PodSpec, secret exposure
- Dashboard (`frontend/`) — XSS, CSRF, header spoofing, info disclosure
- SDKs (`sdks/python`, `sdks/typescript`) — credential leakage, redirect-based attacks

**Out of scope:**

- Denial of service via raw resource exhaustion without bypass (use rate-limit + cost-budget)
- Issues in third-party dependencies (report upstream; we'll bump after disclosure)
- Self-XSS that requires the user to paste attacker-controlled content into their own browser console
- Local-only attacks requiring physical/admin access to the host running Wake

## Disclosure rewards

Wake is OSS-funded; we cannot offer bounties. We will:

- Credit you in the release notes (unless you prefer anonymity)
- Add you to `SECURITY.md` acknowledgements section after disclosure
- Provide a written reference letter on request

## Supply-chain attestations

Each release ships with:

- **SBOM** (CycloneDX 1.5 JSON) — `docs/sbom/wake-v<version>.cdx.json`
- **Container signatures** — cosign keyless via Sigstore Fulcio + Rekor
- **Build provenance** — SLSA Level 3 via GitHub Actions OIDC

Verify a signed image:

```bash
cosign verify ghcr.io/raphaelchristi/wake:v0.9.0 \
  --certificate-identity-regexp '^https://github.com/raphaelchristi/wake/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Check SBOM:

```bash
curl -sL https://github.com/raphaelchristi/wake/releases/download/v0.9.0/wake.cdx.json | \
  cyclonedx-cli validate --input-format json
```

## Hardening recommendations (operators)

When deploying Wake to production:

1. **Set `WAKE_AUTH_REQUIRED=true`** — fail-closed when API key not configured
2. **Set `WAKE_RBAC_ENABLED=true`** — per-route role enforcement (Phase 6)
3. **Use NetworkPolicy** to firewall `/metrics` endpoint (unauthenticated by Prom convention)
4. **Run Postgres with TLS** — `WAKE_DATABASE_URL=postgresql+ssl://...`
5. **Enable backup** (`backup.enabled=true` in Helm values, Phase 6 deliverable)
6. **Run `restore-drill.sh` weekly** in CI to validate RTO < 30min
7. **Pin container images by digest** — `image: ghcr.io/raphaelchristi/wake@sha256:...`
8. **Enable cosign verify** in your deployment pipeline (Kyverno, Connaisseur, Sigstore Policy Controller)
9. **Monitor `wake_errors_total{code}` Prom counter** — esp. `auth_required_not_configured`
10. **Set per-workspace cost-budget** (`agent.metadata.max_cost_usd`) to bound exposure

## Acknowledgements

Reporters of accepted findings will be listed here after fix release.

| Reporter | Finding | Release |
|---|---|---|
| Codex (internal adversarial review) | Vault tenant scope (Phase 6.1 CRITICAL #1) | `v0.6.1-fixes` |
| Codex (internal adversarial review) | SSE proxy header spoofing (Phase 6.1 HIGH #2) | `v0.6.1-fixes` |
| Codex (internal adversarial review) | Dispatcher tenant leak to default workspace (Phase 6.1 HIGH #3) | `v0.6.1-fixes` |
| Codex (internal adversarial review) | Restore drill production target risk (Phase 6.1 HIGH #4) | `v0.6.1-fixes` |
| Claude (inline review substitute) | 11 Phase 7 findings (3 HIGH + 5 MEDIUM + 3 LOW) | tracked in `phases/CODEX-REVIEW-PHASE-7.md` |
