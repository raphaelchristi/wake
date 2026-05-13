/**
 * Auth state for the operator dashboard.
 *
 * Phase 5 keeps things deliberately simple: a single API key persisted in
 * localStorage. OAuth and per-user auth land in v1.1. The key is read on
 * every request by the API client and sent as `X-Wake-API-Key`.
 */

const STORAGE_KEY = "wake.api_key";

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setApiKey(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, key);
  } catch {
    /* swallow — quota / private mode */
  }
}

export function clearApiKey(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* swallow */
  }
}

export function isAuthenticated(): boolean {
  return getApiKey() !== null;
}
