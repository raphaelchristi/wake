# Phase 5 — Public Launch

> **Objetivo:** Converter design + tech work em adoção real. Docs site, 3 tutorials end-to-end, 2 blog posts, Show HN, Twitter thread, Discord. Target: 1000-2000 stars + 100+ Discord members em 2 semanas.

| | |
|---|---|
| **Status** | ⚪ not_started |
| **Duração estimada** | 1 semana (5-7 working days) |
| **Dependências** | Phase 4 done (production stack funcionando) |

---

## Por que essa fase existe

Wake pode ter design perfeito e tech sólida — se ninguém souber, não importa.

Phase 5 é a fase mais simples tecnicamente e mais difícil estrategicamente: **distribuição**. Marketing OSS não é hype; é fazer as pessoas certas descobrirem no momento certo via canal certo.

Esta fase existe explicitamente porque devs/eng tendem a subestimá-la. Ela é nominalmente curta (1 semana) mas tem impacto desproporcional.

---

## Entry criteria

- ✅ Phase 4 done
- ✅ Examples 01-08 funcionando reproduzivelmente
- ✅ Documentação `docs/` completa
- ✅ Helm chart deploy testado
- ✅ Tag v0.4.0-production em git

---

## Exit criteria (gates)

Todos verificadamente cumpridos:

### Site

- [ ] `docs.wake.dev` (ou wake.dev/docs) publicado
- [ ] mkdocs ou starlight com tema próprio (não tema default)
- [ ] Search funcionando
- [ ] Versioning das specs visível
- [ ] Mobile-friendly

### Tutorials

- [ ] Tutorial 1: "Deploy your first Wake agent" (~30min, end-to-end)
- [ ] Tutorial 2: "Port your LangGraph agent to Wake" (~30min)
- [ ] Tutorial 3: "Self-host Wake on Fly.io" (ou AWS/GCP) (~30min)
- [ ] Cada tutorial tem código no `examples/` correspondente
- [ ] Cada tutorial tem GIF/asciicast no início

### Blog posts

- [ ] Blog post 1: "Why Wake: the harness-portable substrate" (~2000 palavras)
- [ ] Blog post 2: "HarnessAdapter spec walkthrough" (~1500 palavras)
- [ ] Ambos publicados em `docs/blog/` E crosspostados (dev.to ou Medium)

### Vídeo

- [ ] Demo video (asciicast OU short Loom) mostrando hello-world em 60s
- [ ] Embedded no README e na home do site

### Outreach

- [ ] Lista de 50+ pessoas-chave contatadas privadamente antes do launch
- [ ] Mensagem privada enviada para mantenedores de LangGraph, CrewAI, Pydantic AI pedindo feedback (não endorsement)
- [ ] 5+ early adopters identificados que vão postar comentários positivos

### Launch day

- [ ] Show HN postado (terça ou quarta manhã US East)
- [ ] Twitter/X thread postado (mesmo dia)
- [ ] Reddit r/LocalLLaMA / r/MachineLearning post (com cuidado de regras)
- [ ] LinkedIn post pessoal
- [ ] Discord servers (LangChain, MCP, etc.) — posts nos channels apropriados
- [ ] Discord/Slack da Wake aberto e moderado

### Comunidade

- [ ] Discord server criado com:
  - [ ] #welcome
  - [ ] #general
  - [ ] #specs-feedback
  - [ ] #adapters
  - [ ] #help
  - [ ] #show-and-tell
- [ ] Roles configurados (newcomer / contributor / maintainer)
- [ ] Bots para moderação (carl-bot ou similar)
- [ ] Code of Conduct aplicado

---

## Deliverables

### Site (mkdocs material ou starlight)

```
docs-site/
├── mkdocs.yml (ou astro.config.mjs)
├── docs/
│   ├── index.md
│   ├── quickstart.md
│   ├── concepts/
│   ├── adapters/
│   ├── deploy/
│   ├── specs/
│   ├── api/
│   ├── examples/
│   └── blog/
├── overrides/
└── public/
```

Hospedagem: Cloudflare Pages, Vercel, ou GitHub Pages.

### Conteúdo

```
docs/tutorials/
├── 01-first-agent.md           # ~3000 palavras + screenshots
├── 02-port-langgraph.md        # ~2500 palavras
└── 03-deploy-self-host.md      # ~3000 palavras

docs/blog/
├── 2026-XX-why-wake.md
├── 2026-XX-harness-adapter-spec.md
└── 2026-XX-three-frameworks-on-wake.md  # da Phase 3

public/
├── demo.cast                    # asciinema
└── og-image.png                 # social preview
```

### Outreach materials

```
launch/
├── hn-post.md                   # title + body do post
├── twitter-thread.md            # 10-15 tweets
├── reddit-llama.md
├── linkedin-post.md
├── personal-outreach-template.md
└── contacts-list.csv            # quem foi contactado, quando, resposta
```

---

## Tasks detalhadas

### Pré-launch (5 dias)

#### T5.1 — Docs site setup (1d)

Escolher entre mkdocs-material e starlight (Astro). Para velocidade: mkdocs-material.

```bash
pip install mkdocs-material
mkdocs new docs-site
# customize theme, navigation, plugins
mkdocs serve
```

Configurar:
- Search
- Versioning (mike plugin)
- Light/dark mode
- Code copy buttons
- Mermaid diagrams

#### T5.2 — Tutorial 1: First agent (1d)

Roteiro:
1. Install Wake
2. Start server
3. Create simple agent (YAML)
4. Send message
5. Watch streaming
6. View events
7. Replay

~3000 palavras + 8-10 screenshots / animated GIFs. Código em `examples/tutorial-01/`.

#### T5.3 — Tutorial 2: Port LangGraph (1d)

Roteiro:
1. Have an existing LangGraph StateGraph
2. Install wake-adapter-langgraph
3. Wrap with `LangGraphAdapter`
4. Run on Wake
5. See durability, replay
6. Compare metrics (cost, latency)

~2500 palavras. Use case real: ReAct agent simples.

#### T5.4 — Tutorial 3: Self-host (1d)

Escolher provider mais simples: Fly.io.

Roteiro:
1. Clone deploy/helm/wake (ou usar fly.toml)
2. Configure Postgres
3. Deploy
4. Configure DNS
5. SSL
6. First production session

~3000 palavras.

#### T5.5 — Blog post 1: Why Wake (1d)

~2000 palavras. Estrutura:

1. The problem (3 crises de produção)
2. Why existing solutions miss
3. The bet (HarnessAdapter ABI)
4. The architecture (brain/hands)
5. What's different vs OpenHands, MAF, Multica
6. What's next

#### T5.6 — Blog post 2: HarnessAdapter spec walkthrough (0.5d)

~1500 palavras. Mostra:

1. The interface
2. Walk through a Claude SDK adapter
3. Walk through a LangGraph adapter
4. The 10 conformance tests
5. How to write your own

#### T5.7 — Demo video (0.5d)

Asciinema ~60s:

```
$ pip install wake-ai
$ wake server --local
$ wake run "build me a CLI todo app"
[streaming events...]
$ wake session events --tail
$ wake session replay sess_xxx --from 5
```

Bonus: short Loom (~3min) mostrando UI side-by-side.

#### T5.8 — Outreach privado (1d, paralelo)

50+ pessoas. Mensagem template (curta!):

> Hey [name], we built Wake — an open-source substrate for AI agents that exposes a HarnessAdapter ABI so any framework (LangGraph, CrewAI, Pydantic AI, Claude Agent SDK, custom) plugs in. Inspired by Anthropic's Managed Agents brain/hands split. Launching publicly next [Tuesday]. Would love your honest feedback before then: <link to docs.wake.dev>. No need to respond if not relevant — just figured you'd want a heads-up.

Lista incluindo:
- Mantenedores: LangChain (Harrison), CrewAI (João), Pydantic AI, Anthropic eng
- Influencers OSS AI: Simon Willison, Ahmed Awadallah, etc.
- Eng leaders em empresas que rodam agentes
- VCs especializados em devtools (off-topic mas eles spam)

Track em `launch/contacts-list.csv`.

### Launch day (1 dia)

#### T5.9 — Show HN (0.5h preparação, dia inteiro responder)

Title (testar 3 variantes):
- "Show HN: Wake – open-source substrate for AI agents (any framework plugs in)"
- "Show HN: Wake – run LangGraph, CrewAI, Claude Agent SDK on the same durable runtime"
- "Show HN: Wake – open alternative to Anthropic Managed Agents (multi-framework)"

Timing: terça ou quarta, 9-11am US East.

Body: 3-4 parágrafos curtos. Links pra docs + repo. Não overpitch.

Responder cada comentário em <30min nas primeiras 4h.

#### T5.10 — Twitter/X thread (0.5h preparação, monitor durante dia)

10-15 tweets:

1. Hook
2. Problema
3. Existing solutions miss
4. Our take
5. Architecture (com diagrama)
6. HarnessAdapter (com snippet)
7. Adapters disponíveis
8. Self-host
9. What's NOT (frameworks, sandboxes, etc.)
10. Comparison table
11. Links

#### T5.11 — Reddit + LinkedIn + Discord (0.5d)

Reddit r/LocalLLaMA: respeitar regras de self-promo. Talvez melhor canal: r/MachineLearning Saturday Discussion.

LinkedIn: post pessoal, não promotional pesado.

Discord servers a postar (#showcase ou similar):
- LangChain
- Model Context Protocol
- LocalLLaMA
- Anthropic Community

#### T5.12 — Monitor + respond (todo dia 0)

- Discord: respostas <1h
- HN: respostas <30min
- Twitter: respostas <2h
- GitHub issues: respostas <4h

### Post-launch (3-5 dias)

#### T5.13 — Triage feedback inicial

- Issues abertas → labelagem + roadmap update
- PRs externos → review + merge ou guidance
- Discord questions → FAQ updates

#### T5.14 — Follow-up content

Se houve tração:
- Post 3: "What we learned from launch week"
- Engagement com framework maintainers que comentaram

Se houve crítica forte:
- Post: "Addressing the criticism" (honest, não defensive)

#### T5.15 — Métricas e retrospectiva

Após 1 semana:

```
GitHub stars: actual vs target
Discord members: actual vs target
Issues abertas: types breakdown
PRs externos: count
Reddit/HN engagement: upvotes, comments
Twitter impressions
Site visits (analytics)
Adapter installs (PyPI download stats)
```

Doc retrospectiva em `phases/retrospective-phase-5.md`.

---

## Reusable Components

### Docs site

| Opção | Source | License | Quando usar |
|---|---|---|---|
| **`mkdocs-material`** | [squidfunk/mkdocs-material](https://github.com/squidfunk/mkdocs-material) | MIT | **Recomendado.** Setup de horas. Tema profissional. |
| Starlight (Astro) | [withastro/starlight](https://github.com/withastro/starlight) | MIT | Alternativa moderna, JS-based |
| Docusaurus | [facebook/docusaurus](https://github.com/facebook/docusaurus) | MIT | React-based, mais pesado |
| Nextra | [shuding/nextra](https://github.com/shuding/nextra) | MIT | Next.js-based |

### Setup patterns a copiar

| Pattern | Fonte | Por quê |
|---|---|---|
| **FastAPI docs setup** | [fastapi/fastapi `docs/`](https://github.com/fastapi/fastapi/tree/master/docs) | Referência absoluta. mkdocs-material expert-tier. MIT. |
| Pydantic docs setup | [pydantic/pydantic `docs/`](https://github.com/pydantic/pydantic/tree/main/docs) | mkdocs-material + plugins ricos. MIT. |
| LangChain docs | [langchain-ai/langchain-docusaurus](https://github.com/langchain-ai/langchain/tree/master/docs) | Docusaurus pesado, ver se vale |
| Anthropic docs structure | platform.claude.com | comparação de UX |

### Hosting

| Opção | Custo | Notas |
|---|---|---|
| **Cloudflare Pages** | grátis | unlimited bandwidth, build minutes generosos |
| Vercel | grátis no Hobby | bandwidth limitado |
| Netlify | grátis básico | bandwidth limitado |
| GitHub Pages | grátis | mais lento, menos features |

### Deploy CLI

| Tool | Source | License |
|---|---|---|
| `wrangler` (Cloudflare) | [cloudflare/wrangler](https://github.com/cloudflare/workers-sdk) | MIT |
| `mkdocs gh-deploy` | mkdocs | BSD |

### Demo videos

| Tool | License | Para que |
|---|---|---|
| **`asciinema`** | GPL 3 | Terminal recording, embedável (preferido) |
| `vhs` (Charm) | [charmbracelet/vhs](https://github.com/charmbracelet/vhs) | MIT | Scripted terminal GIFs |
| `terminalizer` | MIT | GIF de terminal |
| Loom | proprietário | Screen recording (alternativa) |

### Image generation (social previews)

| Tool | License | Para que |
|---|---|---|
| `og-image` (Vercel) | MIT | OG images programáticos |
| Excalidraw (export) | MIT | diagramas a mão |
| Figma free tier | proprietário | quando precisar de design polido |

### Launch playbooks

| Recurso | Source | Por quê |
|---|---|---|
| **"How to launch on HN"** | [Aaron Epstein](https://news.ycombinator.com/showhn.html) regras + diversos posts mortem | timing + título |
| LangFuse launch retrospective | blog deles | OSS observability launch real |
| Show HN best practices | [paulgraham essays](http://paulgraham.com/) | clássicos |
| `OpenSauced` launch guides | [open-sauced/open-sauced](https://github.com/open-sauced/open-sauced) | OSS launch playbook |

### Análise / engagement

| Tool | License | Uso |
|---|---|---|
| Plausible | open core | analytics simples sem cookies |
| Umami | MIT | analytics self-host |
| star-history.com | free | gráfico de stars |
| repobeats.axiom.co | free | repo activity badge |

### Comunidade (Discord)

| Setup item | Source | Notas |
|---|---|---|
| Carl-bot | free tier | mod automation |
| MEE6 | free tier | level / role assignment |
| Discord templates | discordtemplates.com | server template "OSS project" |

### Blog hosting / crosspost

| Plataforma | License | Notas |
|---|---|---|
| dev.to | proprietária mas free | OSS-friendly |
| Hashnode | proprietária | crosspost canonical URL |
| Medium | proprietária | larger audience |
| Personal blog | qualquer SSG | crosspost canonical |

### Outreach: contact lists

| Lista | Fonte | Notas |
|---|---|---|
| LangChain maintainers | GitHub orgs | Harrison Chase + team |
| CrewAI core team | GitHub orgs | João Moura |
| Pydantic AI | GitHub orgs | Samuel Colvin team |
| MCP community | Discord oficial | |
| OSS AI influencers | Twitter/X listas próprias | |

### Anti-reuso

- ❌ Tema customizado tipo "from scratch" — mkdocs-material com pequenos overrides é o melhor uso de tempo
- ❌ Hosting próprio (VPS) — Cloudflare Pages é mais resiliente e grátis
- ❌ Discord bot custom Day-1 — usar Carl-bot/MEE6

### Economia estimada com reuso

| Decisão | Economia |
|---|---|
| `mkdocs-material` vs custom theme | 3-5 dias |
| Cloudflare Pages vs self-host | 1 dia inicial + manutenção contínua |
| FastAPI docs structure como template | 1-2 dias |
| `asciinema` vs video editing tools | 1 dia |
| Carl-bot vs Discord bot custom | 1-2 dias |
| **Total** | **7-10 dias economizados em 5-7 dias de fase** (i.e., fase fica viável) |

---

## Riscos e mitigações

### R5.1 — Show HN não bate (downvoted, fica fora da front page)
**Probabilidade:** média-alta
**Impacto:** médio
**Mitigação:**
- A/B test titles em sub-comunidades antes
- Não depender só de HN — Twitter + Reddit + Discord paralelos
- Re-post permitido após 1 semana se primeiro flopou (regras HN permitem)

### R5.2 — Backlash de comunidade existente (LangChain, OpenHands fans)
**Probabilidade:** média
**Impacto:** médio
**Mitigação:**
- Posicionamento "complementar, não substituto" — explícito em todo material
- COMPARISON.md transparente sobre onde competidores são melhores
- Engagement respeitoso, nunca antagonista

### R5.3 — Discovery dos limites do produto pré-alpha
**Probabilidade:** alta
**Impacto:** baixo-médio
**Mitigação:**
- Comunicar status "v0.4 production-ready mas early" explicitamente
- README badge: "early adopter friendly"
- FAQ honesta sobre o que NÃO funciona ainda

### R5.4 — Confusão com Loom (screen recording company)
**Probabilidade:** baixa
**Impacto:** baixo
**Mitigação:**
- Wake é o nome, Loom não era nosso candidato final
- SEO: "Wake AI", "Wake runtime", "Wake agent"

### R5.5 — Site cai sob tráfego (HN hug of death)
**Probabilidade:** baixa
**Impacto:** baixo
**Mitigação:**
- Cloudflare Pages + Cloudflare CDN
- Site estático puro
- Servidor de demos não atrelado ao site

### R5.6 — Algum competidor (OpenHands, MAF) lança coisa concorrente na mesma semana
**Probabilidade:** baixa
**Impacto:** alto
**Mitigação:**
- Não há mitigação direta
- Se acontecer, pode na verdade ajudar (atenção no espaço)
- Posicionar como complementar

### R5.7 — Discord community tóxica desde o dia 1
**Probabilidade:** baixa
**Impacto:** alto (long-term damage)
**Mitigação:**
- Code of Conduct claro
- Moderação proativa desde dia 1
- 2-3 mods identificados antes do launch

---

## Decisões adiadas

- ❌ Hosted Wake (SaaS comercial) — fora do escopo, OSS first
- ❌ Wake UI dashboard — Day-90 pacote separado
- ❌ Enterprise outreach formal — Day-180
- ❌ Conferência speaking — orgânico
- ❌ Sponsorship / funding — Day-365

---

## Definition of Done

- [ ] Todos os Exit Criteria checkados
- [ ] Site no ar e estável
- [ ] 3 tutorials publicados
- [ ] 2 blog posts publicados
- [ ] Show HN posted
- [ ] Twitter thread published
- [ ] Discord aberto com 50+ membros
- [ ] Retrospectiva documentada
- [ ] Tag `v0.5.0-public` em git
- [ ] Status em `phases/README.md` atualizado para 🎉 launched

---

## Métricas de sucesso

| Métrica | Mínimo (sucesso) | Meta (excelente) |
|---|---|---|
| GitHub stars (após 1 semana) | 500 | 2000 |
| Discord members | 50 | 300 |
| HN comments | 30 | 200 |
| HN upvotes | 100 | 500 |
| Site visits primeira semana | 5,000 | 25,000 |
| Issues abertas por usuários | 10 | 50 |
| PRs externos | 1 | 5 |
| Adapters de terceiros começados | 0 | 1-2 |
| Mantenedor de framework engajou | 0 | 2 |
| Empresa reportou interesse | 0 | 2-3 |

---

## Critério de falha de launch

Se após 2 semanas:

- <100 stars
- <20 Discord members
- Zero engajamento de mantenedor de framework
- Zero PRs externos

→ A tese pode estar errada. Reavaliar.

Possibilidades de pivot:
- Wake foca em ser ferramenta de coding-agent (compete com OpenHands)
- Wake foca em audit-grade compliance (nicho B2B)
- Wake descontinua e contribui de volta pra OpenHands V1 SDK

Decisão em `phases/decisions/post-launch-direction.md`.

---

## After this phase

🎉 **Wake é público.** Próximas iterações:

→ Day-90+ no roadmap original (`docs/ROADMAP.md`): consolidação, mais adapters, UI, security audit.

→ Comunidade-driven: issues, PRs, RFCs guiam priorização.

→ Não há "Phase 6" formal. A partir daqui, é manutenção + evolução baseada em uso real.
