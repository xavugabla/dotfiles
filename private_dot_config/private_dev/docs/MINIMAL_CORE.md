# Minimal Core Contract

This file marks the baseline that should survive gut-down cleanup.

## Keep Required

- Identity/profile selection:
  - `.chezmoidata.yaml`
  - `.chezmoi.toml.tmpl`
  - `.chezmoitemplates/profile-name.tmpl`
- Shell bootstrap:
  - `dot_zshrc.tmpl`, `dot_zprofile` (darwin)
  - `dot_bashrc.tmpl`, `dot_profile` (linux)
- Git/SSH:
  - `dot_gitconfig.tmpl`
  - `private_dot_ssh/private_config.tmpl`
  - `private_dot_config/git/ignore`
  - `private_dot_config/git/allowed_signers`
- Toolchain + shared env policy:
  - `private_dot_config/mise/config.toml`
  - `.chezmoitemplates/dev-env-policy.tmpl`
  - `private_dot_config/environment.d/10-dev-path.conf.tmpl`
  - `private_dot_config/systemd/user/dev-git-fetch.service.tmpl` (linux only)

## Archive-First Rule

Candidates for removal are moved to `_archive/` first. `_archive/**` is ignored
by chezmoi apply so files remain available for rollback without affecting target
machines.
