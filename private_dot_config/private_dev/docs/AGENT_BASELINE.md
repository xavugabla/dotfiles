# Agent Behavior Baseline

Canonical source of truth for cross-tool agent behavior.

See `INDEX.md` for docs navigation and `OPERATIONS.md` for the command flow.

Policy model:
- Lax defaults at `~/code/AGENTS.md`.
- Strict repo-specific policy only for paths listed in
  `~/.config/dev/agent-strict-repos.txt`.
- LCD (lowest common denominator) policy is canonicalized in
  `~/.config/dev/policy-lcd.json` (source template:
  `private_dot_config/private_dev/policy-lcd.json`).
- Tier model is canonicalized in `~/.config/dev/policy-tiers.json` (source template:
  `private_dot_config/private_dev/policy-tiers.json`).

## Core Guardrails

- Work only inside the active repository unless explicitly asked to inspect
  another path.
- Explain significant edits before applying them.
- Do not commit, push, create branches, or open PRs unless explicitly asked.
- Avoid destructive git operations unless explicitly requested.
- Keep secrets out of code and startup flows; prefer direnv/local env files,
  CI/cloud secret stores, and service `EnvironmentFile=` files.
- Prefer a plan-first approach when a task has architecture trade-offs.

## LCD Vocabulary (Machine Standard)

The following keys are standardized and must be interpreted consistently:

- `allow_destructive_git`
- `allow_system_mutation_without_authorization`
- `allow_git_commit_without_authorization`
- `allow_git_push_without_authorization`
- `allow_branch_or_pr_without_authorization`
- `allow_scope_outside_active_repo`

Required guard signals:

- `authorization` (human approval/intent guard must be present)
- `system_mutation_authorization` (system-level changes require authorization)

`dev visibility report --format matrix-json` uses this LCD spec as the desired
state and reports per-repo compliance (`lcd_compliant`, `lcd_violations`).

## Tier Vocabulary (Machine Standard)

Tier intent:

- Tier 4: strict anchor for full-depth governance (`elo-backend-dev`).
- Tier 3: strict anchor for complete-but-lighter governance (`dc_platform`).
- Tier 2: new minimum acceptable standard.
- Tier 1: lowest current baseline, revamp required.

`dev visibility report --format matrix-json` reports:

- `tier_current`
- `tier_target`
- `tier_revamp_required`
- global summary (`tier_counts`, `tier_revamp_count`, `tier_revamp_paths`)

## Canonical Managed Blocks

Default lax block synchronized at `~/code/AGENTS.md`:

```md
<!-- dev-agent-policy:start -->
## Managed Agent Policy (Lax Safe Default)

Policy profile: `lax_safe_v1`

Capability flags:
- `allow_scope_outside_active_repo`: false
- `allow_destructive_git`: false
- `allow_git_commit_without_authorization`: false
- `allow_git_push_without_authorization`: false
- `allow_branch_or_pr_without_authorization`: false
- `allow_system_mutation_without_authorization`: false
- `allow_security_policy_changes_without_authorization`: false
- `allow_plaintext_secret_writes`: false
- `allow_network_side_effects_without_authorization`: false

Execution defaults:
- Collaboration mode: lax (keep momentum, ask only when uncertainty is material).
- Scope: active repo/path under `~/code` unless the user explicitly expands scope.
- Validation: run lightweight targeted checks for changed files and report blockers.
<!-- dev-agent-policy:end -->
```

Strict override block for selected repos:

```md
<!-- dev-agent-policy:start -->
## Managed Agent Policy (Strict Override)
- Policy profile: `strict_safe_v1`
- `allow_scope_outside_active_repo`: false
- `allow_destructive_git`: false
- `allow_git_commit_without_authorization`: false
- `allow_git_push_without_authorization`: false
- `allow_branch_or_pr_without_authorization`: false
- `allow_system_mutation_without_authorization`: false
- `allow_security_policy_changes_without_authorization`: false
- `allow_plaintext_secret_writes`: false
- `allow_network_side_effects_without_authorization`: false
- Scope: modify only task-required files; avoid broad refactors unless requested.
- Approval: ask before architecture/policy/CI/security/cross-repo changes.
- Validation: run strongest targeted checks available for changed files.
<!-- dev-agent-policy:end -->
```

## Sync Model

- `dev agent audit`: report drift/missing for root policy and strict override repos.
- `dev agent sync`: safe autofix for obvious drift:
  - Replace existing managed blocks with canonical lax/strict blocks.
  - Optionally create missing targets with `--bootstrap` across:
    - `AGENTS.md`
    - `CLAUDE.md` (when `.claude/` exists)
    - `.claude/rules/agent-policy.md` (when `.claude/` exists)
    - `.cursor/rules/agent-policy.mdc` (when `.cursor/` exists)
  - Use `--all-repos` to apply lax everywhere except strict allowlist repos.
- `dev agent catalog`: import repo-local policy/rule files into
  `~/.config/dev/agent-catalog/` (index + snapshots) for keep/drop decisions.
