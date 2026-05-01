# Agent Guardrails

Use repo-local rules for agent-specific permissions. The dotfiles baseline
keeps global defaults conservative and documents the expected boundary:

- Agents may read and edit files only inside the active repo unless explicitly
  asked to inspect another path.
- Commits, pushes, branch creation, PRs, and destructive git operations require
  explicit user intent.
- Secrets stay in direnv-loaded local env files, cloud/CI secret stores, or
  service `EnvironmentFile=` files. Agents should not run `op inject` on a
  critical path.
- Cursor per-chat allowlists are UI-managed; verify them with
  `dev visibility report` when changing machine policy.

For cross-tool consistency, keep the managed policy block from
`~/.config/dev/docs/AGENT_BASELINE.md` synchronized in:

- `~/code/AGENTS.md` (default lax baseline)
- strict override repos listed in `~/.config/dev/agent-strict-repos.txt`

- `dev agent audit`
- `dev agent sync` (safe autofix)
