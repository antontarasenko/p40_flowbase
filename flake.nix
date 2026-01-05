{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, pyproject-nix }:
  let
    systems = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-darwin"
      "x86_64-linux"
    ];
    eachSystem = nixpkgs.lib.genAttrs systems (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config = { allowUnfree = true; };
          overlays = [
            (final: _prev: {
              unstable = import nixpkgs-unstable {
                inherit system;
                config = { allowUnfree = true; };
              };
            })
          ];
        };

        python = pkgs.python313;

        p40flowbase = import ./nix/package.nix {
          inherit python pyproject-nix;
          projectRoot = ./.;
        };

        base = with pkgs; [
          bashInteractive
          pkg-config
        ];

        baseDarwinExtras = with pkgs; pkgs.lib.optionals stdenv.isDarwin [
          libiconv
        ];

        baseLinuxExtras = with pkgs; pkgs.lib.optionals stdenv.isLinux [
        ];

      in {
        formatter = pkgs.nixfmt-rfc-style;

        packages.default = p40flowbase.package;
        packages.p40_flowbase = p40flowbase.package;

        devShells.default = pkgs.mkShell {
          packages = base
            ++ baseDarwinExtras
            ++ baseLinuxExtras
            ++ [ p40flowbase.devEnv ];
          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
          '';
        };

        lib = {
          mkPackage = { python }: import ./nix/package.nix {
            inherit python pyproject-nix;
            projectRoot = ./.;
          };
        };
      });
  in {
    formatter = nixpkgs.lib.mapAttrs (_: system: system.formatter) eachSystem;
    devShells = nixpkgs.lib.mapAttrs (_: system: system.devShells) eachSystem;
    packages  = nixpkgs.lib.mapAttrs (_: system: system.packages)  eachSystem;
    lib       = nixpkgs.lib.mapAttrs (_: system: system.lib)       eachSystem;
  };
}
