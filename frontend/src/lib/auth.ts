// TODO: dashboard-shell slice owns this file. This stub is a compatibility
// shim so the metrics + vault slice typechecks before the shell merges.
// When the shell lands, this file is overwritten by the shell version.

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
    /* swallow */
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
