import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { WorkspaceSelector } from "@/components/workspace/WorkspaceSelector";
import { getTenantScope, setTenantScope } from "@/lib/tenant";

describe("WorkspaceSelector", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the current scope in the trigger", () => {
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    render(<WorkspaceSelector />);
    const trigger = screen.getByTestId("workspace-selector-trigger");
    expect(trigger.textContent).toContain("acme");
    expect(trigger.textContent).toContain("prod");
  });

  it("opens the dropdown and lists options", () => {
    render(
      <WorkspaceSelector
        options={[
          { organizationId: "default", workspaceId: "default" },
          { organizationId: "acme", workspaceId: "prod" },
        ]}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-selector-trigger"));
    expect(screen.getByTestId("workspace-selector-menu")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-option-default/default")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-option-acme/prod")).toBeInTheDocument();
  });

  it("opens switch confirmation when selecting a different workspace", () => {
    render(
      <WorkspaceSelector
        options={[
          { organizationId: "default", workspaceId: "default" },
          { organizationId: "acme", workspaceId: "prod" },
        ]}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-selector-trigger"));
    fireEvent.click(screen.getByTestId("workspace-option-acme/prod"));
    // Dialog renders confirm button
    expect(screen.getByTestId("workspace-switch-confirm")).toBeInTheDocument();
    // Tenant scope ainda é o padrão até confirm.
    expect(getTenantScope()).toEqual({
      organizationId: "default",
      workspaceId: "default",
    });
  });

  it("commits the scope on confirm", () => {
    render(
      <WorkspaceSelector
        options={[
          { organizationId: "default", workspaceId: "default" },
          { organizationId: "acme", workspaceId: "prod" },
        ]}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-selector-trigger"));
    fireEvent.click(screen.getByTestId("workspace-option-acme/prod"));
    fireEvent.click(screen.getByTestId("workspace-switch-confirm"));
    expect(getTenantScope()).toEqual({
      organizationId: "acme",
      workspaceId: "prod",
    });
  });

  it("cancels switch without changing scope", () => {
    render(
      <WorkspaceSelector
        options={[
          { organizationId: "default", workspaceId: "default" },
          { organizationId: "acme", workspaceId: "prod" },
        ]}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-selector-trigger"));
    fireEvent.click(screen.getByTestId("workspace-option-acme/prod"));
    fireEvent.click(screen.getByTestId("workspace-switch-cancel"));
    expect(getTenantScope()).toEqual({
      organizationId: "default",
      workspaceId: "default",
    });
  });

  it("selecting the current workspace is a no-op (no dialog)", () => {
    render(
      <WorkspaceSelector
        options={[{ organizationId: "default", workspaceId: "default" }]}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-selector-trigger"));
    fireEvent.click(screen.getByTestId("workspace-option-default/default"));
    expect(screen.queryByTestId("workspace-switch-confirm")).not.toBeInTheDocument();
  });

  it("includes current scope in options when not in passed list", () => {
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    render(
      <WorkspaceSelector
        options={[{ organizationId: "default", workspaceId: "default" }]}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-selector-trigger"));
    expect(screen.getByTestId("workspace-option-acme/prod")).toBeInTheDocument();
  });
});
