import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearTenantScope,
  getTenantScope,
  setTenantScope,
  subscribeTenantScope,
  TENANT_DEFAULTS,
  TENANT_SCOPE_EVENT,
} from "@/lib/tenant";

describe("tenant scope", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("getTenantScope falls back to default/default when nothing is persisted", () => {
    expect(getTenantScope()).toEqual({
      organizationId: "default",
      workspaceId: "default",
    });
    expect(TENANT_DEFAULTS).toEqual({
      organizationId: "default",
      workspaceId: "default",
    });
  });

  it("getTenantScope returns persisted values from localStorage", () => {
    window.localStorage.setItem("wake.organization_id", "acme");
    window.localStorage.setItem("wake.workspace_id", "prod");
    expect(getTenantScope()).toEqual({
      organizationId: "acme",
      workspaceId: "prod",
    });
  });

  it("setTenantScope persists values and emits custom event", () => {
    const listener = vi.fn();
    window.addEventListener(TENANT_SCOPE_EVENT, listener);
    const result = setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    expect(result).toEqual({ organizationId: "acme", workspaceId: "prod" });
    expect(window.localStorage.getItem("wake.organization_id")).toBe("acme");
    expect(window.localStorage.getItem("wake.workspace_id")).toBe("prod");
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(TENANT_SCOPE_EVENT, listener);
  });

  it("setTenantScope accepts partial updates (keeps other axis)", () => {
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    setTenantScope({ workspaceId: "staging" });
    expect(getTenantScope()).toEqual({
      organizationId: "acme",
      workspaceId: "staging",
    });
  });

  it("setTenantScope collapses empty strings to default", () => {
    setTenantScope({ organizationId: "", workspaceId: "" });
    expect(getTenantScope()).toEqual({
      organizationId: "default",
      workspaceId: "default",
    });
  });

  it("clearTenantScope removes persisted values", () => {
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    clearTenantScope();
    expect(window.localStorage.getItem("wake.organization_id")).toBeNull();
    expect(window.localStorage.getItem("wake.workspace_id")).toBeNull();
    expect(getTenantScope()).toEqual(TENANT_DEFAULTS);
  });

  it("subscribeTenantScope notifies on setTenantScope and returns unsubscribe", () => {
    const calls: Array<{ organizationId: string; workspaceId: string }> = [];
    const unsub = subscribeTenantScope((scope) => calls.push(scope));
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    expect(calls).toEqual([{ organizationId: "acme", workspaceId: "prod" }]);
    unsub();
    setTenantScope({ workspaceId: "staging" });
    // Still one — unsubscribed before second emit.
    expect(calls).toHaveLength(1);
  });

  it("trims whitespace on set", () => {
    setTenantScope({ organizationId: "  acme  ", workspaceId: "  prod  " });
    expect(getTenantScope()).toEqual({
      organizationId: "acme",
      workspaceId: "prod",
    });
  });
});
