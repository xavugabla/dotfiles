# Dev Config Docs Index

This docs folder is intentionally small and operational.

Use this as the entrypoint before changing policy, scripts, or managed config.

## Core References

- `MINIMAL_CORE.md`: required chezmoi-managed baseline that should not be gutted.
- `SECRET_MODEL.md`: secret handling model and allowed flows.
- `AGENT_GUARDRAILS.md`: high-level boundaries for agent behavior.
- `AGENT_BASELINE.md`: canonical managed policy blocks for agent sync.
- `OPERATIONS.md`: command/tool index for audit, sync, and catalog tasks.

## Generated Catalogs (outside repo source)

- `~/.config/dev/visibility/agent-visibility.md`: read-only machine + repo agent surface inventory (`dev visibility report`).
- `~/.config/dev/agent-catalog/index.md`: imported repo rule inventory (`dev agent catalog`).
- `~/.config/dev/agent-catalog/snapshots/`: copied source snapshots for side-by-side review.

## Operating Principle

Keep chezmoi source target-native and simple. Use docs + catalogs to explain and
audit behavior instead of introducing heavy conceptual directory layers.
