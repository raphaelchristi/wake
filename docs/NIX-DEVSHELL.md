# Nix Devshell

Reproducible development environment for Wake via [Nix flakes](https://nixos.wiki/wiki/Flakes). Provides pinned versions of Python, Node, Helm, cosign, Terraform, k6, and all CI tooling.

> Phase 9 deliverable (Tier 3 gap #14).

## Why Nix?

- **Reproducible builds** — same toolchain versions across maintainer machines + CI
- **No host pollution** — devshell scope, no global installs needed
- **Cross-platform** — works on macOS/Linux/WSL
- **Combinable** — slot Wake's devshell into your own multi-project Nix config

## Prerequisites

Install Nix (single-user or multi-user):

```bash
# Determinate installer (recommended)
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh

# Or upstream
sh <(curl -L https://nixos.org/nix/install) --daemon
```

Enable flakes (already on by default with Determinate; for upstream Nix):

```bash
mkdir -p ~/.config/nix
echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf
```

## Quick start

```bash
cd /path/to/wake
nix develop
```

This enters a shell with:
- Python 3.11 + `uv` + `pip` + `virtualenv`
- Node 22 + `pnpm`
- Helm + kubectl + kustomize
- Cosign + Sigstore CLI + cyclonedx-cli + grype + trivy + syft
- Terraform + tflint
- k6
- Postgres 16 client
- Common utilities: jq, yq, gh, ripgrep, direnv

Verify:

```
$ nix develop
Wake devshell ready
  Python:    Python 3.11.x
  Node:      v22.x
  Helm:      v3.x
  Cosign:    v2.x
  Terraform: Terraform v1.x

$ python -c "import sys; print(sys.executable)"
# /nix/store/.../python3.11
```

## With direnv (recommended)

`.envrc` already configured:

```bash
echo "use flake" >> .envrc
direnv allow
```

Now the devshell activates automatically when you `cd` into the repo.

## Activating Wake venv inside devshell

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

The `.envrc` will auto-source the venv on subsequent `cd` in.

## What's pinned

`flake.lock` pins `nixpkgs` revision. Upgrade with:

```bash
nix flake update
```

Then commit the new `flake.lock`. CI uses `nix develop --no-update-lock-file` to detect drift.

## Adding tools

Edit `flake.nix` → `packages = with pkgs; [ ... ];` → add the tool. Then:

```bash
exit  # leave devshell
nix develop  # re-enter with new tool
```

Search nixpkgs:

```bash
nix search nixpkgs <tool-name>
```

## Comparison with venv/asdf/mise

| Aspect | Nix devshell | venv | asdf/mise |
|---|---|---|---|
| Reproducibility | full toolchain lockfile | Python only | per-tool lockfile |
| Cross-OS | yes | yes | yes |
| CI parity | bit-identical | partial | partial |
| Setup time first run | ~2 min (fetch) | seconds | minutes per tool |
| Total disk | ~2GB pinned | small | small per tool |

Wake CI uses Nix for reproducible builds; contributors can use any of the three. We test against the Nix-provided toolchain.

## Troubleshooting

**`error: experimental Nix feature 'nix-command' is disabled`**
→ Enable flakes (see Prerequisites).

**`nix develop` is slow first time**
→ Normal — fetching ~2GB of pinned tools. Subsequent runs are instant.

**Tool X is in flake.nix but not in PATH**
→ `exit` and `nix develop` again. Or `nix shell nixpkgs#X` for one-off.

**direnv not activating**
→ `direnv allow` once per repo, ensure direnv hook in your shell init (e.g. `eval "$(direnv hook bash)"`).

## CI usage

`.github/workflows/*` use the Nix devshell where reproducibility matters:

```yaml
- uses: DeterminateSystems/nix-installer-action@main
- uses: DeterminateSystems/magic-nix-cache-action@main
- run: nix develop --command pytest
```

## Limitations

- Initial fetch ~2GB
- macOS performance penalty for some compiles (acceptable for dev)
- Not all packages have macOS support (k6 does; we picked accordingly)
