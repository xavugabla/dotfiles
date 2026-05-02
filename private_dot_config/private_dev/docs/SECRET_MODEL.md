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

For OP-sourced API/token material, seed central files from the profile manifest:

```bash
dev secrets seed-op-api --profile personal
dev secrets seed-op-api --profile daisychain
```

Then load only the profile(s) needed by a repo:

```bash
# .envrc
strict_env
source_env_if_exists "$(dev secrets profile-path daisychain)"
dotenv_if_exists .env.local
source_env_if_exists .envrc.local
```

If both profile files are loaded at a parent directory, downstream repos can
override by loading only one profile file in the repo-local `.envrc`.

## Human Auth

1Password can be used as an optional SSH key provider for humans. The single
control point is `profiles.<name>.onepassword_ssh_agent` in `.chezmoidata.yaml`.
When enabled, `~/.ssh/config` uses `IdentityAgent ~/.1password/agent.sock`.

Do not export long-lived GitHub or cloud tokens from shell startup files. Use
native tools such as `gh auth login` and `gcloud auth login`.

When encrypted chezmoi source files are used, 1Password is also used once per
user/machine to hydrate the local age key (`~/.config/chezmoi/key.txt.age`) via
`dev auth ensure-chezmoi-age-key` or `dev bootstrap`.

## macOS

Shells are zsh-first. `dev bootstrap` keeps `~/.1password/agent.sock` as a
stable symlink to the 1Password app socket when available.

Use launchd only for GUI jobs that truly need it. Prefer `~/.ssh/config` for
SSH agent selection, and avoid duplicate `SSH_AUTH_SOCK` exports outside the
managed shell templates.

## Linux

Repo identity paths use `~/projects/...` on Linux (`projects/daisychain`,
`projects/personal`, `projects/proxima`) while macOS uses `~/code/...`; the
mapping lives in `.chezmoitemplates/context-repo-root-*.tmpl` so `.chezmoidata.yaml`
can stay mac-oriented.

Encrypted chezmoi content decrypts with the age identity file at
`~/.config/chezmoi/key.txt.age`. Hydrate that file once per machine from the
1Password item referenced in `~/.config/dev/chezmoi-age-key.ref` (see
`dev auth ensure-chezmoi-age-key` / `dev bootstrap`).

Linux shells and user-systemd put `~/.local/share/mise/shims` first in PATH.
`SSH_AUTH_SOCK=~/.1password/agent.sock` is set only when
`onepassword_ssh_agent` is enabled for the active profile.

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
