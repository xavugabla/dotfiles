# dotfiles

This repository is the shared `chezmoi` source for the macOS meta user, the
dedicated macOS identity users, and the Linux execution machine.

## Bootstrap

Install `chezmoi`, then apply the source:

```bash
chezmoi init --apply xavugabla
```

Available profiles:
- `meta_mac`: current admin/meta user on macOS
- `DC_OS`: DaisyChain-focused macOS user
- `XA_OS`: personal / other-projects macOS user
- `fx_linux`: Linux execution plane (currently selected by `os=linux`, `username=xavier`, `hostname=fx`)

## Notes

- The source includes shell, Git, SSH, terminal, editor, and user-systemd configuration.
- The repository is the shared baseline and it decides identity explicitly from `username + os` on macOS and `username + hostname + os` for the Linux execution machine.
- Local `chezmoi.toml` should be reserved for truly local, non-policy config.
- `fxbc` is the macOS control-plane user. Use `dev-as DC` or `dev-as XA` from `fxbc` when you want a clean terminal shell as a dedicated macOS identity without switching the full GUI session.
- Use `dev-user-doctor` inside any profile to inspect the rendered identity, Git, SSH-agent, repo-root, and Homebrew state without reading Keychain contents.
- Repo-root Git identity fragments separate DaisyChain, other-projects, and Proxima without duplicating the shared defaults.
- `~/.config/dev/Brewfile` tracks the baseline package inventory only. Use `brew bundle --file ~/.config/dev/Brewfile` when you want Homebrew to evaluate it. Services like `ollama` and `postgresql@16` are installed but intentionally not configured as always-on background services on macOS.
- `mise` is the canonical Node/toolchain entry point. Shells and Linux user-systemd put `~/.local/share/mise/shims` ahead of legacy managers and editor-bundled runtimes.
- Machine-specific secrets are not stored here. Local repo secrets load through direnv and gitignored env files; automation uses cloud/CI secret stores; 1Password is reserved for human SSH/agent flows and explicit legacy rendering.
- Privileged Linux package setup lives in `~/.config/dev/install-apt.sh` after apply. Run it with `--with-1password` only when that machine should install the 1Password app/CLI packages.
