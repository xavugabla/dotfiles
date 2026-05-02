# Operations Command Index

Commands are grouped by purpose to reduce drift.

## Control (write managed baseline)

- `chezmoi apply`  
  Apply chezmoi-managed files.
- `dev bootstrap`  
  Reapply baseline + environment/runtime setup checks.
- `dev auth ensure-chezmoi-age-key`  
  Fetch and store the local chezmoi age private key from 1Password when encrypted source files are in use.

## Affect (explicit local mutations)

- `dev repos add <repo-or-path ...>` / `dev repos remove <repo-or-path ...>`  
  Manage tracked repo list at `~/.config/dev/active-repos.txt`.
- `dev agent sync [--bootstrap] [--repo /abs/path ...]`  
  Write managed policy blocks across repo surfaces (AGENTS/CLAUDE/.claude/.cursor) for strict repos or explicit targets.
- `dev agent sync --all-repos [--bootstrap]`  
  Reconcile repo `AGENTS.md` files in bulk: lax everywhere except strict repo allowlist.
- `dev secrets seed-op-api --profile <personal|daisychain>`  
  Regenerate central OP API/token env files from configured account/vault profiles.
- `dev secrets profile-path <personal|daisychain>`  
  Print the generated profile env file path for `.envrc` loaders.

## Observe (read-only audits/imports)

- `dev visibility report [--extra-root /absolute/path]`  
  Full read-only visibility report of agent surfaces and risk flags.
- `dev visibility report --format json`  
  Write machine-readable full-state JSON at `~/.config/dev/visibility/agent-visibility.json`.
- `dev visibility report --format matrix-json`  
  Write machine-readable policy matrix + reconcile actions at `~/.config/dev/visibility/agent-visibility.matrix.json`.
  Uses LCD target policy from `~/.config/dev/policy-lcd.json` and tier model from `~/.config/dev/policy-tiers.json` (or chezmoi source fallbacks).
- `dev agent audit [--repo /abs/path ...]`  
  Drift check for managed agent policy blocks.
- `dev agent audit --format json`  
  Emit drift results and programmatic reconcile commands as JSON.
- `dev agent catalog [--repo /abs/path ...] [--include-worktrees]`  
  Import repo-local rule files into one review catalog.
- `dev reports export [--vault-root /absolute/path]`  
  Sync generated markdown/json reports, mirrored chezmoi docs, and Tier/LCD policy configs into `<vault>/chezmoi/` and refresh `<vault>/chezmoi/INDEX.md`.
- `dev env doctor [repo-or-path ...]`  
  Inspect direnv posture and env-file permissions.
- `dev secrets check [repo-or-path|service ...]`  
  Validate secret file placement/permissions.

## Legacy/Compatibility Paths

- `dev secrets sync --legacy-op-inject <service|all>`
- `dev secrets render-op <service|all>`

Use only when intentionally rendering legacy 1Password templates.

## Drift-Minimizing Workflow

1. Update policy/docs in chezmoi source.
2. Run observe commands (`dev agent audit`, `dev visibility report`, `dev agent catalog`).
3. Apply explicit mutations only when needed (`dev agent sync`, `dev repos ...`).
4. Re-run observe commands to confirm clean state.
