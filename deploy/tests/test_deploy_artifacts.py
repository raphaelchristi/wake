"""Smoke tests for deploy/ artefacts.

Validates that the docker-compose and Helm chart files parse cleanly
and reference each other consistently. Real-binary checks (`docker compose
config`, `helm lint`) are run when the relevant tools are present;
otherwise the test exercises the YAML parser equivalent and skips the
CLI-specific bits.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parent.parent


def _load(path: Path) -> dict[str, object]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


# ----- Compose -------------------------------------------------------------


def test_docker_compose_parses() -> None:
    data = _load(DEPLOY / "docker-compose.yml")
    services = data["services"]
    assert isinstance(services, dict)
    expected = {
        "postgres",
        "redis",
        "agentgateway",
        "infisical-vault",
        "wake-api",
        "wake-worker",
    }
    assert expected.issubset(services.keys()), services.keys()


def test_docker_compose_dev_overlay_parses() -> None:
    data = _load(DEPLOY / "docker-compose.dev.yml")
    assert "wake-api" in data["services"]
    assert "wake-worker" in data["services"]


def test_docker_compose_config_validates_via_cli() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not available")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(DEPLOY / "docker-compose.yml"),
            "config",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_compose_wake_api_health_endpoint() -> None:
    data = _load(DEPLOY / "docker-compose.yml")
    # API must expose 8080 — required by deploy docs + examples.
    ports = data["services"]["wake-api"]["ports"]
    assert any("8080" in str(p) for p in ports)


def test_compose_worker_has_no_inbound_port() -> None:
    data = _load(DEPLOY / "docker-compose.yml")
    worker = data["services"]["wake-worker"]
    # Worker is consumer-only — no need to expose ports.
    assert "ports" not in worker or not worker.get("ports")


def test_compose_agentgateway_config_volume_path() -> None:
    """The compose stack mounts the on-disk config into the gateway."""
    data = _load(DEPLOY / "docker-compose.yml")
    gw = data["services"]["agentgateway"]
    vols = gw["volumes"]
    assert any("agentgateway/config.yaml" in v for v in vols)


# ----- agentgateway config -------------------------------------------------


def test_agentgateway_config_has_required_sections() -> None:
    data = _load(DEPLOY / "agentgateway" / "config.yaml")
    for key in ("listen", "vault", "allowed_hosts", "mcp_routes"):
        assert key in data, f"missing key {key}"


def test_agentgateway_allowed_hosts_includes_llm_endpoints() -> None:
    data = _load(DEPLOY / "agentgateway" / "config.yaml")
    hosts = set(data["allowed_hosts"])
    # Sanity: agent traffic to providers + MCP must be whitelisted.
    assert "api.anthropic.com" in hosts
    assert "api.github.com" in hosts


# ----- Helm chart ---------------------------------------------------------


def test_helm_chart_yaml() -> None:
    chart = _load(DEPLOY / "helm" / "wake" / "Chart.yaml")
    assert chart["name"] == "wake"
    assert chart["version"] == "0.4.0"
    assert chart["appVersion"] == "0.4.0"


def test_helm_values_documents_known_components() -> None:
    values = _load(DEPLOY / "helm" / "wake" / "values.yaml")
    for section in ("api", "worker", "postgres", "redis", "agentgateway", "vault"):
        assert section in values, f"values.yaml missing {section}"


def test_helm_template_files_exist() -> None:
    templates_dir = DEPLOY / "helm" / "wake" / "templates"
    required = {
        "_helpers.tpl",
        "deployment-api.yaml",
        "deployment-worker.yaml",
        "statefulset-postgres.yaml",
        "deployment-agentgateway.yaml",
        "deployment-vault.yaml",
        "service.yaml",
        "configmap.yaml",
        "secret.yaml",
        "ingress.yaml",
    }
    existing = {p.name for p in templates_dir.iterdir()}
    missing = required - existing
    assert not missing, f"templates missing: {missing}"


def test_helm_lint_runs_when_helm_installed() -> None:
    if shutil.which("helm") is None:
        pytest.skip("helm CLI not available")
    result = subprocess.run(
        ["helm", "lint", str(DEPLOY / "helm" / "wake")],
        capture_output=True,
        text=True,
        check=False,
    )
    # `helm lint` exits 0 on success; tolerate INFO-level messages.
    assert result.returncode == 0, result.stdout + result.stderr


# ----- docs -----------------------------------------------------------------


def test_deploy_docs_exist() -> None:
    docs_root = DEPLOY.parent / "docs"
    for name in (
        "DEPLOY.md",
        "DEPLOY-DOCKER-COMPOSE.md",
        "DEPLOY-KUBERNETES.md",
        "DEPLOY-FLYIO.md",
        "DEPLOY-AWS.md",
    ):
        assert (docs_root / name).exists(), f"missing doc: {name}"
