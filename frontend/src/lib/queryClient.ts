import { QueryClient } from "@tanstack/react-query";

/**
 * Single QueryClient instance for the app. Wrapped in a function so a fresh
 * instance is created per server-render to avoid request bleed-over in RSC.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        gcTime: 5 * 60_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
