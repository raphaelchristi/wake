/**
 * STUB — owned by dashboard-shell.
 *
 * The shell slice ships the real (authed) layout — auth gate redirecting to
 * /login if no API key in localStorage, sidebar + topbar shell, theme
 * provider. This stub exists ONLY so the replay slice's Next.js build
 * succeeds in isolation: it provides the QueryClientProvider that
 * `useEvents` / `useStateAt` need.
 *
 * TODO(dashboard-shell merge): delete this stub.
 */
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export default function AuthedLayout({
  children,
}: {
  children: ReactNode;
}): React.ReactElement {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
