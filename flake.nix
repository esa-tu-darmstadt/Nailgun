{
  description = "scale4edge env flake";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.librelane.url = "github:librelane/librelane/dev";
  inputs.nixpkgs.url = "nixpkgs/nixpkgs-unstable";

  nixConfig = {
    extra-substituters = [
      "https://nix-cache.fossi-foundation.org"
    ];
    extra-trusted-public-keys = [
      "nix-cache.fossi-foundation.org:3+K59iFwXqKsL7BNu6Guy0v+uTlwsxYQxjspXzqLYQs="
    ];
  };

  outputs = { self, nixpkgs, flake-utils, librelane }@inputs:
    flake-utils.lib.eachDefaultSystem (system: let
      nixpkgs_cfg = {
        allowUnfree = true;
      };
      pkgs = import nixpkgs {
        inherit system;
        config = nixpkgs_cfg;
      };

      my_gurobi = pkgs.gurobi.overrideAttrs (oldAttrs: rec {
        version = "11.0.3";
        sourceRoot = "gurobi${builtins.replaceStrings ["."] [""] version}/linux64";
        src = pkgs.fetchurl {
          url = "https://packages.gurobi.com/${pkgs.lib.versions.majorMinor version}/gurobi${version}_linux64.tar.gz";
          sha256 = "sha256-gqLIZxwjS7qp3GTaIrGVGr9BxiBH/fdwBOZfJKkd/RM=";
        };
      });

      myPython = let
        packageOverrides = self: super: {
          kconfiglib = super.kconfiglib.overridePythonAttrs (oldAttrs: rec {
            # Apply patch to fix crashes with unsupported locales
            patches = (oldAttrs.patches or []) ++ [
              (pkgs.fetchpatch {
                url = "https://github.com/ulfalizer/Kconfiglib/pull/107/commits/538ac8b0d1419744e81a3669ecc70a81c84fcc06.patch";
                hash = "sha256-4J48yxv368hRGUYWu1jZ4mi1enOvvq7JYpp0dAvHCYw=";
              })
            ];
          });
        };
      in pkgs.python3.override {inherit packageOverrides; };

      myPyPackages = python-packages: with python-packages; [
        find-libpython
        cocotb
        cocotb-bus
        capstone
        psutil
        numpy
        pyyaml
        pytest
        autopep8 # autoformatter
        kconfiglib # nailgun
        pyelftools # simulations with nailgun
        ruamel-yaml # LN asic model script
        pandas # data output aggregation and formating
        seaborn # data visualization
        tabulate # printing tables

        # Package pyriscv-vp
        (buildPythonPackage (let
          pyriscvvp_repo = pkgs.fetchFromGitHub {
            owner = "esa-tu-darmstadt";
            repo = "pyriscv-vp";
            rev = "b2a3e2aaf677ca3aaa7ca59105bf4f5246292848";
            hash = "sha256-h2LMCmn5xxbDWUF6UZ4568IPJ62X5VLKpMhVMoS2ttA=";
            fetchSubmodules = true;
          };
        in rec {
          pname = "pyriscvvp";
          version = "0.0.1";
          src = "${pyriscvvp_repo}/vp";
          patches = [
            ./patches/pyriscv-vp.patch
          ];
          postPatch = let
            systemc_src = pkgs.fetchurl {
              url = "https://www.accellera.org/images/downloads/standards/systemc/systemc-2.3.3.tar.gz";
              hash = "sha256-V4G5o1Hlr+2rw30UXl9+3sCPP9XeAP/rj6HzCGsfez8=";
            };
          in ''
            cp ${pyriscvvp_repo}/env/basic/vp-display/framebuffer.h src/platform/basic/
            # Excuse me wtf
            cp ${systemc_src} dependencies/systemc-2.3.3.tar.gz
            (cd dependencies && ./build_systemc_233.sh)
            (cd dependencies && ./build_softfloat.sh)
          '';
          build-system = [
            cmake
            pybind11
          ];
          dontUseCmakeConfigure = true;
          buildInputs = [
            boost
          ];
          pythonImportsCheck = [ "pyriscvvp" ];
        }))
      ];

      myPythonWithPackages = myPython.withPackages myPyPackages;

      my_verilator = pkgs.verilator.overrideAttrs (oldAttrs: rec {
        # version = "5.032";
        version = "5.033";
        # Verilator gets the version from this environment variable
        # if it can't do git describe while building.
        VERILATOR_SRC_VERSION = "v${version}";

        src = pkgs.fetchFromGitHub {
          owner = oldAttrs.pname;
          repo = oldAttrs.pname;
          rev = "f4a01eb4525f23ee6ad8b6a4f17535a45adcea61";
          hash = "sha256-bpTAG3r68oAKv6oZqoQmahfirf8sL6Y1q5l1PhcxHUs=";
        };

        patches = [
          # Cruel "fix" to remove the failing asserting: https://github.com/verilator/verilator/issues/5668
          # TODO remove once https://github.com/verilator/verilator/issues/5668 was properly fixed!
          (pkgs.fetchpatch {
            url = "https://github.com/verilator/verilator/pull/5313.patch";
            hash = "sha256-o3eC/vLNtOeubwUnhehVg9tfOp09GHxkRLBDvsKZ0Ms=";
          })
        ] ++ (oldAttrs.patches or []);

        doCheck = false;
      });

      env_packages = with pkgs; [
          git # Pin git to version 2.47.1. Apparently the init.sh script no longer works with version >= 2.48.1

          # Python env for the utility scripts & cocotb
          myPythonWithPackages

          # verilog
          my_verilator
          # yosys # DANGER: yosys adds its own python environment to the path

          # # commercial ILP solver
          my_gurobi
          # program to find MWC
          cliquer

          # # HW synthesis tools
          # DANGER: librelane adds its own python environment to the path.
          # If it has a different python version than our myPythonWithPackages, then it seems to overshadow the results of find_libpython.
          # This results in the usage of the wrong libpython and breaks cocotb simulations.
          librelane.packages."${system}".librelane

          # # Core simulation dependencies
          maven
          sbt
          texinfo
          bison
          flex
          gperf
          gradle # treenail
          jdk21 # Match the java version with the jdk version used in gradle: https://github.com/NixOS/nixpkgs/blob/59e3db96f9a77621aedc57c41e59da674611e0f8/pkgs/development/tools/build-managers/gradle/default.nix#L134
          bluespec # Compile piccolo et al.

          gcc # The cocotb/verilator simulation uses gcc
          cmake
          ccache
          ninja
          gnumake # get-or-tools.sh
          (hiPrio clang_18) # Fix /bin/c++ collision with gcc
          llvmPackages_18.bintoolsNoLibc # ld.lld required for "awesome compiler patcher"
          llvmPackages_18.clang-unwrapped.python # git-clang-format
          zlib.dev # Needed for verilator fst exports

          # yosys-slang dependencies:
          boost.dev
          libedit.dev
          ncurses.dev
          libbsd.dev

          meson # picolibc
          renode-unstable # for functional simulation

          util-linux # we need `rev` for the Makefiles in scaie-v-testbenches
          rsync # awesome_llvm: compiler-patcher.sh
          # get-or-tools.sh dependencies
          curl
          gnutar
          gzip
      ];
    in rec {
      lib.envPackages = env_packages;
      lib.my_gurobi = my_gurobi;

      devShell = pkgs.mkShellNoCC {
        packages = env_packages ++ (with pkgs; [
          # Non essential packages
          gtkwave
          jq # Needed for open dot helper script
          graphviz # convert dot graphs to an image
          clang-tools # for clangd
          lldb
        ]);
      };
    });}
