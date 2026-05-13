# wake-vault-infisical

Wake VaultAdapter backed by [Infisical Agent Vault](https://github.com/Infisical/agent-vault).
Phase 4 component.

## What it does

Stores agent credentials (API tokens, OAuth refresh tokens) **outside**
agent process memory. Agent code only ever sees an opaque proxy token
or a `{{vault:name}}` placeholder; the real value lives in the vault.

The HTTPS MITM egress proxy (Infisical Agent Vault in production,
agentgateway as the L7 routing layer) swaps placeholders / proxy tokens
for real secrets **only at egress time** and **only for hosts in the
allowed_hosts list**.

Prompt-injection attacks that try to exfiltrate `$GITHUB_TOKEN` via a
malicious tool call therefore fail in two stages:

1. The agent never had the raw token (it had a placeholder).
2. Even if it could resolve the placeholder, attacker-controlled hosts
   are not in `allowed_hosts`, so the proxy refuses the request before
   substitution.

## Install

```bash
pip install -e adapters/vault-infisical
```

Adds two console entry points:

* `wake vault` subcommand (auto-discovered through the
  `wake.cli` group).
* `infisical` registered under `wake.vaults` for runtime discovery.

## Quick start

```bash
# In-memory fallback (dev / testing — never use in prod):
wake vault init --in-memory
wake vault add github_token --provider github --value ghp_xxx --in-memory
wake vault list --in-memory
```

With Infisical running as a sidecar:

```bash
export INFISICAL_URL=http://localhost:8200
export INFISICAL_TOKEN=...
export INFISICAL_PROJECT_ID=wake

wake vault init
wake vault add github_token --provider github --oauth \
  --client-id $GITHUB_OAUTH_CLIENT_ID \
  --client-secret $GITHUB_OAUTH_CLIENT_SECRET
```

## Python API

```python
from wake_vault_infisical import InfisicalVault, OAuthFlow

vault = InfisicalVault(in_memory=True)

# Store a token (post-OAuth, or directly).
meta = await vault.add(
    name="github_token",
    provider="github",
    value="ghp_xxx",
    scopes=["repo", "read:user"],
)

# Issue a per-session proxy token. The agent sees this, not the real value.
proxy_token = await vault.get_proxy_token(meta.vault_id, session_id="sess_123")
```

## OAuth providers

Built-in:

| Provider | scopes default | scope separator |
|----------|----------------|-----------------|
| `github` | `repo, read:user` | space |
| `slack`  | `chat:write, channels:read` | comma |
| `notion` | none (workspace-scoped) | — |

`OAuthProvider` is a frozen dataclass — register your own with
`register_provider(OAuthProvider(...))`.

## Egress proxy contract

`VaultProxy` is the unit-testable in-process implementation of the
proxy contract:

```python
from wake_vault_infisical import VaultProxy, ProxyConfig

proxy = VaultProxy(
    vault,
    ProxyConfig(allowed_hosts=["api.github.com"]),
)

# substitutes {{vault:github_token}} only if the host is whitelisted
body = await proxy.handle_request(
    "api.github.com",
    'Authorization: Bearer {{vault:github_token}}',
)
```

Calling `handle_request("attacker.com", ...)` raises `EgressDenied`
**before** any substitution happens.

In production deployments, agentgateway (the Rust binary) performs the
real substitution; this Python helper exists so unit tests can verify
the contract on every commit.

## Tests

```bash
pytest adapters/vault-infisical/tests/ -q
```

Tests run against the in-memory backend and `responses`-mocked OAuth
endpoints — no real services required.

## Security checklist

- [x] Credential values never logged (only presence + length).
- [x] Empty `allowed_hosts` denies egress (fail closed).
- [x] CSRF `state` checked on OAuth callback.
- [x] Revoke is idempotent (cleanup workflows can re-run safely).
- [x] Per-session proxy tokens are opaque and short-lived.
