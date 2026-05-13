import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

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
