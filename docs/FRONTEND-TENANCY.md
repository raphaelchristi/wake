# Frontend Tenancy Adjustments

Wake agora tem tenancy first-class no backend:

- `organization_id` agrupa workspaces.
- `workspace_id` é a fronteira de isolamento operacional.
- Recursos principais (`agents`, `environments`, `sessions`, `events`) carregam esses campos.
- A API aceita os headers `X-Wake-Organization-Id` e `X-Wake-Workspace-Id`.
- Quando os headers não são enviados, o backend usa `default/default` para manter compatibilidade com dev e single-tenant.

Este documento lista apenas os ajustes necessários no frontend para usar essa fundação.

## Objetivo

Fazer o dashboard operar dentro de um workspace explícito, sem vazar dados entre workspaces via requests, cache, SSE ou fixtures tipadas.

## 1. Enviar headers de tenant no API client

Arquivo principal:

- `frontend/src/lib/api/client.ts`

Hoje o client injeta apenas:

```ts
X-Wake-API-Key
```

Adicionar também:

```ts
X-Wake-Organization-Id
X-Wake-Workspace-Id
```

Recomendação inicial:

- criar uma pequena helper em `frontend/src/lib/tenant.ts`;
- ler `organization_id` e `workspace_id` de `localStorage`;
- cair para `default/default` quando ausente;
- permitir override via `WakeApiClient` options para SSR/testes.

Exemplo de contrato desejado:

```ts
export interface TenantScope {
  organizationId: string;
  workspaceId: string;
}

export function getTenantScope(): TenantScope {
  return {
    organizationId: window.localStorage.getItem("wake.organization_id") ?? "default",
    workspaceId: window.localStorage.getItem("wake.workspace_id") ?? "default",
  };
}
```

O `WakeApiClient.headers()` deve setar os dois headers em todas as rotas autenticadas.

## 2. Atualizar tipos gerados/stubs

Arquivo:

- `frontend/src/lib/api/generated.ts`

Adicionar em `Session`, `AgentConfig` e `Event`:

```ts
organization_id: string;
workspace_id: string;
```

Também revisar tipos derivados/importados por:

- `frontend/src/lib/api/types.ts`
- `frontend/src/lib/replay/types.ts`
- fixtures em `frontend/tests/fixtures/`

## 3. Ajustar cache keys do TanStack Query

Qualquer query que retorna dados escopados por workspace deve incluir o workspace atual na key.

Exemplos:

- `["sessions", workspaceId, filters]`
- `["session", workspaceId, sessionId]`
- `["events", workspaceId, sessionId]`
- `["state-at", workspaceId, sessionId, seq]`
- `["metrics", workspaceId, window]`
- `["workers", workspaceId]`
- `["agents", workspaceId]`

Arquivos prováveis:

- `frontend/src/hooks/useSessions.ts`
- `frontend/src/hooks/useSession.ts`
- `frontend/src/hooks/useEvents.ts`
- `frontend/src/hooks/useStateAt.ts`
- `frontend/src/hooks/useMetrics.ts`
- `frontend/src/hooks/useWorkers.ts`

Sem isso, trocar de workspace pode reaproveitar cache do workspace anterior.

## 4. Resolver SSE com tenant headers

Arquivos:

- `frontend/src/lib/sse.ts`
- `frontend/src/hooks/useSSE.ts`
- `frontend/src/app/(authed)/sessions/[id]/replay/page.tsx`

O browser `EventSource` não permite headers customizados. Como o backend agora usa headers para tenant scope, o frontend precisa de uma dessas abordagens:

### Opção recomendada: proxy Next.js

Criar uma rota Next.js, por exemplo:

```txt
/api/wake/sessions/[id]/stream
```

Essa rota:

- lê tenant scope do lado servidor ou de query params controlados;
- injeta `X-Wake-API-Key`, `X-Wake-Organization-Id` e `X-Wake-Workspace-Id`;
- faz proxy para o backend Wake;
- repassa o stream SSE para o browser.

O browser então abre `EventSource` contra o próprio Next.js, sem precisar de headers customizados.

### Alternativa: fetch-based SSE

Substituir `EventSource` por uma implementação baseada em `fetch()` + `ReadableStream`, porque `fetch` permite headers. É mais código e precisa tratar reconexão manualmente.

## 5. UI para selecionar workspace

Para operação multi-tenant real, o dashboard precisa saber qual workspace está ativo.

Opções:

- simples: inputs no login para `organization_id` e `workspace_id`;
- melhor: seletor no topbar com workspace atual;
- produção: SSO/reverse proxy injeta o tenant e o dashboard apenas exibe o escopo.

Primeiro passo pragmático:

- guardar `wake.organization_id` e `wake.workspace_id` no `localStorage`;
- mostrar o workspace atual no topbar;
- limpar/invalidate queries quando o workspace muda.

Arquivos prováveis:

- `frontend/src/app/login/page.tsx`
- `frontend/src/components/layout/Topbar.tsx`
- `frontend/src/app/providers.tsx`
- `frontend/src/lib/queryClient.ts`

## 6. OAuth callback proxy

Arquivo:

- `frontend/src/app/oauth/callback/api/route.ts`

Hoje a rota injeta `X-Wake-API-Key` quando `WAKE_API_KEY` existe.

Ela também deve encaminhar ou injetar:

```ts
X-Wake-Organization-Id
X-Wake-Workspace-Id
```

Sem isso, credenciais/vault podem cair no workspace `default` enquanto o usuário opera outro workspace.

## 7. Testes a adicionar/ajustar

Atualizar:

- `frontend/tests/unit/api-client.test.ts`
- `frontend/tests/fixtures/sessions.ts`
- testes de hooks que usam query keys
- e2e mocks em `frontend/tests/e2e/*.spec.ts`

Casos mínimos:

- API client envia `X-Wake-Organization-Id` e `X-Wake-Workspace-Id`.
- API client usa `default/default` quando tenant não foi configurado.
- query keys mudam quando `workspaceId` muda.
- fixtures incluem `organization_id` e `workspace_id`.
- SSE usa o proxy/estratégia escolhida com tenant preservado.

## 8. Critério de aceite

O frontend estará alinhado com o backend quando:

- toda request HTTP autenticada enviar API key + tenant scope;
- nenhuma lista/detalhe/event stream compartilhar cache entre workspaces;
- tipos TS refletirem `organization_id` e `workspace_id`;
- replay/SSE funcionar dentro do workspace correto;
- OAuth/vault não gravar dados acidentalmente em `default/default`;
- testes cobrirem ao menos dois workspaces distintos.

