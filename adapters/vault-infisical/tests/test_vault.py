"""Tests for ``InfisicalVault`` (in-memory backend)."""

from __future__ import annotations

import pytest

from wake_vault_infisical import InfisicalVault, VaultAdapter, VaultNotFoundError
from wake_vault_infisical.base import CredentialMetadata


@pytest.fixture
def vault() -> InfisicalVault:
    return InfisicalVault(in_memory=True)


async def test_vault_subclasses_vault_adapter(vault: InfisicalVault) -> None:
    assert isinstance(vault, VaultAdapter)


async def test_add_returns_metadata_without_value(vault: InfisicalVault) -> None:
    meta = await vault.add(
        name="github_token",
        provider="github",
        value="ghp_super_secret_value",
        scopes=["repo"],
    )

    assert isinstance(meta, CredentialMetadata)
    assert meta.name == "github_token"
    assert meta.provider == "github"
    assert meta.scopes == ["repo"]
    assert meta.vault_id.startswith("vault_")
    # Critical: secret value MUST NOT appear anywhere on the returned object.
    assert "ghp_super_secret_value" not in meta.model_dump_json()


async def test_list_returns_all_entries(vault: InfisicalVault) -> None:
    await vault.add("a", "github", "value_a")
    await vault.add("b", "slack", "value_b")
    items = await vault.list()
    names = {i.name for i in items}
    assert names == {"a", "b"}
    # Same: no value leakage on list output.
    payload = " ".join(i.model_dump_json() for i in items)
    assert "value_a" not in payload
    assert "value_b" not in payload


async def test_get_metadata(vault: InfisicalVault) -> None:
    meta = await vault.add("x", "custom", "secret")
    looked_up = await vault.get_metadata(meta.vault_id)
    assert looked_up.vault_id == meta.vault_id
    assert looked_up.name == "x"


async def test_get_metadata_unknown_raises(vault: InfisicalVault) -> None:
    with pytest.raises(VaultNotFoundError):
        await vault.get_metadata("vault_does_not_exist")


async def test_proxy_token_is_opaque(vault: InfisicalVault) -> None:
    meta = await vault.add("k", "github", "real-secret-token")
    token = await vault.get_proxy_token(meta.vault_id, session_id="sess_1")
    # Proxy token must not contain the secret.
    assert "real-secret-token" not in token
    # Format check: our in-memory backend prefixes ``wkv_``.
    assert token.startswith("wkv_")


async def test_proxy_token_unique_per_call(vault: InfisicalVault) -> None:
    meta = await vault.add("k", "github", "x")
    a = await vault.get_proxy_token(meta.vault_id, "s1")
    b = await vault.get_proxy_token(meta.vault_id, "s2")
    assert a != b


async def test_proxy_token_for_unknown_vault_raises(vault: InfisicalVault) -> None:
    with pytest.raises(VaultNotFoundError):
        await vault.get_proxy_token("vault_nope", "s1")


async def test_revoke_is_idempotent(vault: InfisicalVault) -> None:
    meta = await vault.add("temp", "custom", "v")
    await vault.revoke(meta.vault_id)
    # Second revoke must not raise.
    await vault.revoke(meta.vault_id)
    # And the entry is really gone.
    with pytest.raises(VaultNotFoundError):
        await vault.get_metadata(meta.vault_id)


async def test_revoke_invalidates_existing_proxy_tokens(vault: InfisicalVault) -> None:
    meta = await vault.add("k", "github", "v")
    # Issue a proxy token then revoke; backend internal map should drop it.
    await vault.get_proxy_token(meta.vault_id, "s1")
    await vault.revoke(meta.vault_id)
    # Listing should not contain the revoked entry.
    items = await vault.list()
    assert all(i.vault_id != meta.vault_id for i in items)


async def test_metadata_carries_user_supplied_fields(vault: InfisicalVault) -> None:
    meta = await vault.add(
        "k",
        "custom",
        "v",
        metadata={"owner": "raphael", "rotation_days": 30},
    )
    assert meta.metadata == {"owner": "raphael", "rotation_days": 30}
    looked = await vault.get_metadata(meta.vault_id)
    assert looked.metadata == {"owner": "raphael", "rotation_days": 30}


async def test_create_factory_returns_in_memory_when_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFISICAL_TOKEN", raising=False)
    from wake_vault_infisical.vault import create

    vault = create()
    assert vault.memory_backend is not None
