# 08 — Vault credentials (OAuth flow → vault → placeholder)

Demonstrates the full credential lifecycle:

1. User starts a GitHub OAuth flow via `wake vault add … --oauth`.
2. The browser redirects, user authorizes, code lands at the callback.
3. The OAuth helper exchanges the code for an access token (server side).
4. The token is stored in the vault — agent code **never** sees it.
5. The agent references the credential by name (`{{vault:github_token}}`).
6. agentgateway substitutes the placeholder only on egress to
   `allowed_hosts`.

## Run (mocked — no real GitHub)

```bash
cd examples/08-vault-credentials
python run.py
```

The mocked path uses `httpx.MockTransport` to simulate the GitHub
token endpoint. No browser, no network. The whole flow runs in <1s
and asserts:

- OAuth `state` (CSRF) check enforced.
- Token never appears in `caplog` or returned metadata.
- The stored credential resolves to the real value only inside the
  egress proxy, only for whitelisted hosts.

## Run (real, interactive)

```bash
# Bring up infisical + agentgateway:
docker compose -f ../../deploy/docker-compose.yml up -d infisical-vault agentgateway

export GITHUB_OAUTH_CLIENT_ID=...
export GITHUB_OAUTH_CLIENT_SECRET=...

# Interactive OAuth — wake vault opens browser, you paste the ?code
# parameter back at the prompt.
wake vault add github_token --provider github --oauth \
  --client-id $GITHUB_OAUTH_CLIENT_ID \
  --client-secret $GITHUB_OAUTH_CLIENT_SECRET

wake vault list
```

After the token is in the vault, point your favourite Wake example
at `agentgateway` (set `WAKE_AGENTGATEWAY_URL=http://localhost:8888`)
and watch the agent transparently authenticate against the GitHub MCP
server.

## Files

- `run.py` — orchestrator (mocked by default; `--real` for live OAuth).
- README (this file).
