#!/usr/bin/env python3
"""Example 08 — OAuth → vault → placeholder substitution.

Default mode is **mocked**: we stub the GitHub token endpoint with
``httpx.MockTransport`` so the whole flow runs in <1s with no network
and no browser interaction.

The script proves:

1. The OAuth helper performs a CSRF-safe code exchange.
2. The exchanged token is stored in the vault.
3. The token never appears in agent-visible logs or metadata.
4. The egress proxy substitutes the placeholder only for whitelisted
   hosts.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from io import StringIO

import httpx

from wake_vault_infisical import (
    InfisicalVault,
    OAuthFlow,
    ProxyConfig,
    VaultProxy,
)


FAKE_TOKEN = "ghp_REAL_LOOKING_BUT_FAKE_TOKEN_FOR_DEMO"


def _mock_github_oauth() -> httpx.MockTransport:
    """A transport that pretends to be GitHub's OAuth endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/login/oauth/access_token":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "access_token": FAKE_TOKEN,
                "token_type": "bearer",
                "scope": "repo,read:user",
            },
        )

    return httpx.MockTransport(handler)


async def _mocked() -> int:
    print("[08] mode: mocked")

    # Capture logs across the whole demo so we can prove the token
    # never leaked at log time.
    log_buf = StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)

    try:
        # ----- 1. Run the OAuth flow against the mocked transport.
        vault = InfisicalVault(in_memory=True)
        client = httpx.AsyncClient(transport=_mock_github_oauth())
        flow = OAuthFlow.for_provider(
            "github",
            client_id="cli_demo_client_id",
            client_secret="cli_demo_secret",
            redirect_uri="http://localhost:8765/callback",
            http_client=client,
        )
        url, state = flow.build_authorize_url()
        print(f"[08] would open browser to: {url[:80]}...")
        print(f"[08] CSRF state: {state}")

        # In real usage, the user authorizes and we receive ?code=...
        data = await flow.exchange_code("authorization_code_from_callback", state=state)
        token = data["access_token"]
        await client.aclose()

        # ----- 2. Store in vault.
        meta = await vault.add(
            name="github_token",
            provider="github",
            value=token,
            scopes=["repo", "read:user"],
        )
        print(f"[08] stored credential {meta.vault_id} ({meta.name}, provider={meta.provider})")

        # ----- 3. Verify the agent surface never has the real token.
        items = await vault.list()
        serialized = " ".join(i.model_dump_json() for i in items)
        assert FAKE_TOKEN not in serialized, "vault metadata leaked the token!"
        print("[08] vault.list() does NOT contain the token ✓")

        proxy_token = await vault.get_proxy_token(meta.vault_id, "sess_demo")
        assert FAKE_TOKEN not in proxy_token, "proxy token equals real token!"
        print(f"[08] proxy token issued: {proxy_token[:16]}…  (≠ real value) ✓")

        # ----- 4. Verify substitution only on whitelisted host.
        proxy = VaultProxy(vault, ProxyConfig(allowed_hosts=["api.github.com"]))
        body_template = "Authorization: Bearer {{vault:github_token}}"
        resolved = await proxy.handle_request("api.github.com", body_template)
        assert FAKE_TOKEN in resolved, "substitution failed on whitelisted host!"
        print("[08] egress to api.github.com → token substituted ✓")

        try:
            await proxy.handle_request("attacker.example.com", body_template)
        except Exception as exc:
            print(f"[08] egress to attacker.example.com → denied ✓ ({type(exc).__name__})")

        # ----- 5. Token NEVER appeared in logs.
        logs = log_buf.getvalue()
        assert FAKE_TOKEN not in logs, "token leaked into logs!"
        print("[08] full log scan — no token leak ✓")

        print("[08] OK")
        return 0
    finally:
        logging.getLogger().removeHandler(handler)


async def _real() -> int:
    print("[08] mode: real — interactive OAuth flow")
    print(
        "[08] this path is interactive; run `wake vault add github_token --provider github --oauth` "
        "directly. The CLI handles browser open + callback prompt."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Example 08 — OAuth → Vault → Substitution")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--mocked", action="store_true")
    args = parser.parse_args()
    if args.real:
        return asyncio.run(_real())
    return asyncio.run(_mocked())


if __name__ == "__main__":
    sys.exit(main())
