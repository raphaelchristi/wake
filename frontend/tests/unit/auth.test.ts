import { beforeEach, describe, expect, it } from "vitest";

import { clearApiKey, getApiKey, isAuthenticated, setApiKey } from "@/lib/auth";

describe("auth", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(getApiKey()).toBeNull();
    expect(isAuthenticated()).toBe(false);
  });

  it("persists and retrieves an API key", () => {
    setApiKey("wake_test_123");
    expect(getApiKey()).toBe("wake_test_123");
    expect(isAuthenticated()).toBe(true);
  });

  it("clearApiKey removes the key", () => {
    setApiKey("wake_test_123");
    clearApiKey();
    expect(getApiKey()).toBeNull();
    expect(isAuthenticated()).toBe(false);
  });
});
