# Development Environment Conventions

This directory holds workstation-level configuration that should stay out of
project repositories.

For global profile/identity/shell baseline notes, use the repo root `README.md`.
This file only covers `~/.config/dev` specifics.

Files and directories:
- `active-repos.txt`: absolute paths for repos polled by `dev-git-fetch.timer`.
- `Brewfile`: package inventory baseline.
- `docs/INDEX.md`: docs entrypoint and catalog locations.
- `docs/OPERATIONS.md`: command index grouped by purpose.
- `docs/MINIMAL_CORE.md`: keep-list for gut-down cleanup.
- `docs/SECRET_MODEL.md`: policy for local, cloud, CI, and human-auth secrets.
- `docs/AGENT_GUARDRAILS.md`: agent/editor permission boundaries.
- `docs/AGENT_BASELINE.md`: canonical cross-tool managed policy block.
- `agent-strict-repos.txt`: opt-in strict override repo list (absolute paths).
- `policy-lcd.json`: machine-readable LCD policy floor used by matrix compliance.
- `policy-tiers.json`: machine-readable tier model (4/3/2/1) used by matrix tiering and revamp targeting.
- `chezmoi-age-key.ref`: 1Password reference used to hydrate the shared chezmoi age key on first apply/refresh.
- `op-api-seed.json`: manifest for account/vault-based OP API-style secret export profiles.
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
- Run `dev auth ensure-chezmoi-age-key` when encrypted chezmoi sources are present and a user/machine needs first-time key hydration.
- Run `dev secrets seed-op-api --profile personal` and `dev secrets seed-op-api --profile daisychain` to regenerate central API/token secret files in `~/.config/dev/auth/secrets/`.
- Use `dev secrets profile-path personal` / `dev secrets profile-path daisychain` to reference the generated files from repo `.envrc` blocks.
- Run `dev visibility report` (or `~/.local/bin/dev-visibility-report.py`) to refresh the read-only inventory at `~/.config/dev/visibility/agent-visibility.md`.
- Run `dev visibility report --format json` and `dev visibility report --format matrix-json` for machine-readable state/matrix outputs.
- Run `dev agent audit` to check lax root policy and strict override repos.
- Run `dev agent audit --format json` when policy drift must be consumed programmatically.
- Run `dev agent sync` for safe autofix; use `--all-repos` to apply lax/strict policy across discovered repos and `--bootstrap` to create missing managed policy targets (`AGENTS.md`, `CLAUDE.md`, `.claude/rules/agent-policy.md`, `.cursor/rules/agent-policy.mdc` where applicable).
- Run `dev agent catalog` to import repo-specific agent/rule files into `~/.config/dev/agent-catalog/` for side-by-side review.
- Run `dev reports export --vault-root ~/code/personal/fx_vault` to sync generated reports, mirrored docs, and tier policy config mirrors (`policy-tiers.json`, `policy-lcd.json`, strict repo list) into `~/code/personal/fx_vault/chezmoi/` with a refreshed `INDEX.md`.
- `mise` startup deployment can be paused by default and enabled per-shell with:

  ```bash
  export XAVUGA_MISE_STARTUP=1
  ```

  When unset (default), shell startup skips adding `~/.local/share/mise/shims`
  and skips `mise activate`, while leaving `mise` installed and ready.

Single-point 1Password SSH behavior is controlled per profile in `.chezmoidata.yaml`
via `profiles.<name>.onepassword_ssh_agent` (true/false). Direnv/env-files are
the default local secret strategy; 1Password CLI rendering is legacy-only.
