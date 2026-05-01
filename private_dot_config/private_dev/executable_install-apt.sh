#!/usr/bin/env bash
set -euo pipefail

with_1password=0
with_tailscale=0
original_args=("$@")

usage() {
  cat <<'EOF'
Usage: install-apt.sh [--with-1password] [--with-tailscale]

Installs baseline Linux developer packages. 1Password packages are optional
because workstation health no longer depends on `op` or `op inject`.
Tailscale install is optional and should be enabled on remote execution hosts.
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "${original_args[@]}"
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-1password) with_1password=1 ;;
    --with-tailscale) with_tailscale=1 ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [ "$with_1password" -eq 1 ]; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://downloads.1password.com/linux/keys/1password.asc \
    | gpg --dearmor --yes -o /usr/share/keyrings/1password-archive-keyring.gpg

  cat >/etc/apt/sources.list.d/1password.list <<'EOF'
deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main
EOF

  install -d -m 0755 /etc/debsig/policies/AC2D62742012EA22/
  install -d -m 0755 /usr/share/debsig/keyrings/AC2D62742012EA22/

  curl -fsSL https://downloads.1password.com/linux/debian/debsig/1password.pol \
    -o /etc/debsig/policies/AC2D62742012EA22/1password.pol
  curl -fsSL https://downloads.1password.com/linux/keys/1password.asc \
    | gpg --dearmor --yes -o /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg
fi

apt-get update
apt-get install -y \
  pipx \
  direnv \
  fzf \
  git-delta \
  tmux \
  shellcheck \
  shfmt \
  zoxide

if apt-cache show mise >/dev/null 2>&1; then
  apt-get install -y mise
else
  printf '%s\n' 'warning: apt package "mise" is unavailable; install mise separately so Node resolves through ~/.local/share/mise/shims' >&2
fi

if [ "$with_1password" -eq 1 ]; then
  apt-get install -y \
    debsig-verify \
    1password \
    1password-cli
fi

if [ "$with_tailscale" -eq 1 ]; then
  if apt-cache show tailscale >/dev/null 2>&1; then
    apt-get install -y tailscale
  else
    printf '%s\n' 'warning: apt package "tailscale" is unavailable; install from official Tailscale repository and enable unattended auth for remote hosts' >&2
  fi
fi
