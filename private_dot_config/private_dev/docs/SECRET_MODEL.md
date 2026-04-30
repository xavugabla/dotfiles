# Secret Model

## Principles

- Local interactive development uses direnv plus gitignored repo env files.
- Human SSH uses the 1Password SSH agent through `~/.ssh/config`.
- User services read explicit env files with `EnvironmentFile=`.
- Cloud Run, CI, and other automation use their platform secret stores.
- `op inject` is legacy and must be requested explicitly.

## Local Development

Use this pattern in a repo:

```bash
# .envrc
strict_env
dotenv_if_exists .env.local
source_env_if_exists .envrc.local
```

Keep `.envrc`, `.env.local`, `.envrc.local`, `*.local.env`, and
`*.secret.env` out of git unless the project deliberately force-adds a
non-secret `.envrc`. Set secret env files to mode `600`.

Check a repo with:

```bash
dev env doctor /path/to/repo
dev secrets check /path/to/repo
```

## Human Auth

1Password remains the SSH key provider for humans. The single policy source is
`~/.ssh/config` through `IdentityAgent ~/.1password/agent.sock`.

Do not export long-lived GitHub or cloud tokens from shell startup files. Use
native tools such as `gh auth login` and `gcloud auth login`.

## macOS

Shells are zsh-first. `dev bootstrap` keeps `~/.1password/agent.sock` as a
stable symlink to the 1Password app socket when available.

Use launchd only for GUI jobs that truly need it. Prefer `~/.ssh/config` for
SSH agent selection, and avoid duplicate `SSH_AUTH_SOCK` exports outside the
managed shell templates.

## Linux

Linux shells and user-systemd put `~/.local/share/mise/shims` first in PATH.
The managed `~/.config/environment.d/10-dev-path.conf` also sets
`SSH_AUTH_SOCK=~/.1password/agent.sock` for user sessions.

For long-running user services, add:

```ini
[Service]
EnvironmentFile=%h/.config/SERVICE/SERVICE.env
```

Create that file manually or through a trusted service-specific script, set it
to mode `600`, and keep it out of git. Do not run `op inject` from service
startup.

## Automation And Cloud

Use the platform secret store:

- Cloud Run: Secret Manager mounted as environment variables or volumes.
- CI: the CI provider's encrypted secrets.
- Local scheduled user services: `EnvironmentFile=` with a local `600` file.

Desktop 1Password vault access is not a dependency for deployed or automated
workloads.

## Legacy 1Password Rendering

Existing templates under `~/.config/dev/1password` can still be rendered:

```bash
dev secrets render-op SERVICE
dev secrets sync --legacy-op-inject SERVICE
```

This is for migration and manual compatibility only.

## Rotation Runbook

1. Identify where the secret is consumed: local repo, user service, CI, or
   Cloud Run.
2. Rotate at the authority of record: provider console, Secret Manager, or CI.
3. Update the local `.env.local` or service `EnvironmentFile=` only if the
   workstation needs that secret.
4. Set local files to mode `600`.
5. Run `dev env doctor` and the service-specific smoke test.
