# Development Environment Conventions

This directory holds workstation-level configuration that should stay out of
project repositories.

For global profile/identity/shell baseline notes, use the repo root `README.md`.
This file only covers `~/.config/dev` specifics.

Files and directories:
- `active-repos.txt`: absolute paths for repos polled by `dev-git-fetch.timer`.
- `Brewfile`: package inventory baseline.
- `docs/MINIMAL_CORE.md`: keep-list for gut-down cleanup.
- `docs/SECRET_MODEL.md`: policy for local, cloud, CI, and human-auth secrets.
- `docs/AGENT_GUARDRAILS.md`: agent/editor permission boundaries.
- `1password/*.env.tpl`: legacy optional `op inject` templates rendered only by explicit commands.
- `1password/*.target`: optional destination path for a rendered env file.

Workflow:
- Use `direnv` for repo-local development environments. Standard local pattern:

  ```bash
  # .envrc
  strict_env
  dotenv_if_exists .env.local
  source_env_if_exists .envrc.local
  ```

  Keep `.envrc`, `.env.local`, and `.envrc.local` gitignored unless a project has an intentional checked-in, non-secret `.envrc`.
- Set local env files to mode `600`. Check with `dev env doctor [repo-or-path]` or `dev secrets check [repo-or-path|service]`.
- Use `EnvironmentFile=` for long-running user services; do not call `op inject` from service startup.
- Run `./install-apt.sh` for privileged Linux baseline packages. Add `--with-1password` only when that Linux machine should install the 1Password app/CLI packages.
- Run `dev bootstrap` after changing managed shell, Git, or systemd files.
- Run `dev visibility report` (or `~/.local/bin/dev-visibility-report.py`) to refresh the read-only inventory at `~/.config/dev/visibility/agent-visibility.md`.
