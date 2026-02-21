{
  description = "p40_flowbase - Data pipeline framework";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    nixpkgs,
    pyproject-nix,
    uv2nix,
    pyproject-build-systems,
    ...
  }:
  let
    inherit (nixpkgs) lib;

    systems = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-darwin"
      "x86_64-linux"
    ];

    workspace = uv2nix.lib.workspace.loadWorkspace {
      workspaceRoot = ./.;
    };

    overlay = workspace.mkPyprojectOverlay {
      sourcePreference = "wheel";
    };

    # setuptools-scm can't resolve git tags inside the Nix sandbox,
    # so we set the version explicitly for the package build.
    scmVersionOverlay = final: prev: {
      p40-flowbase = prev.p40-flowbase.overrideAttrs (old: {
        version = "0.2.2";
        __intentionallyOverridingVersion = true;
      });
    };

    editableOverlay = workspace.mkEditablePyprojectOverlay {
      root = "$REPO_ROOT";
    };

    forAllSystems = lib.genAttrs systems;

    pythonSets = forAllSystems (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python313;
      in
      (pkgs.callPackage pyproject-nix.build.packages {
        inherit python;
      }).overrideScope (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          overlay
          scmVersionOverlay
        ]
      )
    );

  in {
    formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-rfc-style);

    lib = forAllSystems (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        inherit overlay scmVersionOverlay;

        mkPythonSet = { python }:
          (pkgs.callPackage pyproject-nix.build.packages {
            inherit python;
          }).overrideScope (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.default
              overlay
              scmVersionOverlay
            ]
          );

        mkVirtualEnv = { python, extras ? "default" }:
          let
            pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
              inherit python;
            }).overrideScope (
              lib.composeManyExtensions [
                pyproject-build-systems.overlays.default
                overlay
                scmVersionOverlay
              ]
            );
            deps = {
              default = workspace.deps.default;
              all = workspace.deps.all;
              optionals = workspace.deps.optionals;
              groups = workspace.deps.groups;
            };
          in pythonSet.mkVirtualEnv "p40-flowbase-env" deps.${extras};
      }
    );

    packages = forAllSystems (system: {
      default = pythonSets.${system}.mkVirtualEnv "p40-flowbase-env" workspace.deps.default;
    });

    devShells = forAllSystems (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonSet = pythonSets.${system}.overrideScope (
          lib.composeManyExtensions [
            editableOverlay
            scmVersionOverlay
          ]
        );
        virtualenv = pythonSet.mkVirtualEnv "p40-flowbase-dev-env" workspace.deps.all;
      in {
        default = pkgs.mkShell {
          packages = [
            virtualenv
            pkgs.uv
          ];
          env = {
            UV_NO_SYNC = "1";
            UV_PYTHON = pythonSet.python.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
          };
          shellHook = ''
            unset PYTHONPATH
            export REPO_ROOT=$(git rev-parse --show-toplevel)
          '';
        };
      }
    );
  };
}
