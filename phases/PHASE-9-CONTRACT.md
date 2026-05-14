# Phase 9 Execution Contract — Ecosystem & Trust

> Tier 3 gaps (#13–#15): adapter catalog · supply chain · operational docs.
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial A → B → C.
>
> **Baseline:** `v0.8.0-dx` (Phase 8 done). SDKs + eval + edit-replay disponíveis.

---

## Decisões locked

| Decisão | Valor | Justificativa |
|---|---|---|
| Adapter catalog | Static site Next.js em `catalog/` dir (não rota do dashboard) | Mantém dashboard simples; catalog pode hospedar em Vercel/Cloudflare separadamente |
| Badge generator | CLI `wake adapter badge --name=<x>` produz SVG + Markdown snippet | Self-serve pros adapter authors |
| Conformance claim | GitHub Action template que adapter author copia + roda conformance suite + uploads artifact | Trust via reproducible evidence |
| SBOM format | **CycloneDX 1.5 JSON** | Padrão US gov, Kubernetes, npm |
| SBOM generation | `cyclonedx-bom` (Python) + `@cyclonedx/cyclonedx-npm` (TS) | Já maduras; CI step |
| Dep scanning | **`grype`** (vuln DB) + **`trivy`** (containers) em CI | Cobertura complementar |
| Container signing | **`cosign`** + sigstore keyless (OIDC GitHub) | Padrão CNCF; sem long-lived keys |
| Reproducible build | **Nix flake** (`flake.nix`) | Determinism garantida |
| Terraform refs | `terraform/aws/` + `terraform/gcp/` com VPC + EKS/GKE + Postgres + S3 + secrets | Reference implementations, não modules publicadas |
| SECURITY.md | Standard disclosure policy + supported versions + report email | OWASP/NIST aligned |
| Benchmark publish | Estende Phase 7 `BENCHMARKS.md` com results AWS + GCP comparison | Reproducibility via Terraform |

---

## Pre-existing — não modificar

- Phase 6-8 entregáveis (RBAC, ops hardening, SDKs, eval, replay)
- `src/wake/` core — additive only
- Adapter packages — adicionar `conformance_results.json` mas não muda código

---

## Divisão de slices

| Agent | Worktree | Branch | Owns |
|---|---|---|---|
| `eco-catalog` | `wake-wt-eco-catalog` | `agent/eco-catalog` | Public adapter catalog site + conformance badge generator + claim workflow |
| `eco-supply` | `wake-wt-eco-supply` | `agent/eco-supply` | SBOM (CycloneDX) + grype/trivy CI + cosign signing + SECURITY.md + Nix flake |
| `eco-refs` | `wake-wt-eco-refs` | `agent/eco-refs` | AWS Terraform + GCP Terraform + benchmark results extended + reference architecture docs |

---

## Files ownership

### `eco-catalog` owns

```
# Catalog site (Next.js standalone)
catalog/                                                         NEW DIR
catalog/package.json                                             NEW (catalog-site 0.1.0)
catalog/next.config.mjs                                          NEW (static export)
catalog/src/app/page.tsx                                         NEW (catalog index)
catalog/src/app/adapters/[slug]/page.tsx                         NEW (detail)
catalog/src/lib/registry.ts                                      NEW (load adapters.json)
catalog/data/adapters.json                                       NEW (initial: claude-sdk, langgraph, crewai, pydantic-ai)
catalog/README.md                                                NEW

# Badge generator
src/wake/cli/badge.py                                            NEW (wake adapter badge --name=X --score=10 --output=badge.svg)
src/wake/badges/                                                 NEW DIR (SVG templates)
src/wake/badges/conformance.svg.j2                               NEW

# Claim workflow template
templates/adapter-claim/                                         NEW DIR
templates/adapter-claim/.github/workflows/conformance-claim.yml  NEW (run conformance + upload + open PR)
templates/adapter-claim/README.md                                NEW

# Tests
tests/unit/test_badge_generator.py                               NEW

# Docs
docs/ADAPTER-CATALOG.md                                          NEW (≥300 linhas — how to claim + criteria + listing process)
catalog/README.md                                                NEW (≥150 linhas — local dev + deploy)
```

### `eco-supply` owns

```
# SBOM
.github/workflows/sbom.yml                                       NEW (generate CycloneDX on tag)
scripts/sbom/generate.sh                                         NEW (orchestrates cyclonedx-bom for Python + npm)
docs/sbom/.gitkeep                                               NEW (output dir)

# Dep scanning
.github/workflows/security-scan.yml                              NEW (grype + trivy weekly + on PR)
.grype.yaml                                                      NEW (config + ignore false positives)
.trivyignore                                                     NEW

# Cosign
.github/workflows/sign-images.yml                                NEW (cosign keyless on tag + verify)
deploy/cosign/cosign.pub                                         NEW (placeholder; key gerada via OIDC)

# SECURITY.md
SECURITY.md                                                      NEW (≥150 linhas)
docs/SECURITY-DISCLOSURE.md                                      NEW (≥200 linhas)

# Nix flake
flake.nix                                                        NEW (Python + Node + Helm + k6 + cosign)
flake.lock                                                       NEW (committed)
.envrc                                                           NEW (direnv: use flake)
docs/NIX-DEVSHELL.md                                             NEW (≥150 linhas)

# Tests
.github/workflows/security-scan-test.yml                         NEW (validates SBOM + scan outputs in PR)
```

### `eco-refs` owns

```
# AWS Terraform
terraform/aws/                                                   NEW DIR
terraform/aws/main.tf                                            NEW (VPC + EKS + RDS Postgres + S3 + IAM)
terraform/aws/variables.tf                                       NEW
terraform/aws/outputs.tf                                         NEW
terraform/aws/versions.tf                                        NEW
terraform/aws/modules/eks/                                       NEW (Helm install Wake)
terraform/aws/modules/postgres/                                  NEW
terraform/aws/README.md                                          NEW (≥400 linhas — deploy guide)
terraform/aws/examples/                                          NEW (smallest + production presets)

# GCP Terraform
terraform/gcp/                                                   NEW DIR (estrutura espelho AWS)
terraform/gcp/main.tf                                            NEW (VPC + GKE + Cloud SQL + GCS + IAM)
terraform/gcp/variables.tf                                       NEW
terraform/gcp/outputs.tf                                         NEW
terraform/gcp/versions.tf                                        NEW
terraform/gcp/modules/gke/                                       NEW
terraform/gcp/modules/postgres/                                  NEW
terraform/gcp/README.md                                          NEW (≥400 linhas)

# Reference architecture docs
docs/REFERENCE-ARCH-AWS.md                                       NEW (≥500 linhas — diagram + tradeoffs)
docs/REFERENCE-ARCH-GCP.md                                       NEW (≥500 linhas)

# Benchmarks extension
docs/BENCHMARKS.md                                               UPDATE (add AWS + GCP results comparison)
scripts/bench-aws.sh                                             NEW (provision via Terraform + run k6 + tear-down)
scripts/bench-gcp.sh                                             NEW

# Tests
.github/workflows/terraform-validate.yml                         NEW (terraform fmt + validate em PR)
```

---

## Cross-cutting

- `docs/BENCHMARKS.md`: slice C estende. Slice A/B não tocam.
- `.github/workflows/`: cada slice adiciona workflows próprios; sem overlap em nomes.
- `pyproject.toml` raiz: slice A adiciona `wake-cli` extras opcionais pro `badge` subcommand; slice B + C não tocam.

---

## ACCEPTANCE CRITERIA

### `eco-catalog` done quando:

- [ ] `catalog/` Next.js standalone site builda e exporta estático (`next build && next export`)
- [ ] Index lista 4 reference adapters com badges
- [ ] Detail page mostra: name, version, conformance score, last verified date, claim link
- [ ] `wake adapter badge --name=X --score=10` produz SVG válido + Markdown snippet
- [ ] Claim workflow template funcional (testar com 1 adapter mock)
- [ ] `docs/ADAPTER-CATALOG.md` ≥300 linhas
- [ ] `pytest tests/unit/test_badge_generator.py -v` 5+ cases
- [ ] Catalog site Lighthouse Perf ≥90 (static export)

### `eco-supply` done quando:

- [ ] `.github/workflows/sbom.yml` gera CycloneDX 1.5 JSON em release
- [ ] SBOM contém todas deps Python + npm + Helm chart deps
- [ ] `grype` + `trivy` rodam em PR + weekly; falham em CRITICAL/HIGH (com `.grype.yaml` ignore allowlist documentada)
- [ ] `cosign sign` keyless funcionando em release workflow (assume Fulcio + Rekor)
- [ ] `cosign verify` documentado em SECURITY.md
- [ ] `flake.nix` provides Python 3.11 + Node 22 + Helm + cosign + k6
- [ ] `nix develop` entra shell com tudo disponível
- [ ] `SECURITY.md` cobre: supported versions, report email/GitHub Security Advisory, disclosure timeline, scope
- [ ] `docs/SECURITY-DISCLOSURE.md` ≥200 linhas
- [ ] `docs/NIX-DEVSHELL.md` ≥150 linhas

### `eco-refs` done quando:

- [ ] `terraform/aws/` apply num account de teste produz cluster funcional (validar via `terraform plan` no CI; apply é manual)
- [ ] `terraform/gcp/` idem
- [ ] Helm install Wake automático após cluster up (módulo opcional)
- [ ] `docs/REFERENCE-ARCH-AWS.md` + `REFERENCE-ARCH-GCP.md` ≥500 linhas cada com diagrams (ASCII + Mermaid)
- [ ] `docs/BENCHMARKS.md` extended com tabelas AWS + GCP comparison (results podem ser indicativos se infra real não roda no ambiente)
- [ ] `scripts/bench-aws.sh` + `bench-gcp.sh` provision + run + teardown
- [ ] `terraform fmt -check` + `terraform validate` clean em CI

**Quality (todos):**
- [ ] Sem regressão suites baseline
- [ ] Commit prefixes: `catalog:`, `supply:`, `terraform:`, `docs:`, `tests:`

---

## MERGE ORDER

1. **`eco-catalog`** → main (zero overlap)
2. **`eco-supply`** → main (workflows + SECURITY)
3. **`eco-refs`** → main (terraform + BENCHMARKS extension)

Tag final: `v0.9.0-ecosystem` — **última phase antes da Phase 10 (Public Launch)**.

---

## REGRA DE OURO

1. **Leia contract + `docs/ROADMAP.md` Tier 3 + `phases/PHASE-8-CONTRACT.md` ANTES de codar.**
2. **Catalog é package independente** (`catalog/`) — não confunde com dashboard.
3. **Cosign keyless** usa OIDC GitHub — não introduz long-lived keys.
4. **Terraform é REFERENCE**, não module publicada — clones esperados.
5. **Commit no SEU worktree**, `NÃO push`, `NÃO merge`.
6. **Estimativa**: 180-240min wall-clock por slice.
