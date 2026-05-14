/**
 * Tenant scope (organization + workspace) — fonte de verdade no browser
 * para os headers `X-Wake-Organization-Id` e `X-Wake-Workspace-Id`.
 *
 * Modelo:
 *   - persistência local via `localStorage` (chaves abaixo);
 *   - fallback `default/default` quando os valores não foram configurados,
 *     o que mantém o dashboard usável em dev/single-tenant sem onboarding;
 *   - SSR seguro (typeof window guard) — retorna defaults se rodando no
 *     servidor;
 *   - subscribers via `subscribeTenantScope` para que o provider de
 *     React invalide o cache quando o scope muda em outra tab.
 *
 * O design segue o que `frontend/src/lib/auth.ts` já fazia para a API key.
 */
const ORGANIZATION_KEY = "wake.organization_id";
const WORKSPACE_KEY = "wake.workspace_id";

const DEFAULT_ORGANIZATION_ID = "default";
const DEFAULT_WORKSPACE_ID = "default";

export const TENANT_SCOPE_EVENT = "wake:tenant-scope-changed";

export interface TenantScope {
  organizationId: string;
  workspaceId: string;
}

/**
 * Lê o scope atual do `localStorage`. Sempre retorna valores não vazios —
 * cai para `default/default` quando não há nada salvo ou quando o storage
 * lança (modo privado, quota, SSR).
 */
export function getTenantScope(): TenantScope {
  if (typeof window === "undefined") {
    return {
      organizationId: DEFAULT_ORGANIZATION_ID,
      workspaceId: DEFAULT_WORKSPACE_ID,
    };
  }
  try {
    const org = window.localStorage.getItem(ORGANIZATION_KEY);
    const ws = window.localStorage.getItem(WORKSPACE_KEY);
    return {
      organizationId: org && org.length > 0 ? org : DEFAULT_ORGANIZATION_ID,
      workspaceId: ws && ws.length > 0 ? ws : DEFAULT_WORKSPACE_ID,
    };
  } catch {
    return {
      organizationId: DEFAULT_ORGANIZATION_ID,
      workspaceId: DEFAULT_WORKSPACE_ID,
    };
  }
}

/**
 * Persiste o scope no `localStorage` e emite um evento custom para que o
 * provider re-fetch/limpe cache. Aceita parciais para permitir trocar
 * apenas o workspace mantendo a organização.
 */
export function setTenantScope(scope: Partial<TenantScope>): TenantScope {
  if (typeof window === "undefined") {
    return getTenantScope();
  }
  const current = getTenantScope();
  const next: TenantScope = {
    organizationId: (scope.organizationId ?? current.organizationId).trim(),
    workspaceId: (scope.workspaceId ?? current.workspaceId).trim(),
  };
  // Empty string colapsa para default — backend trata empty como 400,
  // então nunca deixamos persistir vazio.
  if (next.organizationId.length === 0) next.organizationId = DEFAULT_ORGANIZATION_ID;
  if (next.workspaceId.length === 0) next.workspaceId = DEFAULT_WORKSPACE_ID;
  try {
    window.localStorage.setItem(ORGANIZATION_KEY, next.organizationId);
    window.localStorage.setItem(WORKSPACE_KEY, next.workspaceId);
  } catch {
    /* quota / private mode — swallow */
  }
  try {
    window.dispatchEvent(
      new CustomEvent<TenantScope>(TENANT_SCOPE_EVENT, { detail: next }),
    );
  } catch {
    /* ignore — older runtimes without CustomEvent */
  }
  return next;
}

/**
 * Limpa o scope (volta a `default/default`). Usado no logout para evitar
 * que outra credencial herde um workspace alheio.
 */
export function clearTenantScope(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ORGANIZATION_KEY);
    window.localStorage.removeItem(WORKSPACE_KEY);
  } catch {
    /* swallow */
  }
  try {
    window.dispatchEvent(
      new CustomEvent<TenantScope>(TENANT_SCOPE_EVENT, {
        detail: {
          organizationId: DEFAULT_ORGANIZATION_ID,
          workspaceId: DEFAULT_WORKSPACE_ID,
        },
      }),
    );
  } catch {
    /* ignore */
  }
}

/**
 * Inscrição em mudanças do scope. Retorna `unsubscribe` idempotente.
 * Escuta tanto o evento custom (mudança nessa tab) quanto `storage` (outra tab).
 */
export function subscribeTenantScope(
  listener: (scope: TenantScope) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onCustom = (event: Event) => {
    const detail = (event as CustomEvent<TenantScope>).detail;
    if (detail) {
      listener(detail);
    } else {
      listener(getTenantScope());
    }
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === ORGANIZATION_KEY || event.key === WORKSPACE_KEY) {
      listener(getTenantScope());
    }
  };
  window.addEventListener(TENANT_SCOPE_EVENT, onCustom);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(TENANT_SCOPE_EVENT, onCustom);
    window.removeEventListener("storage", onStorage);
  };
}

/**
 * Hook React de leitura. Mantemos fora de `tenant.ts` para que a helper
 * pura possa ser usada de qualquer lugar (server actions, testes),
 * mas exportamos um wrapper aqui para ergonomia.
 *
 * Implementado via React import lazy (sem `"use client"` no arquivo todo,
 * que segue server-safe). Componentes que precisarem reagir a mudança
 * importam `useTenantScope` em arquivos client; aqui apenas expomos o
 * shape para o tipo.
 */
export const TENANT_DEFAULTS: TenantScope = {
  organizationId: DEFAULT_ORGANIZATION_ID,
  workspaceId: DEFAULT_WORKSPACE_ID,
};
