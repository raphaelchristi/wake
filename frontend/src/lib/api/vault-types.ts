// Hand-written types mirroring the backend vault routes
// (`src/wake/api/routes/vault.py`). Lives alongside the OpenAPI-generated
// types so this slice can render the vault UI before codegen runs.

export type VaultProvider = "github" | "slack" | "notion" | "custom";

export interface VaultCredential {
  vault_id: string;
  name: string;
  provider: VaultProvider | string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  metadata: Record<string, unknown>;
}

export interface CredentialList {
  data: VaultCredential[];
}

export interface OAuthStartRequest {
  provider: VaultProvider | string;
  scopes?: string[];
  redirect_uri?: string;
}

export interface OAuthStartResponse {
  provider: string;
  auth_url: string;
  state: string;
}

export interface RotateRequest {
  redirect_uri?: string;
}

export type AuditDecision =
  | "oauth_start"
  | "oauth_success"
  | "oauth_failed"
  | "rotate_started"
  | "revoked"
  | "allow"
  | "deny"
  | string;

export interface AuditEntry {
  timestamp: string;
  session_id: string | null;
  provider: string | null;
  host: string | null;
  decision: AuditDecision;
  vault_id: string | null;
  detail: string | null;
}

export interface AuditList {
  data: AuditEntry[];
}
