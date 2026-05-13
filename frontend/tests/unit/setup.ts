// Vitest unit-test setup. Augments happy-dom with Testing Library matchers
// (jest-dom) and provides a `ResizeObserver` polyfill — Recharts'
// ResponsiveContainer requires it but happy-dom does not implement it.

import "@testing-library/jest-dom/vitest";

if (typeof globalThis.ResizeObserver === "undefined") {
  // Minimal polyfill — Recharts only needs the shape, not real measurement.
  class ResizeObserverPoly {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverPoly;
}

// happy-dom doesn't seed innerWidth/innerHeight either; Recharts uses
// these via getBoundingClientRect under the hood. Inject default sizes.
if (typeof window !== "undefined") {
  Object.defineProperty(window, "innerWidth", {
    value: 1280,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(window, "innerHeight", {
    value: 800,
    writable: true,
    configurable: true,
  });
}
