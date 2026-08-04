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

      # Highest Gurobi usable with or-tools 9.15: Gurobi 13 dropped the
      # GRBcopyparams export, which or-tools' dynamic loader CHECK-fails on
      # (fix pending upstream: google/or-tools#5272). Bump to 13.x once that
      # lands in a release.
      my_gurobi = pkgs.gurobi.overrideAttrs (oldAttrs: rec {
        version = "12.0.3";
        sourceRoot = "gurobi${builtins.replaceStrings ["."] [""] version}/linux64";
        src = pkgs.fetchurl {
          url = "https://packages.gurobi.com/${pkgs.lib.versions.majorMinor version}/gurobi${version}_linux64.tar.gz";
          sha256 = "sha256-Ib2ruq+Dzi2kKk8T7N56H9F7buxNdMl7rYoFGIfRECE=";
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
          cocotb = super.cocotb.overridePythonAttrs (oldAttrs: rec {
            # Any $stop/$fatal (e.g. an RTL assertion under --assert) with FST
            # tracing enabled deadlocks the sim process forever instead of
            # exiting: cocotb's exit callback deletes the tracer, which relocks
            # the mutex Verilated::runExitCallbacks() is holding. Backport of
            # cocotb/cocotb#5423 + 555b88f3 (master-only, not in 2.0.1); see
            # the patch header. Drop once the pinned cocotb release contains
            # both commits.
            patches = (oldAttrs.patches or []) ++ [
              ./patches/cocotb-verilator-fatal-hang.patch
            ];
          });
        };
      # Pinned to 3.13: cocotb 2.0.1 does not support python 3.14 yet.
      in pkgs.python313.override {inherit packageOverrides; };

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
          # setup.py-only project: nixpkgs no longer defaults to setuptools,
          # so declare the PEP 517 backend explicitly.
          pyproject = true;
          build-system = [
            setuptools
            cmake
            pybind11
          ];
          dontUseCmakeConfigure = true;
          # SystemC 2.3.3's QuickThreads assembly has no .note.GNU-stack section,
          # so the linker marks the resulting module as requiring an executable
          # stack, which glibc refuses to load. QuickThreads only switches the
          # stack pointer (no trampolines), so forcing noexecstack is safe.
          NIX_LDFLAGS = "-z noexecstack";
          buildInputs = [
            boost
          ];
          pythonImportsCheck = [ "pyriscvvp" ];
        }))
      ];

      myPythonWithPackages = myPython.withPackages myPyPackages;

      my_verilator = pkgs.verilator;

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
          (lib.hiPrio clang_18) # Fix /bin/c++ collision with gcc
          llvmPackages_18.bintoolsNoLibc # ld.lld required for "awesome compiler patcher"
          llvmPackages_18.clang-unwrapped.python # git-clang-format
          zlib.dev # Needed for verilator fst exports
          lz4.dev # Verilator >= 5.04x compresses FST traces with lz4

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

      # Environment that belongs to the toolchain in env_packages, shared with
      # every consumer of it (our devShell, the isax-tools-integration devShell
      # and its CI container image) so the two cannot drift apart.
      env_vars = {
        # nixpkgs defaults SOURCE_DATE_EPOCH to 315532800 (1980-01-01T00:00:00Z), but
        # maven-jar-plugin >= 3.5 rejects anything below 1980-01-01T00:00:02Z (the
        # minimum a ZIP timestamp can represent), which breaks the SCAIE-V jar build.
        SOURCE_DATE_EPOCH = "315532802";
      };

    in rec {
      lib.envPackages = env_packages;
      lib.envVars = env_vars;
      lib.my_gurobi = my_gurobi;

      devShell = pkgs.mkShellNoCC (env_vars // {
        packages = env_packages ++ (with pkgs; [
          # Non essential packages
          gtkwave
          jq # Needed for open dot helper script
          graphviz # convert dot graphs to an image
          clang-tools # for clangd
          lldb
        ]);
      });
    });}
