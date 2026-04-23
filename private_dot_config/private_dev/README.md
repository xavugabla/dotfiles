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
- Run `sudo ~/.local/bin/dev-bootstrap-macos-users [DC] [XA]` from the meta macOS user when you need to seed or refresh the dedicated macOS users from the shared baseline.
- Run `dev bootstrap` after changing managed shell, Git, or systemd files.
- Run `dev visibility report` (or `~/.local/bin/dev-visibility-report.py`) to refresh the read-only agent config inventory at `~/.config/dev/visibility/agent-visibility.md`. v2 adds:
  - Repo discovery across `~/code/*` plus any absolute paths listed in `active-repos.txt`.
  - Per-repo and per-vault git posture (branch, remotes, signing, custom hooks, dirty).
  - iCloud Obsidian vault scan under `~/Library/Mobile Documents/iCloud~md~obsidian/Documents` (toggle with `--no-scan-vaults`; override location with `--vault-root <abs path>`).
  - Cursor `globalStorage/state.vscdb` read-only inspect with the fixed caveat that the per-chat allowlist is UI-only (toggle with `--no-sqlite`).
  - Hooks/rules/skills/plugins enumeration for Claude, Codex, Cursor, Continue (global + per repo/vault).
  - New risk flags: destructive git allow rules, vaults without guardrails, Codex `~` trust scope, Continue empty-allow ambiguity, "agent could commit silently here".
- Git identity boundaries are anchored by repo roots: `~/code/daisychain`, `~/code/personal`, and `~/code/proxima`.
- `.chezmoidata.yaml` is the shared baseline. The repo decides identity explicitly from `username + os` for macOS users and `username + hostname + os` for the Linux execution machine.
- `~/.config/chezmoi/chezmoi.toml` should be reserved for truly local, non-policy configuration.
- `Brewfile` in `~/.config/dev` is package inventory, not service policy. Use `brew bundle --file ~/.config/dev/Brewfile` when you want Homebrew to evaluate it. Local model servers and local databases should be started manually when needed.
- `mise` is intentionally deferred until there is an explicit shared toolchain/version policy.
