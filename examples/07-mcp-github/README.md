# 07 — MCP / GitHub via agentgateway + vault

Demonstrates the **full Phase 4 egress path**: an agent that uses the
GitHub MCP server, with the `github_token` credential stored in the
Wake vault and routed through agentgateway.

## What it shows

1. `wake vault add github_token …` stores a real GitHub PAT in the vault.
2. The agent's MCP server reference uses `vault:github_token` instead
   of an actual token.
3. At runtime, the request flows:

   ```
   agent → wake-worker → agentgateway ──▶ api.github.com
                            │
                            └─── vault:github_token swap (only for whitelisted hosts)
   ```

4. The agent **never sees the real token**; it only ever holds the
   placeholder string `{{vault:github_token}}` or an opaque proxy token.

5. A second invocation tries to exfiltrate the token to an attacker
   host — verifies the egress is denied **before** any substitution
   happens.

## Prerequisites

- The Phase 4 deploy stack running locally (`docker compose up` in
  `deploy/`), OR `--mocked` to use the in-memory test scaffold.
- A GitHub personal access token with `repo` scope (only for the real-call path).

## Files

| File | Purpose |
|------|---------|
| `agentgateway.yaml` | Standalone agentgateway config exposing only `api.github.com` |
| `run.py` | Orchestrator script with `--mocked` default |

## Run (mocked)

```bash
cd examples/07-mcp-github
python run.py
```

This path makes no network calls. Asserts the exfil attempt is
denied and the legit request returns the expected payload.

## Run (real)

```bash
docker compose -f ../../deploy/docker-compose.yml up -d agentgateway infisical-vault
export GITHUB_TOKEN=ghp_xxx                            # your PAT
wake vault add github_token --provider github --value "$GITHUB_TOKEN"
python run.py --real
```

Notes:

- The vault stores the token; the script then drops the env var so
  the agent never has access.
- `agentgateway.yaml` is loaded by the compose stack via volume mount
  (see `deploy/agentgateway/config.yaml` for the canonical version).
