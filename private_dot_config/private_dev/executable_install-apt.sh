#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

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

apt-get update
apt-get install -y \
  pipx \
  direnv \
  fzf \
  git-delta \
  shellcheck \
  shfmt \
  zoxide \
  debsig-verify \
  1password \
  1password-cli
