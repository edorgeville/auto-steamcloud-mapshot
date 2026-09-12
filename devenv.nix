{
  pkgs,
  lib,
  config,
  inputs,
  ...
}:

{
  # https://devenv.sh/packages/
  packages = [
    pkgs.git
    pkgs.jq
    pkgs.curl
    pkgs.hadolint
    pkgs.shellcheck
    pkgs.actionlint
    pkgs.dive
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    package = pkgs.python313;
    venv.enable = true;
    venv.requirements = ''
      ruff
    '';
  };

  # # https://devenv.sh/git-hooks/
  # git-hooks.hooks = {
  #   ruff.enable = true;
  #   shellcheck.enable = true;
  #   hadolint.enable = true;
  #   actionlint.enable = true;
  # };

  # See full reference at https://devenv.sh/reference/options/
}
