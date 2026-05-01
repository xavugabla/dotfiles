#!/usr/bin/env bash
set -euo pipefail

with_1password=0
original_args=("$@")

usage() {
  cat <<'EOF'
Usage: install-apt.sh [--with-1password]

Installs baseline Linux developer packages. 1Password packages are optional and
should only be installed on machines that need them for human SSH and Git auth.
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
    *)
      usage >&2
      exit 1
      ;;
  esac
  shift
done

apt-get update
apt-get install -y ca-certificates curl gnupg

install -d -m 0755 /etc/apt/keyrings
curl -fSs https://mise.jdx.dev/gpg-key.pub \
  | tee /etc/apt/keyrings/mise-archive-keyring.asc >/dev/null

cat >/etc/apt/sources.list.d/mise.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/mise-archive-keyring.asc] https://mise.jdx.dev/deb stable main
EOF

if [ "$with_1password" -eq 1 ]; then
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
  bat \
  direnv \
  fd-find \
  gh \
  git \
  jq \
  mise \
  pipx \
  fzf \
  git-delta \
  ripgrep \
  shellcheck \
  shfmt \
  tmux \
  zoxide

if [ "$with_1password" -eq 1 ]; then
  apt-get install -y \
    debsig-verify \
    1password \
    1password-cli
fi
