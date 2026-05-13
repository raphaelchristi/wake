# VISION

> O substrato debaixo dos agentes de IA vai virar commodity. A interface que conecta frameworks a ele, não.

## A tese em uma página

Em 2026, todo time sério rodando agentes em produção encara as mesmas três dores: **durabilidade, sandbox, framework lock-in.** A Anthropic resolveu isso internamente e produtizou como **Managed Agents** — proprietário, hosted, Claude-only, billing por hora.

Existem alternativas open source para cada peça isoladamente — OpenHands para coding agents, Letta para memória, E2B para sandbox, LiteLLM para roteamento de modelo, Infisical para credenciais. Não existe **a costura** — um substrato neutro debaixo desses frameworks, onde LangGraph, CrewAI, Pydantic AI e Claude Agent SDK rodam todos no mesmo runtime, com o mesmo event log, com o mesmo sandbox e com o mesmo vault.

A peça que falta é uma **interface**, não uma implementação. Chamamos de `HarnessAdapter`. É o WSGI dos agentes. Qualquer framework que implementa a interface roda em qualquer runtime compatível.

Wake é (a) a publicação dessa interface como padrão aberto, (b) a implementação de referência do runtime, e (c) os adapters de referência para os frameworks principais.

---

## Os três problemas, descritos honestamente

### 1. Durabilidade

Hoje, "agent em produção" geralmente significa: processo Python rodando, talvez num worker do Celery, com a conversa em memória. Quando o processo morre — OOM, deploy, crash, network blip — a sessão evapora. Não há replay. Não há resume. O usuário recomeça.

Frameworks resolvem parcialmente:

- LangGraph tem checkpointers (SQLite, Postgres, DynamoDB) — funciona dentro do LangGraph
- Temporal/Restate/DBOS oferecem durable execution genérico — você reescreve seu agente como workflow
- OpenHands V1 tem EventLog imutável — funciona dentro do OpenHands

Nenhuma dessas soluções é **substrato neutro**. Cada uma força um modelo de programação.

### 2. Sandbox

Dar bash a um agente é dar shell remoto a um modelo de linguagem. Se o agente sofre prompt injection (e sofre — é a vulnerabilidade #1 de agentes em 2026), ele lê seu `.ssh/id_rsa`, manda pra URL atacante e termina o dia.

Hoje, devs:

- Rodam tudo em Docker padrão (que não é sandbox, é namespace isolation)
- Ou pulam essa parte com `--dangerously-skip-permissions`
- Ou pagam Anthropic/E2B/Daytona/Modal para terceirizar

A Anthropic publicou [sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime) open source — bubblewrap + seccomp + network proxy. Ótimo. Mas é uma biblioteca; ainda precisa ser integrada no runtime, no event log, no vault.

### 3. Framework lock-in

Empresa tem time A em LangGraph, time B em CrewAI, time C em Pydantic AI, time D experimentando AutoGen. Cada um:

- Implementa observabilidade do seu jeito
- Implementa retry/durabilidade do seu jeito
- Implementa sandbox do seu jeito
- Implementa vault do seu jeito

O time de plataforma da empresa não tem como oferecer uma fundação comum. Migrar um agente do framework X para o Y é reescrever tudo.

---

## A solução técnica

Três decisões arquiteturais, em ordem de importância:

### Decisão 1: Event log append-only é a fonte de verdade

Não a memória do processo. Não o state do framework. **O event log durável.**

Toda interação — user message, assistant response, tool call, tool result, status change — é um evento. Eventos são imutáveis. Você corrige com novos eventos, nunca atualizando os antigos.

Isso desbloqueia:

- **Resume:** harness lê eventos, reconstrói estado, continua
- **Replay:** rebobina pra qualquer evento, refaz do mesmo input
- **Fork:** branch num evento, explora caminho alternativo
- **Audit:** log assinado, compliance-grade
- **Debug:** vê exatamente o que aconteceu

### Decisão 2: Harness fica fora do container

Esse é o insight central que a Anthropic descreve no [engineering post](https://www.anthropic.com/engineering/managed-agents) sobre "decoupling the brain from the hands."

O harness é uma função stateless: `wake(sessionId) → getEvents() → emitir novos eventos`. Pode morrer a qualquer momento, ser reescalonado em outra máquina, restart sem perda.

O container (sandbox) é cattle: provisionado preguiçoso, na primeira tool call que precisa dele. Se morre, vira um tool-call error que o LLM recebe e pode tentar de novo.

Crítico: **o harness invoca o sandbox como uma tool** — `execute(name, input) → string`. Não é "harness rodando dentro do container." É "container exposto via interface unificada de tools."

Citação direta da Anthropic: *"The harness doesn't know whether the sandbox is a container, a phone, or a Pokémon emulator."*

### Decisão 3: HarnessAdapter como interface pública

A arquitetura acima é genérica. Pode rodar qualquer harness. A Anthropic mantém esse slot interno — eles usam pra rodar variantes próprias (incluindo Claude Code).

A oportunidade open source é literalmente **publicar essa interface como padrão.** Chamamos de `HarnessAdapter` v0.1.0. Define:

```
step(ctx, events, tools) → AsyncIterator[Event]
```

Qualquer framework que implementa essa interface roda no runtime Wake. Implementações de referência:

- `adapter-claude-sdk` — Claude Agent SDK como harness
- `adapter-langgraph` — StateGraph como harness
- `adapter-crewai` — Crew como harness
- `adapter-pydantic-ai` — Pydantic AI Agent como harness

Cada adapter é ~200-400 linhas. Tradução entre o modelo interno do framework e o event schema canônico.

---

## O que Wake NÃO é

Importante para posicionamento:

- **Não é um framework de agentes.** LangGraph, CrewAI, Pydantic AI continuam existindo. Wake roda eles.
- **Não é um sandbox.** Reusa sandbox-runtime, Docker, gVisor, Firecracker.
- **Não é um vault.** Reusa Infisical Agent Vault.
- **Não é uma camada de memória.** Letta, Mem0 continuam existindo e podem plugar.
- **Não é uma camada de observabilidade.** Langfuse, Phoenix, Helicone continuam existindo e podem consumir o event log.
- **Não é um durable execution engine.** Temporal, Restate, DBOS continuam existindo (Wake pode usar um deles internamente).
- **Não é multi-provider routing.** Reusa LiteLLM.
- **Não é um produto SaaS.** É open source, self-host first.

**É:** a costura entre todas essas peças, governada por uma spec aberta (HarnessAdapter + event schema).

---

## Para quem é Wake

### Usuários primários

- **Times de plataforma de IA** em empresas que precisam padronizar agentes entre múltiplos frameworks
- **Devs frustrados com Managed Agents** (billing, lock-in, branding) querendo self-host com mesma UX
- **Devs em coding-agents** (alternativa ao OpenHands com mais flexibilidade)
- **Teams em compliance/regulated industries** que precisam de audit log assinado e replay determinístico

### Não-usuários

- Dev solo brincando com agente em weekend project — overkill
- Time que já tem stack Temporal + LangGraph funcionando — não precisa migrar
- Empresa 100% comprometida com Claude e satisfeita com Managed Agents hosted — pague Anthropic

---

## A aposta

A aposta é dupla:

1. **Substrato vai virar commodity em 6-12 meses.** OpenHands V1, Microsoft Agent Framework, Multica, OpenClaw — todos convergem. A briga será sobre quem ganha o mindshare antes da consolidação.
2. **A interface HarnessAdapter é o moat real.** Ninguém publicou ainda. Se Wake fizer isso primeiro e for adotada por LangGraph/CrewAI/Pydantic AI como integração nativa, vira padrão (igual MCP virou para tools).

Time window: ~6 meses para definir o padrão. ~12 meses para conquistar mindshare antes da convergência fechar a janela.

Se a aposta estiver errada — se MAF ou OpenHands publicar a interface primeiro, ou se a indústria convergir em outra direção — Wake vira um fork ou contribui de volta. O custo de errar é baixo. O custo de não tentar é perder a chance de definir como agentes plugam em substratos pelo próximo ciclo.

---

## A pergunta que importa

Se essa visão estiver certa, dentro de 18 meses todo agente em produção vai rodar num runtime que fala uma versão dessa interface. A pergunta é se será uma interface aberta, com governança de comunidade, ou um padrão de facto de algum vendor.

Wake aposta na primeira opção e quer ser a referência.
