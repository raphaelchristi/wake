import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CredentialsList } from "@/components/vault/CredentialsList";
import { AuditLog } from "@/components/vault/AuditLog";
import { ProviderIcon } from "@/components/vault/ProviderIcon";
import type {
  AuditEntry,
  VaultCredential,
} from "@/lib/api/vault-types";

const credential: VaultCredential = {
  vault_id: "v_abc123",
  name: "github_token_demo",
  provider: "github",
  scopes: ["repo", "read:user"],
  created_at: new Date(Date.now() - 60_000).toISOString(),
  expires_at: null,
  metadata: { last_used_at: new Date().toISOString() },
};

describe("CredentialsList", () => {
  it("renders the empty state when no credentials are present", () => {
    render(<CredentialsList credentials={[]} />);
    expect(
      screen.getByTestId("credentials-list-empty"),
    ).toBeInTheDocument();
  });

  it("renders rows with name + provider + scopes", () => {
    render(<CredentialsList credentials={[credential]} />);
    expect(screen.getByText("github_token_demo")).toBeInTheDocument();
    expect(screen.getByText("repo")).toBeInTheDocument();
    expect(screen.getByText("read:user")).toBeInTheDocument();
    expect(screen.getAllByTestId("credential-row")).toHaveLength(1);
  });

  it("calls onRotate and onRevoke with the credential", async () => {
    const onRotate = vi.fn();
    const onRevoke = vi.fn();
    const user = userEvent.setup();
    render(
      <CredentialsList
        credentials={[credential]}
        onRotate={onRotate}
        onRevoke={onRevoke}
      />,
    );

    await user.click(screen.getByLabelText(/rotate github_token_demo/i));
    expect(onRotate).toHaveBeenCalledWith(credential);

    await user.click(screen.getByLabelText(/revoke github_token_demo/i));
    expect(onRevoke).toHaveBeenCalledWith(credential);
  });

  it("renders the loading skeleton", () => {
    render(<CredentialsList credentials={[]} isLoading />);
    expect(
      screen.getByTestId("credentials-list-loading"),
    ).toBeInTheDocument();
  });
});

describe("AuditLog", () => {
  const baseEntry: AuditEntry = {
    timestamp: new Date().toISOString(),
    session_id: "01HZX0EXAMPLE",
    provider: "github",
    host: "api.github.com",
    decision: "allow",
    vault_id: "v_abc",
    detail: null,
  };

  it("shows an offline-specific empty state when offline=true", () => {
    render(<AuditLog entries={[]} offline />);
    expect(screen.getByTestId("audit-offline")).toBeInTheDocument();
  });

  it("shows an error message when error provided", () => {
    render(<AuditLog entries={[]} error={new Error("nope")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("nope");
  });

  it("shows the truly-empty state separately from offline", () => {
    render(<AuditLog entries={[]} />);
    expect(screen.getByTestId("audit-empty")).toBeInTheDocument();
  });

  it("renders entries with decision badge and host", () => {
    render(<AuditLog entries={[baseEntry, { ...baseEntry, decision: "deny" }]} />);
    const rows = screen.getAllByTestId("audit-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-decision", "allow");
    expect(rows[1]).toHaveAttribute("data-decision", "deny");
    expect(screen.getAllByText("api.github.com").length).toBeGreaterThan(0);
  });
});

describe("ProviderIcon", () => {
  it("renders the github glyph for provider=github", () => {
    const { container } = render(<ProviderIcon provider="github" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("falls back to a generic key glyph for unknown providers", () => {
    const { container } = render(<ProviderIcon provider="zoom" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
