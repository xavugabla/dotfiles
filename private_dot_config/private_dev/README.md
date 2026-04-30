# Development Environment Conventions

This directory holds workstation-level configuration that should stay out of
project repositories.

Files and directories:
- `active-repos.txt`: absolute paths for repos polled by `dev-git-fetch.timer`.
- `docs/SECRET_MODEL.md`: the policy for local, cloud, CI, and human-auth secrets.
- `1password/*.env.tpl`: legacy optional `op inject` templates rendered only by explicit commands.
- `1password/*.target`: optional destination path for a rendered env file.
- `secrets.sh`: legacy interactive exports. It is no longer sourced globally.

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
- Run `./install-apt.sh` for privileged Linux baseline packages. It installs `mise` when an apt package is available and otherwise warns to install it separately. Add `--with-1password` only when that Linux machine should install the 1Password app/CLI packages.
- Use `fxbc` as the macOS control-plane user. Run `dev-as DC` or `dev-as XA` from `fxbc` for clean terminal work as the dedicated macOS identities.
- Run `dev-user-doctor` inside any profile to inspect identity, Git, SSH-agent, repo-root, and Homebrew state without reading Keychain contents.
- Run `sudo ~/.local/bin/dev-bootstrap-macos-users [DC] [XA]` from the meta macOS user when you need to seed or refresh the dedicated macOS users from the shared baseline.
- Run `dev bootstrap` after changing managed shell, Git, or systemd files. It warns if `node` resolves outside mise shims; `op` is optional and only needed for explicit legacy 1Password rendering.
- Run `dev secrets sync` for guidance only. Use `dev secrets render-op SERVICE` or `dev secrets sync --legacy-op-inject SERVICE` when intentionally rendering old 1Password templates.
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
- `mise` is the canonical Node/toolchain entry point. Keep `~/.local/share/mise/shims` ahead of nvm, Cursor, and ad hoc `~/.local/bin/node` shims.
- Agent/editor permission boundaries are summarized in `docs/AGENT_GUARDRAILS.md`.
