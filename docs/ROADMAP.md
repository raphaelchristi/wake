# Wake Roadmap — Gap Analysis & Path to v1.0

> Registro honesto do que falta no Wake pra virar **substrato production-ready** para customers reais (não só dev experience). Resultado direto das duas Codex adversarial reviews (que produziram Phase 5.1 e 5.2) + análise interna pós-POC de integração com `ceppem-agent` (2026-05-14).
>
> **Status atual:** Wake é alpha (v0.5.2). Os componentes core (event log, sandbox, vault, multi-worker, dashboard) shipam, mas há **23 gaps** documentados abaixo, organizados por tier de criticidade.
>
> **Public Launch (originalmente Phase 6) foi adiado.** Sem Tier 0 resolvido, o primeiro customer descobre os gaps e sai queimado.
>
> O roadmap histórico anterior (Day 1 / 30 / 90 / 365) está em [`ROADMAP-HISTORICAL.md`](./ROADMAP-HISTORICAL.md) — mantido por contexto e porque vários compromissos dele já shipparam.

---

## TL;DR — re-priorizando o roadmap

| Phase | Foco | Tier que resolve | Por quê | Status |
|---|---|---|---|---|
| **6** | Multi-tenancy + RBAC + backup | Tier 0 (#1 #2 #3) | Bloqueia qualquer customer real | ✅ done (`v0.6.0-tenancy` + `v0.6.1-fixes`) |
| **7** | Operational hardening (idempotency, retention, rate limit, cost budget, Prometheus) | Tier 1 (#4-8) | Sem isso, Wake é "dev tool" não "prod substrate" | ✅ done (`v0.7.0-ops-hardening`) |
| **8** | Client SDKs (Python + TS) + edit-and-replay + eval framework | Tier 2 (#9-12) | É o que faz developers contratarem Wake | ✅ done (`v0.8.0-dx`) |
| **9** | Adapter catalog público + supply chain + benchmarks | Tier 3 (#13-15) | Constrói confiança ecosystem | ✅ done (`v0.9.0-eco`) |
| **10** | Public Launch (era Phase 6) | — | Agora com história contável |
| **11+** | Memory / artifacts / scheduled / multi-agent / computer-use | Tier 4 | Diferenciação vs Managed Agents |

**O gap mais grave:** multi-tenancy. Tudo se desdobra dela — sem ela, RBAC não faz sentido, quotas não fazem sentido, SaaS shape não roda.

**O gap com maior ROI imediato:** client SDK (`wake-py`). Sem ele, mesmo um POC simples vira `httpx.post()` raw. SDK é o que faz Wake "real" pros developers.

---

## Tier 0 — Bloqueia qualquer customer real

> **✅ RESOLVIDO em Phase 6 (`v0.6.0-tenancy`, 2026-05-14)** — gaps #1, #2, #3 fechados via 3 slices paralelos (RBAC backend / frontend tenancy / pgbackrest + DR runbook). Mantidos abaixo por contexto histórico do estado original.

### 1. Multi-tenancy não existe

- Tabelas (`agents`, `sessions`, `events`) têm um único namespace
- Não há `Organization` / `Workspace` / `tenant_id` first-class
- Ceppem é multi-tenant por design (`SogivendasTenantMiddleware`). Se Wake fosse usado, todo tenant viraria `metadata.tenant_id` — sem isolation de query, sem RBAC, sem quota
- **Impacto:** qualquer SaaS-shaped uso é tampão (security by obscurity)

### 2. Authorization é binária

- `X-Wake-API-Key` = god mode
- Não há "user A pode invocar agent X mas não Y"
- Não há "user A não pode ler sessions de user B"
- Dashboard expõe tudo pra quem tem a chave

### 3. Sem backup story

- Phase 4 lista `pgbackrest`/`wal-g` como "Reusable Components" mas zero está wireado no chart
- Sem PITR documented. Sem disaster recovery runbook. Sem `wake export`/`wake import`
- **Não pode rodar prod sem isso**

---

## Tier 1 — Bloqueia produção em escala

### 4. Idempotency / dedup

- `events.append` aloca seq atomicamente, OK
- Mas se o worker double-processa (foi exatamente o finding #3 do Codex que fechamos em Phase 5.2), nada impede 2 escritas para o mesmo step lógico
- Falta `event.metadata.idempotency_key` + UNIQUE index

### 5. Retention + compaction

- Event log cresce pra sempre. Sessions de 100k eventos viram inviáveis no replay
- Sem `wake events compact` ou snapshots periódicos
- Sem TTL → archive-to-S3 pipeline

### 6. Rate limiting + backpressure

- FastAPI sem rate limit middleware. Cliente mal-configurado faz DDoS
- Worker sem signal de "dispatcher saturated; stop polling"
- Sem per-key quota / per-tenant quota

### 7. Cost budgeting

- LiteLLM callbacks emitem `cost_usd` em metadata (✅)
- Mas: **zero enforcement**. Session pode rodar até R$10k sem ninguém saber
- Falta `agent.metadata.max_cost_usd` + kill-switch quando excede

### 8. `/metrics` Prometheus

- Tem `GET /v1/metrics/summary` (JSON pro dashboard)
- **Não tem** `/metrics` exposition (Prometheus). Real ops people scrape Prometheus, não polls REST JSON

---

## Tier 2 — Bloqueia "shipping product" em cima do Wake

### 9. Client SDK

- `wake-py` não existe. Quem integra usa raw HTTP ou abre o dashboard
- TypeScript client tampouco
- Comparar com Anthropic SDK: `client.sessions.create(...)`. Em Wake é `httpx.post(...)`

### 10. Edit-and-replay

- Dashboard tem scrubber pra **visualizar** replay
- **Não tem** "pegar session X, trocar system prompt, replay com mesmas seeds, diff dos eventos resultantes"
- Isso é o golden workflow de prompt engineering. LangSmith tem; Phoenix tem; Wake não

### 11. Eval framework

- `wake-test-conformance` testa **adapters**, não **agents**
- Não há `wake eval run --agent X --dataset golden.jsonl` que rode 100 cenários e mostre p95 cost, accuracy, regressions
- Phoenix Evals + LangSmith Evals fazem isso. Wake precisa equivalente — ou plugin que delegue

### 12. Agent versioning UI

- Backend versiona (✅)
- Dashboard **não mostra** diff entre v3 e v4 de um agent
- Sem canary ("5% do tráfego pra v4")

---

## Tier 3 — Bloqueia ecosystem

### 13. Adapter catalog público

- Conformance suite existe. **Nenhum site/registry público** lista "todos adapters que passam 10/10"
- Third-party autores não têm UX pra reivindicar conformance
- Sem isso, ABI é "API do Wake", não "padrão da indústria"

### 14. Supply chain

- Sem SBOM
- Sem dependency scanning CI
- Sem `SECURITY.md` (só CoC + contributing)
- Images não publicadas em registry, não assinadas (cosign)
- Reproducible builds: nada

### 15. Documentação operacional

- README + specs são bons
- Falta "deploying Wake at scale on AWS/GCP" com Terraform de exemplo
- Falta migration guide: "vim de LangGraph standalone, como ponho isso no Wake"
- Falta benchmark publicado (load test existe, nunca foi rodado real + publicado)

---

## Tier 4 — Parity com Anthropic Managed Agents

Coisas que Anthropic shipou e Wake nem encostou.

### 16. Memory primitives

- Wake só tem event log
- Managed Agents tem memória semântica abstraída
- Ceppem implementa RAG por conta. Mem0/Letta plugariam — Wake não tem hook

### 17. Artifact storage

- Sandbox tem files mas **não há event type canônico** `artifact.created` / API `GET /v1/sessions/{id}/artifacts/{path}`
- Necessário pra workflows tipo "agent gerou um Excel, download pra mim"

### 18. Multi-agent orchestration nativa

- Ceppem faz Root→Domain→Team→Agent **internamente no graph**
- Wake tem `SessionDispatcher` flat por session. Não há "agent A delega pra agent B" como primitive (cada session é independente)
- Managed Agents tem isso first-class

### 19. Scheduled agents

- Sem cron-like trigger. "Roda esse agent toda segunda às 9h" → você builds isso por fora

### 20. Computer use / GUI / voice

- Wake bash/file-edit no sandbox
- Sem browser automation primitive (Playwright in sandbox)
- Sem TTS/STT (ceppem-agent tem!)
- Sem computer-use (screenshot + click)

---

## Tier 5 — Estratégico (não-técnico mas importante)

### 21. Adoção é zero

- Primeiro stress test externo: POC de integração com `ceppem-agent` em 2026-05-14
- Sem case study publicado. Sem RFC público debatido. Sem GitHub Discussions vivendo

### 22. Standards influence ainda é aposta

- HarnessAdapter ABI é "um padrão proposto" enquanto for só Wake
- Falta engagement com maintainers de LangGraph/CrewAI/Pydantic AI pra abençoar/criticar a spec
- LangChain tem influência massiva — Wake precisa amigos lá

### 23. Posicionamento vs Anthropic

- Wake imita arquitetura de Managed Agents abertamente
- Anthropic pode endorse (push pra ecosystem), ignorar, ou competir
- Sem clarification, customers grandes hesitam

---

## Plano detalhado por phase (proposed)

### Phase 6 — Multi-tenancy & RBAC ✅ DONE (`v0.6.0-tenancy`)

**Resolve Tier 0** · **Goal:** Wake suporta múltiplas organizações isoladas com permissões por usuário e backup operational.

Status: ✅ done em 2026-05-14 via 3 slices multi-agent paralelos (`tenancy-rbac`, `tenancy-frontend`, `tenancy-ops`). Tag `v0.6.0-tenancy`. 382 unit tests pass + 107 vitest pass + 8/10 playwright pass + helm lint clean + DISASTER-RECOVERY 1028 linhas + RUNBOOK 919 linhas. Detalhes em [`phases/PHASE-6-multi-tenancy.md`](../phases/PHASE-6-multi-tenancy.md) + [`phases/PHASE-6-CONTRACT.md`](../phases/PHASE-6-CONTRACT.md).

Deliverables:
- `Organization` / `Workspace` entity + tables
- `organization_id` / `workspace_id` first-class em todas as tabelas (agents, sessions, events, vault)
- Per-tenant vault namespaces
- `User` entity + role-based access control (admin, operator, viewer)
- Per-user session scoping
- `wake export` / `wake import` CLI commands
- `pgbackrest` wired into Helm chart com restore runbook (`docs/DISASTER-RECOVERY.md`)
- Dashboard: org switcher + user management UI
- Tests: multi-tenant isolation property tests
- Migration path for single-tenant deploys → multi-tenant (default org/workspace)

### Phase 7 — Operational Hardening

**Resolve Tier 1** · **Goal:** Wake passa em load test de 1000 concurrent sessions em produção real.

Deliverables:
- `event.metadata.idempotency_key` + UNIQUE index com retry-safe append
- `wake events compact` command + snapshot policy
- TTL → S3 archive pipeline
- FastAPI rate limit middleware (per-key, per-tenant quotas)
- Worker backpressure signaling
- `agent.metadata.max_cost_usd` enforcement + kill-switch
- `/metrics` Prometheus exposition endpoint
- Helm chart com `ServiceMonitor` for kube-prometheus-stack
- Load test runbook executed + results published in `docs/BENCHMARKS.md`

### Phase 8 — Developer Experience

**Resolve Tier 2** · **Goal:** Time de produto adota Wake em 1 dia.

Deliverables:
- `wake-py` SDK published to PyPI (typed, async, com `client.sessions.stream()`)
- `wake-ts` SDK published to npm
- Dashboard: "edit & replay" flow (swap prompt, replay, side-by-side diff)
- `wake eval` framework: dataset → agent → metrics (cost, accuracy, latency)
- LangSmith Evals + Phoenix Evals integration adapters
- Agent versioning diff UI + canary deploy (`weight: 5%`)
- `docs/MIGRATION-FROM-LANGGRAPH.md`, `docs/MIGRATION-FROM-MANAGED-AGENTS.md`

### Phase 9 — Ecosystem & Trust

**Resolve Tier 3** · **Goal:** Wake parece um produto, não um experimento.

Deliverables:
- Public adapter catalog (`adapters.wake.dev` ou similar)
- Conformance badge generator + claim flow
- SBOM published per release (CycloneDX format)
- Dependency scanning CI (`grype`, `trivy`)
- `SECURITY.md` + responsible disclosure process
- Container images signed (cosign + sigstore)
- Reproducible builds (Nix flake)
- Reference architecture: AWS Terraform example
- Reference architecture: GCP Terraform example
- Published benchmarks in `docs/BENCHMARKS.md`

### Phase 10 — Public Launch (era Phase 6)

**Goal:** mundo sabe que Wake existe.

Deliverables (originais de PHASE-6-public-launch.md):
- Documentation site (mkdocs-material)
- Asciinema demos
- HN / Reddit / Twitter announcement drafts
- PyPI publish (wake-ai + adapters)
- Discord / GitHub Discussions setup
- Recorded conference talk submission

### Phase 11+ — Managed Agents Parity

**Resolve Tier 4** · **Goal:** Wake é uma alternativa OSS funcional, não só "subset open de Managed Agents".

Possible phases (any order, pick by customer demand):

- **Phase 11A — Memory primitives:** `MemoryAdapter` ABI + reference impls (Mem0, Letta, vector DB)
- **Phase 11B — Artifact storage:** `artifact.created` canonical event + REST API + browser download
- **Phase 11C — Multi-agent orchestration:** `agent.delegate(other_agent)` primitive + delegation events
- **Phase 11D — Scheduled agents:** cron triggers + `Schedule` entity
- **Phase 11E — Computer use:** Playwright-in-sandbox + screenshot/click primitives
- **Phase 11F — Voice:** TTS/STT adapter ABI + reference impls

---

## Tier 5 (estratégico) — executar em paralelo com phases técnicas

Esses items não shipam num PR; são posicionamento e engagement:

- **Adoção:** publicar case study do POC com ceppem (com permissão), conseguir 2-3 stress tests externos ANTES da Phase 10
- **Standards engagement:** abrir issues amigáveis em LangGraph, CrewAI, Pydantic AI propondo o `HarnessAdapter` como padrão de interop; gravar 1 call por equipe pra alinhar
- **Anthropic relationship:** considerar enviar Wake pra `community-projects` ou similar lista; clarificar se é blessed/neutral/competitor

---

## Como ler isto

1. **Sem Tier 0 = sem customer real.** Phase 6 não é opcional — é o gate pra Wake ser usado por alguém que não seja você mesmo.
2. **Sem Tier 1 = não roda em produção.** Phase 7 separa "playground" de "infra séria".
3. **Sem Tier 2 = developers não adotam.** Phase 8 é a feature mais visível pro outside world.
4. **Sem Tier 3 = ABI não vira padrão.** Phase 9 é construir o caminho pra outros frameworks abençoarem.
5. **Public Launch antes desses tiers = queimar reputação.** Use Phase 10 como "lançamento responsável".
6. **Tier 4 é diferenciação, não fundação.** Constrói depois de ter customers.

---

## Histórico de revisões

| Data | Mudança | Trigger |
|---|---|---|
| 2026-05-14 | Roadmap inicial criado com 23 gaps tiered | Análise interna pós-POC ceppem-agent + 2 Codex adversarial reviews |

---

*Este documento é um RFC vivo. Discordâncias e propostas: abra issue com tag `rfc:roadmap` no GitHub.*
