{
  description = "Wake AI development shell — reproducible dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          name = "wake-devshell";
          packages = with pkgs; [
            # Python toolchain
            python311
            python311Packages.pip
            python311Packages.virtualenv
            uv

            # Node toolchain (frontend + catalog + TS SDK)
            nodejs_22
            pnpm

            # Helm + k8s tooling
            kubernetes-helm
            kubectl
            kustomize

            # Supply chain
            cosign
            cyclonedx-cli
            grype
            trivy
            syft

            # Terraform
            terraform
            tflint

            # Load testing
            k6

            # Postgres
            postgresql_16

            # Utilities
            jq
            yq
            curl
            ripgrep
            git
            gh
            direnv
          ];

          shellHook = ''
            echo "Wake devshell ready"
            echo "  Python:    $(python --version)"
            echo "  Node:      $(node --version)"
            echo "  Helm:      $(helm version --short 2>/dev/null || echo missing)"
            echo "  Cosign:    $(cosign version 2>/dev/null | head -n1 || echo missing)"
            echo "  Terraform: $(terraform version | head -n1)"
            echo ""
            echo "Activate venv: uv venv .venv && source .venv/bin/activate"
            echo "Install:       uv pip install -e '.[dev]'"
          '';
        };
      });
}
