{
  poetry2nix,
  lib,
  stdenv,
  substituteAll,
  writeShellScriptBin,
  python3,
}: let
  overrides = poetry2nix.overrides.withDefaults (self: super: {
    hishel = super.hishel.overridePythonAttrs (
      old: {
        nativeBuildInputs =
          old.nativeBuildInputs
          ++ [
            self.hatch-fancy-pypi-readme
          ];
      }
    );
  });
in {
  # This is the main runnable app that only includes runtime dependencies.
  app = poetry2nix.mkPoetryApplication {
    projectDir = ./..;
    overrides = overrides;
  };

  # This is the development environment.
  devEnv = poetry2nix.mkPoetryEnv {
    projectDir = ./..;
    overrides = overrides;
  };
}
