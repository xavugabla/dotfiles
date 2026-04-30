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
