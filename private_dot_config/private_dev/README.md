# Development Environment Conventions

This directory holds workstation-level configuration that should stay out of
project repositories.

Files and directories:
- `active-repos.txt`: absolute paths for repos polled by `dev-git-fetch.timer`.
- `1password/*.env.tpl`: `op inject` templates rendered into service env files.
- `1password/*.target`: optional destination path for a rendered env file.
- `secrets.sh`: legacy interactive exports. It is no longer sourced globally.

Workflow:
- Use `direnv` for repo-local development environments.
- Use `EnvironmentFile=` for long-running user services.
- Run `./install-apt.sh` for the privileged package and 1Password install step.
- Run `dev bootstrap` after changing managed shell, Git, or systemd files.
