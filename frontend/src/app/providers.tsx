"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/queryClient";
import { getTenantScope, subscribeTenantScope } from "@/lib/tenant";

/**
 * Tenancy-aware Providers:
 *   - Mantém o `QueryClient` único da app.
 *   - Observa mudanças no `tenantScope`. Quando o workspace muda,
 *     `queryClient.clear()` apaga todo cache (evita vazamento de dados
 *     entre tenants) e o router redireciona para `/sessions` para
 *     começar a nova sessão de navegação a partir de uma landing page
 *     que existe em todo workspace.
 *   - O primeiro tick (mount) inicializa `lastScopeRef` sem clear/push,
 *     para não disparar redirect indevido no boot.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  const router = useRouter();
  const lastScopeRef = useRef<{ org: string; ws: string } | null>(null);

  useEffect(() => {
    // Inicializa após hydrate.
    if (lastScopeRef.current === null) {
      const initial = getTenantScope();
      lastScopeRef.current = {
        org: initial.organizationId,
        ws: initial.workspaceId,
      };
    }
    const unsub = subscribeTenantScope((next) => {
      const prev = lastScopeRef.current;
      const changed =
        !prev ||
        prev.org !== next.organizationId ||
        prev.ws !== next.workspaceId;
      lastScopeRef.current = {
        org: next.organizationId,
        ws: next.workspaceId,
      };
      if (changed) {
        client.clear();
        router.push("/sessions");
      }
    });
    return unsub;
  }, [client, router]);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
