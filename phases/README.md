# Phases

Plano de execução do Wake. Cada fase tem **gates de saída objetivos** — você só passa pra próxima depois de cumprir todos os critérios listados.

`docs/` é o **que** Wake é. `phases/` é o **como** Wake vai ser construído.

---

## Visão geral

| Fase | Nome | Duração | Status |
|---|---|---|---|
| [Phase 0](./PHASE-0-design-lock.md) | Design Lock | 1-2 semanas | 🟡 in_progress |
| [Phase 1](./PHASE-1-skeleton.md) | Skeleton | 2 semanas | ⚪ not_started |
| [Phase 2](./PHASE-2-first-adapter.md) | First Adapter | 2 semanas | ⚪ not_started |
| [Phase 3](./PHASE-3-spec-validation.md) | Spec Validation | 3 semanas | ⚪ not_started |
| [Phase 4](./PHASE-4-production-stack.md) | Production Stack | 3 semanas | ⚪ not_started |
| [Phase 5](./PHASE-5-public-launch.md) | Public Launch | 1 semana | ⚪ not_started |

**Total estimado:** 12-13 semanas (≈3 meses) para Wake v0.1.0 público com 4 adapters funcionando.

---

## Filosofia das fases

### 1. Gates são objetivos, não opinião

Cada fase termina quando todos os critérios de saída listados estão verificavelmente cumpridos. Não "estou achando que tá pronto." Tem que ter:

- Testes passando
- Artefato existindo no repo
- Comando que funciona reproduzivelmente
- Métrica que bateu

### 2. Sem pular fases

A tentação é começar a escrever código antes da Phase 0 fechar. Resistência: a tese inteira de Wake depende de specs validadas pela comunidade. Código sem spec validada é código que vai ser reescrito.

### 3. Cada fase produz algo demoável

Phase 1 demoa: `wake run hello`. Phase 2 demoa: `HarnessAdapter` funcionando. Phase 3 demoa: LangGraph rodando no Wake. Phase 4 demoa: kill -9 e resume. Phase 5 demoa: post no HN.

Se uma fase não tem demo, ela tá errada.

### 4. Riscos são listados antes, não depois

Cada fase tem seção de riscos com mitigações. Quando o risco se materializar, já tem plano.

### 5. Duração é teto, não meta

Estimativas são pessimistas (Hofstadter dobra). Se passar do teto, é sinal pra reavaliar arquitetura, não trabalhar mais horas.

### 6. Audite reuso antes de implementar

Toda fase tem seção `## Reusable Components`. Antes de qualquer task começar, ler essa seção e perguntar:

- **Existe lib madura que faz isso?** → importa.
- **Existe pattern em projeto referência?** → estuda, adapta.
- **Existe spec aberta?** → adota em vez de inventar.

Reescrever do zero o que já existe maduro é a forma #1 de queimar tempo em projeto OSS. As fases foram desenhadas assumindo reuso agressivo. Estimativas de duração só fecham se a regra for seguida.

Lista de reuso por fase em cada `PHASE-N-*.md`, seção `## Reusable Components`. Resumo cross-phase de componentes-chave:

| Componente | Phase | Reuso |
|---|---|---|
| Anthropic Cookbook tool-use | Phase 1 | pattern oficial |
| OpenHands V1 EventLog | Phase 1 | estudar antes de codar |
| `python-statemachine` | Phase 1 | session FSM |
| `pluggy` | Phase 2 | plugin discovery |
| ASGI/MCP conformance patterns | Phase 2 | template de spec testing |
| LangGraph/CrewAI/Pydantic AI docs oficiais | Phase 3 | estudo antes de adapter |
| Open Agent Specification | Phase 3 | adoção parcial considerada |
| `sandbox-runtime` (Anthropic) | Phase 4 | sandbox completo, evita 4 semanas |
| `Infisical Agent Vault` | Phase 4 | vault + proxy completo, evita 3 semanas |
| `LiteLLM` | Phase 4 | model router, evita 2 semanas |
| `agentgateway` (Linux Foundation) | Phase 4 | MCP/A2A gateway, evita 1 semana |
| `mkdocs-material` + FastAPI docs structure | Phase 5 | site pronto em 1 dia |
| `asciinema` | Phase 5 | demos terminal |
| Cloudflare Pages | Phase 5 | hosting grátis

---

## Dependências entre fases

```
Phase 0 (design lock)
   │
   ▼
Phase 1 (skeleton)
   │
   ▼
Phase 2 (first adapter) ──────────┐
   │                              │
   ▼                              │
Phase 3 (spec validation) ────────┤
   │                              │
   ▼                              ▼
Phase 4 (production stack) ─→ Phase 5 (public launch)
```

Phase 4 e Phase 5 podem rodar em paralelo parcialmente (docs/blog/launch prep durante Phase 4).

---

## Como usar este diretório

### Para o autor / equipe core

1. Abrir cada `PHASE-N-*.md` no início da fase
2. Marcar tasks completas conforme avança
3. Verificar gates de saída antes de marcar fase como `done`
4. Atualizar status nesta README ao mudar de fase

### Para contribuidores externos

1. Olha esta README pra ver onde estamos
2. Lê o `PHASE-N-*.md` da fase atual pra ver o que falta
3. Procura tasks marcadas como `help wanted` na fase atual
4. Não tenta contribuir em fase futura — issues serão aceitos mas trabalho não começa antes

### Para usuários potenciais

Lê o status na tabela acima. Se Wake está em Phase 0/1/2 — provavelmente não usável ainda. Phase 3+ — começa a dar pra experimentar. Phase 5 — produto público.

---

## Atualização desta README

Após cada mudança de status de fase, atualize a tabela acima E commite com mensagem `phase: <name> → <new status>`. Histórico do progresso fica visível via `git log phases/README.md`.

---

## Glossário rápido

- **Gate** — critério objetivo de saída de uma fase
- **DoD** (Definition of Done) — checklist final, todos os items precisam estar ✓
- **Help wanted** — task que pode ser feita por contribuidor externo sem dependência de decisão arquitetural
- **Spec lock** — momento em que uma spec é congelada e mudanças exigem RFC
