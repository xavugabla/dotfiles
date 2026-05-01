# Agent Behavior Baseline

Canonical source of truth for cross-tool agent behavior.

See `INDEX.md` for docs navigation and `OPERATIONS.md` for the command flow.

Policy model:
- Lax defaults at `~/code/AGENTS.md`.
- Strict repo-specific policy only for paths listed in
  `~/.config/dev/agent-strict-repos.txt`.

## Core Guardrails

- Work only inside the active repository unless explicitly asked to inspect
  another path.
- Explain significant edits before applying them.
- Do not commit, push, create branches, or open PRs unless explicitly asked.
- Avoid destructive git operations unless explicitly requested.
- Keep secrets out of code and startup flows; prefer direnv/local env files,
  CI/cloud secret stores, and service `EnvironmentFile=` files.
- Prefer a plan-first approach when a task has architecture trade-offs.

## Canonical Managed Blocks

Default lax block synchronized at `~/code/AGENTS.md`:

```md
<!-- dev-agent-policy:start -->
## Managed Agent Policy (Default Lax)
- Scope: default to the active repo/path under `~/code`; avoid unrelated trees unless asked.
- Workflow: keep momentum on straightforward tasks and ask only when uncertainty is material.
- Git: commits/pushes/branches/PRs require explicit user intent; avoid destructive git unless explicitly requested.
- Secrets: never add plaintext secrets; prefer env references and approved secret stores.
- Validation: run lightweight checks relevant to modified files and report blockers clearly.
<!-- dev-agent-policy:end -->
```

Strict override block for selected repos:

```md
<!-- dev-agent-policy:start -->
## Managed Agent Policy (Strict Override)
- Scope: modify only files required by the task and avoid broad refactors unless requested.
- Approval: ask before changing architecture, policies, CI/security settings, or cross-repo dependencies.
- Git: never commit/push/branch/rebase/reset/force without explicit user intent in this chat.
- Secrets: no plaintext secrets, no token pasting, no secret exfiltration paths.
- Validation: run strongest available targeted checks for changed files before completion.
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
