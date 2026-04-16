# dotfiles

This repository is the canonical `chezmoi` source for the workstation setup on
my Linux machines.

## Bootstrap

Install `chezmoi`, then apply the source:

```bash
chezmoi init --apply xavugabla
```

## Notes

- The source includes shell, Git, editor, SSH, and user-systemd configuration.
- Machine-specific secrets are not stored here.
- Privileged package setup lives in `~/.config/dev/install-apt.sh` after apply.
