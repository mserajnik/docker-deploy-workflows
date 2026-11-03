# SPDX-FileCopyrightText: 2026 Michael Serajnik <https://github.com/mserajnik>
# SPDX-License-Identifier: AGPL-3.0-or-later

{
  description = "GitHub Actions workflows for repositories that build and publish Docker images";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    # A maintained fork of actionlint that supports `ubuntu-26.04` runners,
    # `job.workflow_repository`, and `job.workflow_sha`.
    actionlint.url = "github:kjanat/actionlint/v1.17.0";
  };

  outputs =
    { nixpkgs, actionlint, ... }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "aarch64-linux"
        "x86_64-linux"
      ];
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              actionlint.packages.${system}.default
              pkgs.dprint
              pkgs.gh
              pkgs.reuse
              # uv in a standard filesystem layout, so that the Python and the
              # tools it installs run on NixOS without nix-ld.
              (pkgs.buildFHSEnv {
                name = "uv";
                targetPkgs = pkgs: [ pkgs.uv ];
                runScript = "uv";
                unsharePid = true;
                # Required so that uv's Python finds CA certificates.
                profile = ''
                  export SSL_CERT_FILE="''${SSL_CERT_FILE:-${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt}"
                '';
                extraInstallCommands = "ln -s ${pkgs.uv}/share $out/share";
              })
            ];
          };
        }
      );
    };
}
