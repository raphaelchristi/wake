# Phase 0 — Design Lock

> **Objetivo:** congelar as specs publicamente após >1 semana de revisão da comunidade. Nenhum código antes disso.

| | |
|---|---|
| **Status** | 🟡 in_progress |
| **Duração estimada** | 1-2 semanas |
| **Início** | repo publicado em GitHub |
| **Dependências** | nenhuma |

---

## Por que essa fase existe

A tese inteira de Wake depende de uma spec aberta que vire padrão. Se a spec sair errada e código for escrito em cima dela, todo o ecosystem de adapters vai herdar a falha — e fixar depois exige major version bump quebrando todo mundo.

**Custo de um erro de spec:** 6+ meses de retrabalho.
**Custo de mais 1 semana de revisão:** zero.

Por isso esta fase **bloqueia tudo até as specs estarem validadas**.

---

## Entry criteria (já cumpridos)

- ✅ `docs/` publicado com 12 documentos
- ✅ Repo no GitHub (https://github.com/raphaelchristi/wake)
- ✅ `README.md` raiz aponta pros docs
- ✅ Specs v0.1.0 rascunhadas

---

## Exit criteria (gates)

Todos precisam estar verificadamente cumpridos antes de iniciar Phase 1:

- [ ] `LICENSE` commitado (MIT ou Apache 2.0)
- [ ] `CONTRIBUTING.md` commitado com processo RFC documentado
- [ ] `CODE_OF_CONDUCT.md` commitado
- [ ] Issue "RFC: HarnessAdapter v0.1.0" aberta com label `rfc`
- [ ] Issue "RFC: Event Schema v0.1.0" aberta com label `rfc`
- [ ] Issue "Q: Runtime language — Python vs Go vs Rust" aberta com label `decision`
- [ ] Anúncio público feito (HN OR tweet OR post Discord)
- [ ] Janela de review aberta por ≥7 dias após anúncio
- [ ] ≥5 comentários externos em cada issue de RFC OU declaração explícita de "passou sem review significativo, prosseguindo"
- [ ] Specs `SPEC-HARNESS-ADAPTER.md` e `SPEC-EVENT-SCHEMA.md` tagueadas como `spec-v0.1.0-frozen` em git
- [ ] Open questions Q1-Q4 de cada spec têm decisões documentadas no próprio documento
- [ ] Decisão de linguagem do runtime tomada e documentada em `phases/decisions/runtime-language.md`

---

## Deliverables

### Arquivos novos

```
LICENSE                                   # MIT ou Apache 2.0
CONTRIBUTING.md                           # processo de contribuição + RFC
CODE_OF_CONDUCT.md                        # Contributor Covenant 2.1
phases/decisions/                         # arquivo por decisão arquitetural
└── runtime-language.md
.github/
├── ISSUE_TEMPLATE/
│   ├── rfc.md                           # template para RFC
│   ├── bug.md
│   └── feature.md
└── PULL_REQUEST_TEMPLATE.md
```

### Issues no GitHub

- RFC: HarnessAdapter v0.1.0
- RFC: Event Schema v0.1.0
- Q: Runtime language (Python vs Go vs Rust)
- Q: License (MIT vs Apache 2.0)
- Q: Default sandbox backend
- Welcome / introduction (para early visitors)

### Publicações externas

- Tweet/post anunciando
- Show HN ou Hacker News thread (opcional)
- Post em discords relevantes (LangChain, MCP, etc.)

---

## Tasks detalhadas

### T0.1 — Escolher e commitar LICENSE
**Effort:** 30min
**Decisão:** Apache 2.0 recomendado para projeto infra com chance enterprise (patents grant + corporate friendliness). MIT como fallback.

```bash
# após decisão
curl -o LICENSE https://www.apache.org/licenses/LICENSE-2.0.txt
# editar para incluir copyright header se necessário
git add LICENSE && git commit -m "license: Apache 2.0"
```

### T0.2 — Escrever CONTRIBUTING.md
**Effort:** 2h

Deve cobrir:
- Como abrir issue
- Como propor mudança em spec (processo RFC)
- Como contribuir código (quando código existir, Phase 1+)
- Como rodar testes
- DCO sign-off ou CLA (decidir)

### T0.3 — Commitar CODE_OF_CONDUCT.md
**Effort:** 10min

Usar Contributor Covenant 2.1 padrão. Adicionar email de contato.

### T0.4 — Criar templates de issue e PR
**Effort:** 1h

`.github/ISSUE_TEMPLATE/rfc.md`:
```markdown
---
name: RFC (Request for Comments)
about: Propose changes to specs or major architecture
title: 'RFC: '
labels: rfc
---

## Summary
## Motivation
## Detailed design
## Drawbacks
## Alternatives considered
## Unresolved questions
```

### T0.5 — Abrir RFC: HarnessAdapter v0.1.0
**Effort:** 1h

Issue copia/cola do SPEC-HARNESS-ADAPTER.md com pedido específico de feedback:

- "Adapter para meu framework cabe nessa interface?"
- "Open questions Q1-Q4 — qual decisão?"
- "Naming é confuso?"
- "Onde a spec é ambígua?"

### T0.6 — Abrir RFC: Event Schema v0.1.0
**Effort:** 1h

Idem. Foco específico em:
- Tipos faltando
- Mapping pra Anthropic Messages API
- JSON schemas validação

### T0.7 — Abrir Q: Runtime language
**Effort:** 30min

Issue listando trade-offs:
- Python: ecosystem AI maior, type system fraco, pip hell
- Go: single binary, perf, ecosystem AI fraco, generics meh
- Rust: perf máxima, learning curve, ecosystem AI nascente

Pedir input de quem vai usar.

### T0.8 — Identificar e contatar 5-10 reviewers candidatos
**Effort:** 2h

Lista de pessoas a contatar diretamente:
- Mantenedores de LangGraph (Harrison Chase et al.)
- Mantenedores de CrewAI (João Moura)
- Mantenedores de Pydantic AI
- Time de Managed Agents (se houver contato)
- Time de OpenHands
- Time de sandbox-runtime
- 2-3 devs de plataforma em empresas que rodam agentes
- 2-3 OSS maintainers conhecidos no espaço

Mensagem privada curta: "publicamos uma spec experimental para X, gostaria muito do seu feedback, link aqui."

### T0.9 — Anúncio público
**Effort:** 4h (com revisão de texto)

Canais:
1. Tweet/X thread (5-7 tweets)
2. Post em discord MCP
3. Post em discord LangChain (se permitido)
4. Reddit r/LocalLLaMA (cuidado com regras)
5. Hacker News (opcional, com timing — terças/quartas manhã US)

Mensagem-tipo:
> "We just published the design phase of Wake — an open spec for a framework-agnostic agent runtime substrate. Looking for honest critique before we write any code. <link>"

### T0.10 — Janela de review (7+ dias)
**Effort:** observar + responder

Durante a semana:
- Responder comentários em <24h
- Atualizar spec se ajuste menor não-breaking
- Logar feedback grande em issues separadas
- Não defender — entender

### T0.11 — Decisões finais
**Effort:** 1d

Ao fim da janela:
- Para cada open question Q1-Q4 em cada spec → decisão documentada
- Para decisão de linguagem → documento em `phases/decisions/runtime-language.md`
- Aplicar mudanças não-breaking nas specs
- Aplicar mudanças breaking apenas se houver consenso claro

### T0.12 — Spec lock v0.1.0
**Effort:** 30min

```bash
git tag spec-v0.1.0
git push origin spec-v0.1.0
```

Atualizar README de cada spec com:
> **Frozen at v0.1.0** — mudanças requerem RFC e major version bump.

---

## Riscos e mitigações

### R0.1 — Ninguém revisa (engajamento baixo)
**Probabilidade:** alta
**Impacto:** médio
**Mitigação:**
- Contatar reviewers diretamente (T0.8)
- Não dependermos só de canais abertos
- Definir limite: "se <5 comments externos após 14 dias, prosseguir mesmo assim com nota explícita no commit de lock"

### R0.2 — Bikeshedding sobre nome / cor do botão
**Probabilidade:** média
**Impacto:** baixo (atraso, não dano)
**Mitigação:**
- Time-box: 7 dias úteis máximo na janela de review
- "Nome do projeto" e "syntax detalhada" são out-of-scope durante Phase 0

### R0.3 — Crítica fundamental aparece (spec tem falha grave)
**Probabilidade:** baixa-média
**Impacto:** alto (extensão de 1-2 semanas)
**Mitigação:**
- Esse é exatamente o ponto desta fase
- Se aparecer falha, **agradece muito**, atrasa o projeto, conserta
- Custo de Phase 0 atrasada << custo de Phase 4 com spec ruim

### R0.4 — Concorrente publica algo equivalente durante janela
**Probabilidade:** baixa
**Impacto:** alto
**Mitigação:**
- Não há mitigação direta
- Monitorar OpenHands, MAF, Multica
- Se aparecer, avaliar honestamente: contribuir lá em vez?

### R0.5 — Licença errada escolhida (perde adoção)
**Probabilidade:** baixa
**Impacto:** médio-alto
**Mitigação:**
- Apache 2.0 é safe default
- Mudar licença pós-Phase-0 é caro (precisa concordância de todos contribuidores)
- Se incerto, **default Apache 2.0** e seguir

---

## Definition of Done (Phase 0)

- [ ] Todos os Exit Criteria checkados acima
- [ ] Tag `spec-v0.1.0` em git
- [ ] Status atualizado em `phases/README.md` para ✅ done
- [ ] Commit: `phase 0: design lock complete`
- [ ] Phase 1 unblock anunciado

---

## Métricas de sucesso

| Métrica | Mínimo | Meta |
|---|---|---|
| Comentários em RFC | ≥5 | ≥20 |
| Reviewers externos contatados | 5 | 10 |
| Pessoas que respondem | 2 | 5 |
| GitHub stars | 10 | 100 |
| Issues abertas pela comunidade | 0 | 5 |

**Não-métrica:** stars. Stars sem feedback são ruído.

---

## After this phase

→ [Phase 1: Skeleton](./PHASE-1-skeleton.md) — escrever o runtime mínimo.
