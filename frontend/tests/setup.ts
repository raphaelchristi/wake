import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

// jsdom doesn't ship matchMedia or ResizeObserver; stub for components that
// query them (e.g. timeline width measurement).
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

(globalThis as unknown as { ResizeObserver: typeof ResizeObserverMock }).ResizeObserver =
  ResizeObserverMock;

// jsdom doesn't implement Element.scrollIntoView; stub so EventList's
// auto-scroll effect runs without throwing.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    /* no-op */
  };
}
