import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// happy-dom in some versions ships a localStorage proxy without `clear`.
// Replace it with a plain Map-backed Storage when missing methods.
beforeAll(() => {
  const needsStub =
    typeof globalThis.localStorage === "undefined" ||
    typeof globalThis.localStorage.clear !== "function";
  if (needsStub) {
    const store = new Map<string, string>();
    const stub: Storage = {
      get length() {
        return store.size;
      },
      clear: () => store.clear(),
      getItem: (k) => store.get(k) ?? null,
      key: (i) => Array.from(store.keys())[i] ?? null,
      removeItem: (k) => void store.delete(k),
      setItem: (k, v) => void store.set(k, String(v)),
    };
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      writable: true,
      value: stub,
    });
    if (typeof window !== "undefined") {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        writable: true,
        value: stub,
      });
    }
  }
});

// happy-dom doesn't ship matchMedia by default; stub it for components that
// might use it via libraries.
if (typeof globalThis.matchMedia !== "function") {
  Object.defineProperty(globalThis, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })),
  });
}

afterEach(() => {
  cleanup();
  // Clear localStorage between tests so auth state doesn't leak.
  try {
    globalThis.localStorage?.clear();
  } catch {
    /* ignore */
  }
});
