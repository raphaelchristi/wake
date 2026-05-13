# PRINCIPLES

Princípios de design que governam decisões. Quando há conflito entre features e princípios, princípios ganham.

---

## 1. Event log é a única fonte de verdade

Não cache. Não state em memória. Não objetos serializados. **Append-only event log.** Imutável. Replayable. Auditable.

**Consequência:** todo state derivado é reconstruível a partir do log. Se algo não pode ser reconstruído do log, está errado.

**Não negociável.**

---

## 2. Harness é stateless

O harness é uma função pura: `step(events, tools, ctx) → AsyncIterator[Event]`. Pode morrer a qualquer instante. O próximo `wake()` reconstrói tudo a partir do log.

**Consequência:** sem sessões "agarradas" a uma máquina. Sem state in-memory entre invocações. Sem locks distribuídos. Escala horizontalmente sem cerimônia.

**Não negociável.**

---

## 3. Container é cattle, não pet

Containers são provisionados preguiçoso (na primeira tool call que precisa) e descartáveis. Morte do container = tool_call error, não falha de sessão.

**Consequência:** TTFT baixo (não espera container). Custo baixo (containers só quando necessários). Resiliência alta (qualquer container morre, ninguém liga).

**Não negociável.**

---

## 4. Sandbox é uma tool, não um modo de execução

O sandbox é invocado via `execute(name, input) → string`. O harness não sabe se por trás é Docker, sandbox-runtime, Firecracker, gVisor, máquina física ou Pokémon emulator.

**Consequência:** trocar de runtime de sandbox é trocar de adapter. Sem reescrever harness, sem reescrever frameworks.

**Não negociável.**

---

## 5. Credenciais nunca tocam o harness

Tokens OAuth, API keys, secrets vivem num vault separado. O harness chama tools autenticadas via proxy. O proxy injeta credenciais no nível do request HTTP. O harness e o sandbox nunca veem o token real.

**Consequência:** prompt injection que tenta exfiltrar credenciais não tem o que exfiltrar. Audit trail mostra cada uso. Rotação não exige redeploy.

**Não negociável.**

---

## 6. Frameworks plugam via interface, não dependência

Wake não importa LangGraph. LangGraph não importa Wake. Existe um adapter no meio que traduz.

**Consequência:** atualização de LangGraph não quebra Wake. Mudança em Wake não quebra LangGraph. Adapters são versionáveis independente do framework.

**Negociável apenas com motivo arquitetural muito claro.**

---

## 7. Reuse antes de reinventar

Sandbox: usa sandbox-runtime. Vault: usa Infisical Agent Vault. Model routing: usa LiteLLM. MCP: usa o protocolo oficial. Agent definition: usa Open Agent Specification.

**Consequência:** o código próprio de Wake é menor. Vulnerabilidades resolvidas upstream nos beneficiam. Bibliotecas maduras compartilhadas com ecossistema.

**Aplicável sempre que existir alternativa OSS razoável.**

---

## 8. Compatibilidade superficial com Managed Agents API

Endpoints, status codes, schemas de request/response idênticos onde possível. Um dev que sabe Managed Agents consegue usar Wake sem reler docs.

**Consequência:** drop-in migration. Adoção mais fácil. Ferramentas ao redor (SDKs, dashboards) funcionam nos dois.

**Aplicável até o ponto onde divergir é claramente melhor.**

---

## 9. Determinismo é design goal, não acidente

Replay produz mesmo resultado dado mesmos inputs. Onde determinismo é impossível (LLM amostragem, tempo, IO externo), Wake snapshota.

**Consequência:** debugging via replay é confiável. Compliance audit é confiável. Side-by-side comparison de agentes é confiável.

**Aplicável a tudo no caminho hot.**

---

## 10. Spec primeiro, código depois

Toda decisão estrutural passa por um documento (spec, RFC) antes de virar código. Documento é PR-eável. Comunidade revisa antes da implementação.

**Consequência:** menos retrabalho. Comunidade compra a tese antes do código existir. Specs viram padrão; código vira referência.

**Aplicável a HarnessAdapter, event schema, tool ABI, API REST, qualquer interface pública.**

---

## 11. Out-of-box experience é sagrado

`pip install wake-ai && wake server --local && wake run "hello"` precisa funcionar em <2 minutos sem ler docs.

**Consequência:** decisões padrão precisam ser inteligentes. Configuração é progressiva: nada → mínimo → completo.

**Aplicável a CLI, SDK, exemplos, docs.**

---

## 12. Sem cerimônia para casos comuns

Casos comuns: rodar um Claude SDK simples; ouvir eventos; pegar resultado final. Cada um precisa ser uma linha de código.

```python
result = wake.run("refactor this file", agent="coding-bot")
```

Casos avançados (multi-framework, vault customizado, sandbox plugável) ficam atrás de configuração explícita.

**Princípio Rails-y: "convention over configuration" para 80% dos casos.**

---

## 13. Multi-provider é Day 2

Day 1: Claude (Anthropic API direto). Day 2+: outros providers via LiteLLM ou adapter.

**Motivação:** semântica de tool use varia entre providers. Caching/thinking/skills são Claude-only. Tentar abstrair tudo no Day 1 = vazamento ou simplificação demais.

**Honesto:** Wake é "Claude-first, BYO-LLM possible." Não é "neutral multi-provider."

---

## 14. Multiagent, outcomes e memória são features de produto, não primitivas

Multiagent (coordinator + workers), outcomes (LLM-as-judge), memory (long-term facts) — todos são úteis. Todos podem ser construídos em cima das primitivas. Nenhum é primitiva.

**Consequência:** roadmap não promete essas coisas no core. Elas podem virar pacotes (`wake-multiagent`, `wake-outcomes`, `wake-memory`) ou plugins.

---

## 15. Documentação é código

Se uma feature não está documentada, ela não existe. PRs que mudam comportamento sem atualizar docs são rejeitados.

**Aplicável desde o pre-alpha.**

---

## Decisões irreversíveis (escolhidas com cuidado extra)

Algumas decisões custam muito reverter depois. Listadas explicitamente para tomar com peso:

1. **Event schema canônico** — quase impossível mudar quebrando, exige major version bump
2. **HarnessAdapter signature** — idem
3. **Session status enum** — frameworks dependem disso
4. **Tool ABI** — todas as tools dependem
5. **API REST contract** — clientes dependem
6. **Linguagem do runtime principal** — Python vs Go vs Rust define ecosistema

Para essas, exigimos: spec escrita, RFC público, ≥2 semanas de revisão, ≥3 adapters de referência implementados antes de v1.0.

---

## Anti-princípios (o que recusamos fazer)

- ❌ "Suportar todos os frameworks" via interface mais larga e leaky
- ❌ Embutir LLM routing dentro do runtime (delegamos a LiteLLM)
- ❌ Embutir vector store dentro do runtime (delegamos a quem quiser)
- ❌ UI/dashboard como parte do core (vira pacote separado)
- ❌ Optimization automática de prompt (não é nosso problema)
- ❌ Fine-tuning, RAG, vector search (não é nosso problema)
- ❌ Marketplace de agents (não é nosso problema)
- ❌ Billing/quota (não é nosso problema)
- ❌ Empurrar conta SaaS no usuário

Wake é **substrato**. Quem quer SaaS por cima constrói por cima.
