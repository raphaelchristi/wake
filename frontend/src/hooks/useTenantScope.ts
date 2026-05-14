"use client";

import * as React from "react";

import {
  getTenantScope,
  subscribeTenantScope,
  TENANT_DEFAULTS,
  type TenantScope,
} from "@/lib/tenant";

/**
 * Hook React que devolve o `TenantScope` atual e re-renderiza quando ele
 * muda — seja por setter local (custom event) ou por outra tab (storage).
 *
 * SSR-safe: na primeira render server-side devolve `TENANT_DEFAULTS`;
 * após hydrate o `useEffect` reconcilia com o valor real do `localStorage`.
 * Isso evita mismatch quando a tab tem um scope diferente do default.
 */
export function useTenantScope(): TenantScope {
  const [scope, setScope] = React.useState<TenantScope>(TENANT_DEFAULTS);

  React.useEffect(() => {
    setScope(getTenantScope());
    const unsub = subscribeTenantScope((next) => setScope(next));
    return unsub;
  }, []);

  return scope;
}
