#!/usr/bin/env python3
"""dev-visibility-report v2.

Generates a read-only Markdown audit of every agent surface this machine
exposes. v2 adds:

- iCloud Obsidian vault scan (alongside ~/code/* repo scan).
- Repo discovery across ~/code/* plus any absolute paths listed in
  ~/.config/dev/active-repos.txt.
- Per-repo / per-vault git posture (is_git_repo, default branch, remotes,
  signing, custom hooks, dirty).
- Read-only inspection of Cursor's globalStorage SQLite plus a fixed caveat
  noting that the per-chat "auto-run / allowed commands" list lives in the
  Cursor UI (this DB), not on disk.
- Hooks / rules / skills / plugins enumeration for Claude, Codex, Cursor,
  and Continue at both global and repo scope.
- New risk flags: "agent could commit silently here" and "vault has no agent
  guardrails"; explicit Continue empty-allow note.
- New CLI flags: --scan-vaults / --no-scan-vaults, --no-sqlite.

The script is intentionally read-only and dependency-free.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


HOME = Path.home()
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")))
OUTPUT_PATH = CONFIG_HOME / "dev" / "visibility" / "agent-visibility.md"
ACTIVE_REPOS_FILE = CONFIG_HOME / "dev" / "active-repos.txt"

TOOL_ORDER = ("claude", "codex", "cursor", "continue")
TOOL_LABELS = {
    "claude": "Claude",
    "codex": "Codex",
    "cursor": "Cursor",
    "continue": "Continue",
}

GLOBAL_ROOTS = {
    "claude": HOME / ".claude",
    "codex": HOME / ".codex",
    "cursor": HOME / ".cursor",
    "continue": HOME / ".continue",
}

KNOWN_GLOBAL_FILES = {
    "claude": (
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/CLAUDE.md",
    ),
    "codex": (
        ".codex/config.toml",
        ".codex/AGENTS.md",
    ),
    "cursor": (".cursor/mcp.json",),
    "continue": (
        ".continue/config.yaml",
        ".continue/permissions.yaml",
        ".continue/.continuerc.json",
    ),
}

KNOWN_REPO_FILES = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/launch.json",
    ".codex/config.toml",
    ".codex/AGENTS.md",
    ".cursor/mcp.json",
    ".continue/config.yaml",
    ".continue/permissions.yaml",
    ".continue/.continuerc.json",
)

AGENT_PATHS = (".claude", ".codex", ".cursor", ".continue")
CONTEXT_CASE_SENSITIVE = {"AGENTS.md"}
CONTEXT_CASE_INSENSITIVE = {"agent.md", "context.md", "claude.md"}
SECRET_KEYWORDS = ("token", "api_key", "apikey", "authorization")
MAX_PERMISSION_RENDER_ENTRIES = 8
ENV_REFERENCE_PATTERNS = (
    re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$"),
    re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$"),
)

DEFAULT_VAULT_ROOT = HOME / "Library/Mobile Documents/iCloud~md~obsidian/Documents"
KNOWN_VAULT_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "CONTEXT.md",
    ".cursor/hooks.json",
    ".cursor/rules",
    ".git",
)

CURSOR_STATE_DB = (
    HOME / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
)
CURSOR_SQLITE_CAVEAT = (
    "Cursor's per-chat 'auto-run / allowed commands' list is stored in "
    "`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` "
    "and surfaced only via the Cursor UI (Settings -> Agent -> Allowed "
    "commands). It is not exposed in `~/.cursor/mcp.json` or any text "
    "config; this scanner cannot enumerate it."
)
CURSOR_SQLITE_KEY_PATTERNS = (
    re.compile(r"^cursor\.(commands|terminal|composer|agent)"),
    re.compile(r"allowlist", re.IGNORECASE),
    re.compile(r"deniedCommand", re.IGNORECASE),
    re.compile(r"approvedCommand", re.IGNORECASE),
)

GIT_DESTRUCTIVE_PATTERNS = (
    re.compile(r"\bgit\s+commit\b"),
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\bgit\s+reset\b"),
    re.compile(r"\bgit\s+rebase\b"),
    re.compile(r"\bgit\s+rm\b"),
    re.compile(r"\bgit\s+mv\b"),
    re.compile(r"\bgit\s+stash\b"),
    re.compile(r"\bgit\s+tag\b"),
    re.compile(r"\bgit\s+reflog\b"),
    re.compile(r"\bgit\s+gc\b"),
    re.compile(r"\bgit\s+update-ref\b"),
    re.compile(r"\bgit\s+filter-branch\b"),
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dev visibility report",
        description="Generate a read-only Markdown report of agent config surfaces.",
    )
    parser.add_argument(
        "--extra-root",
        help="Optional absolute path whose immediate child directories will also be scanned.",
    )
    parser.add_argument(
        "--scan-vaults",
        dest="scan_vaults",
        action="store_true",
        default=True,
        help="Scan the iCloud Obsidian vault root (default: on).",
    )
    parser.add_argument(
        "--no-scan-vaults",
        dest="scan_vaults",
        action="store_false",
        help="Skip the iCloud Obsidian vault scan.",
    )
    parser.add_argument(
        "--no-sqlite",
        dest="cursor_sqlite",
        action="store_false",
        default=True,
        help="Skip read-only inspection of the Cursor globalStorage SQLite database.",
    )
    parser.add_argument(
        "--vault-root",
        help="Override the iCloud vault root (defaults to the standard Obsidian iCloud path).",
    )
    return parser.parse_args(argv)


def display_path(path: Path) -> str:
    try:
        relative = path.relative_to(HOME)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def repo_label(path: Path) -> str:
    return display_path(path)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def parse_json(path: Path) -> Any | None:
    text = read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_toml(path: Path) -> dict[str, Any] | None:
    text = read_text(path)
    if text is None:
        return None

    try:
        import tomllib
    except ModuleNotFoundError:
        return None

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None

    return data if isinstance(data, dict) else None


def parse_inline_list(raw_value: str) -> list[str] | None:
    inner = raw_value[1:-1].strip()
    if not inner:
        return []

    values: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == ",":
            values.append("".join(current).strip())
            current = []
            continue
        current.append(char)

    if quote is not None:
        return None

    values.append("".join(current).strip())
    return [value for value in values if value]


def parse_simple_yaml_lists(path: Path, keys: set[str]) -> dict[str, Any] | None:
    text = read_text(path)
    if text is None:
        return None

    result: dict[str, Any] = {}
    current_key: str | None = None
    ignore_block = False

    for raw_line in text.splitlines():
        stripped_line = raw_line.rstrip()
        content = stripped_line.split("#", 1)[0].rstrip()
        if not content.strip():
            continue

        if raw_line[:1].isspace():
            if current_key is None and not ignore_block:
                return None
            stripped = content.lstrip()
            if ignore_block:
                continue
            if not stripped.startswith("- "):
                return None
            result.setdefault(current_key or "", []).append(stripped[2:].strip())
            continue

        ignore_block = False
        current_key = None
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)", content)
        if match is None:
            return None

        key, raw_value = match.groups()
        raw_value = raw_value.strip()
        if key not in keys:
            ignore_block = not raw_value
            continue

        if not raw_value:
            result.setdefault(key, [])
            current_key = key
            continue

        if raw_value == "[]":
            result[key] = []
            continue

        if raw_value.startswith("[") and raw_value.endswith("]"):
            values = parse_inline_list(raw_value)
            if values is None:
                return None
            result[key] = values
            continue

        result[key] = raw_value

    return result


def normalize_relative(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def append_permission(
    permissions: list[dict[str, Any]], source: str, values: dict[str, Any]
) -> None:
    if values:
        permissions.append({"source": source, "values": values})


def append_integration(
    integrations: list[dict[str, Any]], source: str, values: dict[str, Any]
) -> None:
    if values:
        integrations.append({"source": source, "values": values})


def is_env_reference(value: str) -> bool:
    stripped = value.strip()
    return any(pattern.fullmatch(stripped) for pattern in ENV_REFERENCE_PATTERNS)


def is_env_backed_bearer(value: str) -> bool:
    stripped = value.strip()
    if not stripped.lower().startswith("bearer "):
        return False
    _, _, token = stripped.partition(" ")
    return is_env_reference(token)


def collect_secret_risks(parsed: Any, source: str) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def walk(value: Any, key_path: list[str]) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, key_path + [str(key)])
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested, key_path)
            return
        if not isinstance(value, str):
            return

        joined_path = ".".join(key_path)
        last_key = key_path[-1].lower() if key_path else ""
        if "Bearer " in value:
            if is_env_backed_bearer(value):
                return
            message = f"{joined_path} contains an embedded bearer value"
        elif any(keyword in last_key for keyword in SECRET_KEYWORDS) and value.strip():
            if is_env_reference(value):
                return
            message = f"{joined_path} contains an embedded secret-like value"
        else:
            return

        dedupe_key = (source, message)
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            risks.append({"source": source, "message": message})

    walk(parsed, [])
    return risks


def collect_wildcard_permission_risks(
    source: str, values: dict[str, Any]
) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    for key, value in values.items():
        entries: list[str] = []
        if isinstance(value, list):
            entries = [item for item in value if isinstance(item, str) and "*" in item]
        elif isinstance(value, str) and "*" in value:
            entries = [value]

        if entries:
            risks.append(
                {
                    "source": source,
                    "message": f"{key} contains wildcard permission entries ({len(entries)})",
                }
            )
    return risks


def collect_destructive_git_risks(
    source: str, values: dict[str, Any]
) -> list[dict[str, str]]:
    """Flag allow rules that would let an agent silently mutate git state."""
    risks: list[dict[str, str]] = []
    for key, value in values.items():
        if not key.startswith("permissions.allow"):
            continue
        entries: list[str] = []
        if isinstance(value, list):
            entries = [item for item in value if isinstance(item, str)]
        elif isinstance(value, str):
            entries = [value]
        for entry in entries:
            if any(p.search(entry) for p in GIT_DESTRUCTIVE_PATTERNS):
                risks.append(
                    {
                        "source": source,
                        "message": f"{key} entry permits a destructive git command: `{entry}`",
                    }
                )
    return risks


def extract_claude_permissions(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    data = parse_json(path)
    if not isinstance(data, dict):
        return [], []

    values: dict[str, Any] = {}
    permissions = data.get("permissions")
    if isinstance(permissions, dict):
        for key in ("allow", "ask", "deny"):
            if key in permissions:
                values[f"permissions.{key}"] = permissions[key]

    sandbox = data.get("sandbox")
    if isinstance(sandbox, dict) and "filesystem" in sandbox:
        values["sandbox.filesystem"] = sandbox["filesystem"]

    source = display_path(path)
    permission_surfaces: list[dict[str, Any]] = []
    append_permission(permission_surfaces, source, values)
    risks = collect_secret_risks(data, source)
    risks.extend(collect_wildcard_permission_risks(source, values))
    risks.extend(collect_destructive_git_risks(source, values))
    return permission_surfaces, risks


def extract_continue_permissions(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    data = parse_simple_yaml_lists(path, {"allow", "ask", "exclude"})
    if data is None:
        return [], []

    values = {key: data[key] for key in ("allow", "ask", "exclude") if key in data}
    source = display_path(path)
    permission_surfaces: list[dict[str, Any]] = []
    append_permission(permission_surfaces, source, values)
    risks = collect_wildcard_permission_risks(source, values)
    if values.get("allow") == [] and values.get("ask") == [] and values.get("exclude") == []:
        risks.append(
            {
                "source": source,
                "message": (
                    "allow/ask/exclude are all empty; Continue treats this as 'no extra "
                    "rules' (default behavior stands), NOT as deny-all"
                ),
            }
        )
    return permission_surfaces, risks


def extract_codex_data(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    data = parse_toml(path)
    if data is None:
        return [], [], []

    source = display_path(path)
    permissions: list[dict[str, Any]] = []
    integrations: list[dict[str, Any]] = []

    trust_levels: dict[str, Any] = {}
    projects = data.get("projects")
    if isinstance(projects, dict):
        for project_path, project_data in projects.items():
            if isinstance(project_data, dict) and "trust_level" in project_data:
                trust_levels[display_path(Path(project_path))] = project_data["trust_level"]
    values: dict[str, Any] = {}
    if trust_levels:
        values["projects.trust_level"] = trust_levels
    append_permission(permissions, source, values)

    plugin_names: list[str] = []
    plugins = data.get("plugins")
    if isinstance(plugins, dict):
        plugin_names = sorted(str(name) for name in plugins.keys())
    append_integration(
        integrations,
        source,
        {"plugins": plugin_names} if plugin_names else {},
    )

    risks = collect_secret_risks(data, source)
    if isinstance(trust_levels, dict) and "~" in trust_levels:
        risks.append(
            {
                "source": source,
                "message": (
                    "projects.\"/Users/...\" trust_level is set on the entire HOME directory; "
                    "every subfolder (including iCloud vaults) is implicitly trusted"
                ),
            }
        )
    return permissions, integrations, risks


def extract_claude_integrations(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    data = parse_json(path)
    if not isinstance(data, dict):
        return [], []

    enabled_plugins = data.get("enabledPlugins")
    plugin_names: list[str] = []
    if isinstance(enabled_plugins, dict):
        plugin_names = sorted(str(name) for name, enabled in enabled_plugins.items() if enabled)
    elif isinstance(enabled_plugins, list):
        plugin_names = [str(item) for item in enabled_plugins]

    integrations: list[dict[str, Any]] = []
    append_integration(
        integrations,
        display_path(path),
        {"enabledPlugins": plugin_names} if plugin_names else {},
    )
    risks = collect_secret_risks(data, display_path(path))
    return integrations, risks


def extract_cursor_integrations(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    data = parse_json(path)
    if not isinstance(data, dict):
        return [], []

    servers = data.get("mcpServers")
    server_values: dict[str, Any] = {}
    if isinstance(servers, dict):
        for name, raw_config in servers.items():
            if not isinstance(raw_config, dict):
                continue
            entry = {
                key: raw_config[key]
                for key in ("url", "command", "type")
                if key in raw_config
            }
            server_values[str(name)] = entry

    integrations: list[dict[str, Any]] = []
    append_integration(
        integrations,
        display_path(path),
        {"mcpServers": server_values} if server_values else {},
    )
    risks = collect_secret_risks(data, display_path(path))
    return integrations, risks


def collect_context_files(repo_path: Path) -> list[str]:
    context_files: list[str] = []
    agents_path = repo_path / "AGENTS.md"
    if agents_path.is_file():
        context_files.append("AGENTS.md")

    try:
        children = list(repo_path.iterdir())
    except OSError:
        return context_files

    for child in children:
        if not child.is_file():
            continue
        if child.name.lower() in CONTEXT_CASE_INSENSITIVE:
            context_files.append(child.name)

    return sorted(set(context_files))


# ---------------------------------------------------------------------------
# v2: git posture, surfaces, vaults, sqlite
# ---------------------------------------------------------------------------


def _redact_remote(url: str) -> str:
    """Strip user:token@ from https remotes; leave ssh URLs untouched."""
    return re.sub(r"https?://[^/@]+@", "https://[redacted]@", url)


def _read_git_head(git_dir: Path) -> str | None:
    head = git_dir / "HEAD"
    text = read_text(head)
    if text is None:
        return None
    text = text.strip()
    if text.startswith("ref: "):
        return text[5:].rsplit("/", 1)[-1]
    return text[:12] if text else None


def _read_git_remotes(git_dir: Path) -> list[str]:
    config = git_dir / "config"
    text = read_text(config)
    if text is None:
        return []
    remotes: list[str] = []
    in_remote = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[remote "):
            in_remote = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_remote = False
            continue
        if in_remote and stripped.startswith("url"):
            _, _, rhs = stripped.partition("=")
            url = rhs.strip()
            if url:
                remotes.append(_redact_remote(url))
    return remotes


def _read_git_signing(git_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for source_path in (git_dir / "config", HOME / ".gitconfig"):
        text = read_text(source_path)
        if text is None:
            continue
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].split(" ", 1)[0].lower()
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip().lower()
            value = value.strip()
            if section == "commit" and key == "gpgsign":
                out.setdefault("commit.gpgsign", value)
            elif section == "tag" and key == "gpgsign":
                out.setdefault("tag.gpgsign", value)
    return out


def _read_git_custom_hooks(git_dir: Path) -> list[str]:
    hooks_dir = git_dir / "hooks"
    if not hooks_dir.is_dir():
        return []
    out: list[str] = []
    try:
        for child in hooks_dir.iterdir():
            if not child.is_file():
                continue
            if child.name.endswith(".sample"):
                continue
            try:
                if os.access(child, os.X_OK):
                    out.append(child.name)
            except OSError:
                continue
    except OSError:
        return []
    return sorted(out)


def _git_dirty(repo_path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def git_posture(repo_path: Path) -> dict[str, Any]:
    git_dir = repo_path / ".git"
    if not git_dir.is_dir():
        return {"is_git_repo": False}
    posture: dict[str, Any] = {"is_git_repo": True}
    branch = _read_git_head(git_dir)
    if branch:
        posture["current_branch"] = branch
    remotes = _read_git_remotes(git_dir)
    if remotes:
        posture["remotes"] = remotes
    signing = _read_git_signing(git_dir)
    if signing:
        posture["signing"] = signing
    custom_hooks = _read_git_custom_hooks(git_dir)
    if custom_hooks:
        posture["custom_hooks"] = custom_hooks
    dirty = _git_dirty(repo_path)
    if dirty is not None:
        posture["dirty"] = dirty
    return posture


def _list_glob(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    try:
        return sorted(root.glob(pattern))
    except OSError:
        return []


def _surface_skill_names(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    try:
        for skill_md in root.glob("**/SKILL.md"):
            out.append(skill_md.parent.name)
    except OSError:
        return []
    return sorted(set(out))


def _surface_plugin_ids(root: Path, candidates: tuple[str, ...]) -> list[str]:
    if not root.is_dir():
        return []
    ids: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        for candidate in candidates:
            data = parse_json(child / candidate)
            if isinstance(data, dict):
                identifier = data.get("name") or data.get("id") or child.name
                ids.append(str(identifier))
                break
    return sorted(set(ids))


def enumerate_global_surfaces(tool: str) -> dict[str, Any]:
    root = GLOBAL_ROOTS[tool]
    surfaces: dict[str, Any] = {}
    if not root.exists():
        return surfaces

    if tool == "claude":
        skills = _surface_skill_names(root / "skills")
        if skills:
            surfaces["skills"] = skills
        plugins_root = root / "plugins"
        plugin_ids = _surface_plugin_ids(plugins_root, ("plugin.json", "package.json"))
        if plugin_ids:
            surfaces["plugins"] = plugin_ids
    elif tool == "codex":
        skills = _surface_skill_names(root / "skills")
        if skills:
            surfaces["skills"] = skills
        for sub in ("memories", "plugins"):
            d = root / sub
            if d.is_dir():
                try:
                    children = sorted(c.name for c in d.iterdir())
                except OSError:
                    children = []
                if children:
                    surfaces[sub] = children
        agents_md = root / "AGENTS.md"
        if agents_md.is_file():
            text = read_text(agents_md) or ""
            surfaces["agents_md"] = "non-empty" if text.strip() else "empty"
    elif tool == "cursor":
        hooks_path = root / "hooks.json"
        if hooks_path.is_file():
            data = parse_json(hooks_path)
            if isinstance(data, dict) and "hooks" in data:
                surfaces["hooks"] = sorted(data.get("hooks", {}).keys())
            else:
                surfaces["hooks"] = "present"
        rules_dir = root / "rules"
        rules = [p.name for p in _list_glob(rules_dir, "*.mdc")]
        if rules:
            surfaces["rules"] = rules
        for skills_subdir in (".cursor-user-skills", "skills-cursor"):
            names = _surface_skill_names(root / skills_subdir)
            if names:
                surfaces[skills_subdir] = names
        plugin_json = root / ".claude-plugin" / "plugin.json"
        if plugin_json.is_file():
            data = parse_json(plugin_json)
            if isinstance(data, dict):
                surfaces["claude_plugin"] = data.get("name", "(unnamed)")
        ext_path = root / "extensions" / "extensions.json"
        ext_data = parse_json(ext_path)
        if isinstance(ext_data, list):
            ids: list[str] = []
            for item in ext_data:
                if isinstance(item, dict):
                    ident = item.get("identifier")
                    if isinstance(ident, dict) and "id" in ident:
                        ids.append(str(ident["id"]))
                    elif "id" in item:
                        ids.append(str(item["id"]))
            if ids:
                surfaces["extensions"] = sorted(set(ids))
    elif tool == "continue":
        for sub in ("extensions", "rules"):
            d = root / sub
            if d.is_dir():
                try:
                    names = sorted(c.name for c in d.iterdir())
                except OSError:
                    names = []
                if names:
                    surfaces[sub] = names

    return surfaces


def enumerate_repo_surfaces(repo_path: Path) -> dict[str, Any]:
    surfaces: dict[str, Any] = {}
    rules_dir = repo_path / ".cursor" / "rules"
    rules = [p.name for p in _list_glob(rules_dir, "*.mdc")]
    if rules:
        surfaces["cursor_rules"] = rules
    cursor_hooks = repo_path / ".cursor" / "hooks.json"
    if cursor_hooks.is_file():
        data = parse_json(cursor_hooks)
        if isinstance(data, dict) and "hooks" in data:
            surfaces["cursor_hooks"] = sorted(data.get("hooks", {}).keys())
        else:
            surfaces["cursor_hooks"] = "present"
    for context_name in ("CLAUDE.md", "AGENTS.md", "CONTEXT.md"):
        if (repo_path / context_name).is_file():
            surfaces.setdefault("context", []).append(context_name)
    return surfaces


def cursor_sqlite_inspect() -> dict[str, Any]:
    """Read-only inspect of the Cursor globalStorage state DB.

    Returns {"available": bool, "items": [...], "note": str}. items lists the
    keys whose name matches a small allowlist-relevant pattern, with the
    decoded value's top-level keys (or a short preview).
    """
    info: dict[str, Any] = {
        "path": display_path(CURSOR_STATE_DB),
        "exists": CURSOR_STATE_DB.is_file(),
        "available": False,
        "items": [],
        "note": CURSOR_SQLITE_CAVEAT,
    }
    if not info["exists"]:
        return info
    uri = f"file:{CURSOR_STATE_DB}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.Error:
        return info
    try:
        cursor = conn.execute("SELECT key, value FROM ItemTable")
        for key, value in cursor:
            if not isinstance(key, str):
                continue
            if not any(p.search(key) for p in CURSOR_SQLITE_KEY_PATTERNS):
                continue
            entry: dict[str, Any] = {
                "key": key,
                "length": len(value) if isinstance(value, (bytes, str)) else None,
            }
            if isinstance(value, (bytes, str)):
                text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
                if len(text) <= 1024:
                    try:
                        decoded = json.loads(text)
                    except json.JSONDecodeError:
                        decoded = None
                    if isinstance(decoded, dict):
                        entry["top_keys"] = sorted(str(k) for k in decoded.keys())[:8]
                    elif decoded is not None:
                        entry["preview"] = repr(decoded)[:120]
                    else:
                        entry["preview"] = text[:120]
            info["items"].append(entry)
        info["items"].sort(key=lambda item: item["key"])
        info["available"] = True
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return info


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_global_root(tool: str, root: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "tool": tool,
        "path": display_path(root),
        "exists": root.exists(),
        "files": [],
        "permissions": [],
        "integrations": [],
        "risks": [],
        "surfaces": {},
    }

    if not root.exists():
        return entry

    for relative in KNOWN_GLOBAL_FILES[tool]:
        path = HOME / relative
        if not path.is_file():
            continue

        entry["files"].append(relative)
        if relative == ".claude/settings.local.json":
            permissions, risks = extract_claude_permissions(path)
            entry["permissions"].extend(permissions)
            entry["risks"].extend(risks)
        elif relative == ".claude/settings.json":
            integrations, risks = extract_claude_integrations(path)
            entry["integrations"].extend(integrations)
            entry["risks"].extend(risks)
        elif relative == ".codex/config.toml":
            permissions, integrations, risks = extract_codex_data(path)
            entry["permissions"].extend(permissions)
            entry["integrations"].extend(integrations)
            entry["risks"].extend(risks)
        elif relative == ".cursor/mcp.json":
            integrations, risks = extract_cursor_integrations(path)
            entry["integrations"].extend(integrations)
            entry["risks"].extend(risks)
        elif relative == ".continue/permissions.yaml":
            permissions, risks = extract_continue_permissions(path)
            entry["permissions"].extend(permissions)
            entry["risks"].extend(risks)

    entry["surfaces"] = enumerate_global_surfaces(tool)
    return entry


def scan_repo(repo_path: Path) -> dict[str, Any]:
    agent_files: list[str] = []
    config_files: list[str] = []
    permissions: list[dict[str, Any]] = []
    integrations: list[dict[str, Any]] = []
    risks: list[dict[str, str]] = []

    for agent_path in AGENT_PATHS:
        candidate = repo_path / agent_path
        if candidate.exists():
            agent_files.append(agent_path)

    for relative in KNOWN_REPO_FILES:
        path = repo_path / relative
        if not path.is_file():
            continue

        agent_files.append(relative)
        config_files.append(relative)
        if relative == ".claude/settings.local.json":
            repo_permissions, repo_risks = extract_claude_permissions(path)
            permissions.extend(repo_permissions)
            risks.extend(repo_risks)
        elif relative == ".claude/settings.json":
            repo_integrations, repo_risks = extract_claude_integrations(path)
            integrations.extend(repo_integrations)
            risks.extend(repo_risks)
        elif relative == ".codex/config.toml":
            repo_permissions, repo_integrations, repo_risks = extract_codex_data(path)
            permissions.extend(repo_permissions)
            integrations.extend(repo_integrations)
            risks.extend(repo_risks)
        elif relative == ".cursor/mcp.json":
            repo_integrations, repo_risks = extract_cursor_integrations(path)
            integrations.extend(repo_integrations)
            risks.extend(repo_risks)
        elif relative == ".continue/permissions.yaml":
            repo_permissions, repo_risks = extract_continue_permissions(path)
            permissions.extend(repo_permissions)
            risks.extend(repo_risks)

    context_files = collect_context_files(repo_path)
    surfaces = enumerate_repo_surfaces(repo_path)
    posture = git_posture(repo_path)
    relevant = bool(agent_files or context_files or config_files or surfaces)

    return {
        "path": display_path(repo_path),
        "agent_files": sorted(set(agent_files)),
        "context_files": context_files,
        "config_files": sorted(set(config_files)),
        "permissions": permissions,
        "integrations": integrations,
        "risks": risks,
        "surfaces": surfaces,
        "git": posture,
        "relevant": relevant,
        "is_vault": False,
    }


def scan_vault(vault_path: Path) -> dict[str, Any]:
    """Same shape as scan_repo, but only flags relevance using KNOWN_VAULT_FILES."""
    entry = scan_repo(vault_path)
    entry["is_vault"] = True
    relevant = entry["relevant"]
    if not relevant:
        for marker in KNOWN_VAULT_FILES:
            if (vault_path / marker).exists():
                relevant = True
                break
    entry["relevant"] = relevant
    return entry


def iter_repo_candidates(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    try:
        children = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return []
    return sorted(children, key=lambda child: child.name.lower())


def iter_active_repos(path: Path = ACTIVE_REPOS_FILE) -> list[Path]:
    if not path.is_file():
        return []

    text = read_text(path)
    if text is None:
        return []

    repos: list[Path] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        repo_path = Path(line).expanduser()
        if not repo_path.is_absolute() or not repo_path.is_dir():
            continue
        try:
            repos.append(repo_path.resolve())
        except OSError:
            continue
    return repos


def collect_repo_targets(repo_roots: list[Path]) -> list[Path]:
    deduped: dict[str, Path] = {}

    for repo_root in repo_roots:
        for repo_path in iter_repo_candidates(repo_root):
            deduped[str(repo_path.resolve())] = repo_path.resolve()

    for repo_path in iter_active_repos():
        deduped[str(repo_path)] = repo_path

    return sorted(deduped.values(), key=lambda path: str(path).lower())


def scan(
    extra_root: Path | None = None,
    *,
    scan_vaults: bool = True,
    cursor_sqlite: bool = True,
    vault_root: Path | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tools_detected": [],
        "global_roots": [],
        "repos": [],
        "vaults": [],
        "cursor_sqlite": None,
    }

    detected_tools: set[str] = set()
    for tool in TOOL_ORDER:
        root = GLOBAL_ROOTS[tool]
        entry = scan_global_root(tool, root)
        data["global_roots"].append(entry)
        if entry["exists"]:
            detected_tools.add(tool)

    repo_roots = [HOME / "code"]
    if extra_root is not None:
        repo_roots.append(extra_root)

    for repo_path in collect_repo_targets(repo_roots):
        repo_entry = scan_repo(repo_path)
        if not repo_entry["relevant"]:
            continue
        data["repos"].append(repo_entry)
        for agent_path in AGENT_PATHS:
            if agent_path in repo_entry["agent_files"]:
                detected_tools.add(agent_path[1:])

    if scan_vaults:
        vault_base = vault_root if vault_root is not None else DEFAULT_VAULT_ROOT
        for vault_path in iter_repo_candidates(vault_base):
            vault_entry = scan_vault(vault_path)
            if not vault_entry["relevant"]:
                continue
            data["vaults"].append(vault_entry)

    if cursor_sqlite:
        data["cursor_sqlite"] = cursor_sqlite_inspect()

    data["repos"].sort(key=lambda repo: repo["path"])
    data["vaults"].sort(key=lambda vault: vault["path"])
    data["tools_detected"] = [TOOL_LABELS[tool] for tool in TOOL_ORDER if tool in detected_tools]
    return data


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def json_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def format_surface_value(key: str, value: Any) -> str:
    if (
        isinstance(value, list)
        and (key in {"allow", "ask", "exclude"} or key.startswith("permissions."))
        and len(value) > MAX_PERMISSION_RENDER_ENTRIES
    ):
        preview = json.dumps(value[:MAX_PERMISSION_RENDER_ENTRIES], sort_keys=True)
        remaining = len(value) - MAX_PERMISSION_RENDER_ENTRIES
        return f"{preview} (+{remaining} more)"
    return json_value(value)


def render_surface_group(
    lines: list[str], heading: str, surfaces: list[dict[str, Any]]
) -> bool:
    if not surfaces:
        return False

    lines.append(f"### {heading}")
    for surface in surfaces:
        lines.append(f"- `{surface['source']}`")
        for key, value in surface["values"].items():
            lines.append(f"  - `{key}`: `{format_surface_value(key, value)}`")
    lines.append("")
    return True


def _render_git_block(lines: list[str], git: dict[str, Any]) -> None:
    if not git or not git.get("is_git_repo"):
        lines.append("- Git posture: not a git repo")
        return
    parts = [f"current_branch=`{git.get('current_branch','?')}`"]
    if "remotes" in git:
        parts.append(f"remotes=`{', '.join(git['remotes'])}`")
    if "signing" in git:
        parts.append(f"signing=`{json_value(git['signing'])}`")
    if "custom_hooks" in git:
        parts.append(f"custom_hooks=`{', '.join(git['custom_hooks'])}`")
    if "dirty" in git:
        parts.append(f"dirty=`{git['dirty']}`")
    lines.append(f"- Git posture: {' · '.join(parts)}")


def _render_repo_or_vault(lines: list[str], entry: dict[str, Any]) -> None:
    lines.append(f"### `{entry['path']}`")
    _render_git_block(lines, entry.get("git") or {})
    lines.append(
        "- Agent files: "
        + (", ".join(f"`{p}`" for p in entry.get("agent_files") or []) or "None")
    )
    lines.append(
        "- Context files: "
        + (", ".join(f"`{p}`" for p in entry.get("context_files") or []) or "None")
    )
    lines.append(
        "- Config files: "
        + (", ".join(f"`{p}`" for p in entry.get("config_files") or []) or "None")
    )
    surfaces = entry.get("surfaces") or {}
    if surfaces:
        lines.append("- Surfaces:")
        for key, value in surfaces.items():
            lines.append(f"  - `{key}`: `{json_value(value)}`")
    lines.append("")


def render_markdown(data: dict[str, Any]) -> str:
    lines = ["# Agent Visibility", ""]

    lines.append("## Tools detected")
    if data["tools_detected"]:
        for tool in data["tools_detected"]:
            lines.append(f"- {tool}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Global config roots")
    found_roots = [entry for entry in data["global_roots"] if entry["exists"]]
    if not found_roots:
        lines.append("- None")
    else:
        for entry in found_roots:
            files = ", ".join(f"`{Path(path).name}`" for path in entry["files"]) or "None"
            lines.append(f"- {TOOL_LABELS[entry['tool']]}: `{entry['path']}`")
            lines.append(f"  - Files: {files}")
    lines.append("")

    lines.append("## Obsidian vaults")
    if not data.get("vaults"):
        lines.append("- None")
        lines.append("")
    else:
        for vault in data["vaults"]:
            _render_repo_or_vault(lines, vault)

    lines.append("## Repo-local agent + context files")
    if not data["repos"]:
        lines.append("- None")
        lines.append("")
    else:
        for repo in data["repos"]:
            _render_repo_or_vault(lines, repo)

    lines.append("## Declared permission/integration surfaces")
    global_permissions = [
        surface
        for entry in data["global_roots"]
        for surface in entry["permissions"]
    ]
    repo_like_entries = data["repos"] + data.get("vaults", [])
    repo_permissions = [
        surface
        for repo in repo_like_entries
        for surface in repo["permissions"]
    ]
    global_integrations = [
        surface
        for entry in data["global_roots"]
        for surface in entry["integrations"]
    ]
    repo_integrations = [
        surface
        for repo in repo_like_entries
        for surface in repo["integrations"]
    ]

    rendered_any_surface = False
    rendered_any_surface = render_surface_group(lines, "Global permissions", global_permissions) or rendered_any_surface
    rendered_any_surface = render_surface_group(lines, "Repo / vault permissions", repo_permissions) or rendered_any_surface
    rendered_any_surface = render_surface_group(lines, "Global integrations", global_integrations) or rendered_any_surface
    rendered_any_surface = render_surface_group(lines, "Repo / vault integrations", repo_integrations) or rendered_any_surface
    if not rendered_any_surface:
        lines.append("- None")
        lines.append("")

    lines.append("## Hooks, rules, skills, plugins")
    surfaces_emitted = False
    for entry in data["global_roots"]:
        if not entry["exists"]:
            continue
        if not entry.get("surfaces"):
            continue
        surfaces_emitted = True
        lines.append(f"### {TOOL_LABELS[entry['tool']]} (global)")
        for key, value in entry["surfaces"].items():
            lines.append(f"- `{key}`: `{json_value(value)}`")
        lines.append("")
    repo_surfaces_present = [
        repo for repo in data["repos"] + data.get("vaults", []) if repo.get("surfaces")
    ]
    if repo_surfaces_present:
        surfaces_emitted = True
        lines.append("### Per repo / vault")
        for entry in repo_surfaces_present:
            lines.append(f"- `{entry['path']}`")
            for key, value in entry["surfaces"].items():
                lines.append(f"  - `{key}`: `{json_value(value)}`")
        lines.append("")
    if not surfaces_emitted:
        lines.append("- None")
        lines.append("")

    sqlite_info = data.get("cursor_sqlite")
    if sqlite_info is not None:
        lines.append("## Cursor SQLite allowlist (UI-only)")
        lines.append(f"- DB path: `{sqlite_info['path']}` (exists: `{sqlite_info['exists']}`)")
        lines.append(f"- Note: {sqlite_info['note']}")
        if sqlite_info.get("available") and sqlite_info.get("items"):
            lines.append("- Matching ItemTable keys:")
            for item in sqlite_info["items"][:25]:
                preview = ""
                if "top_keys" in item:
                    preview = f" top_keys=`{json_value(item['top_keys'])}`"
                elif "preview" in item:
                    preview = f" preview=`{item['preview']}`"
                lines.append(
                    f"  - `{item['key']}` length=`{item['length']}`{preview}"
                )
            if len(sqlite_info["items"]) > 25:
                lines.append(f"  - ... +{len(sqlite_info['items'])-25} more")
        lines.append("")

    lines.append("## Risk flags")
    risks: list[dict[str, str]] = []
    for entry in data["global_roots"]:
        risks.extend(entry["risks"])
    for repo in data["repos"]:
        risks.extend(repo["risks"])
    for vault in data.get("vaults", []):
        risks.extend(vault["risks"])

    cursor_global_allowlist = any(
        sqlite_info and sqlite_info.get("available") and sqlite_info.get("items"),
    ) if sqlite_info else False
    for repo in data["repos"] + data.get("vaults", []):
        git = repo.get("git") or {}
        if not git.get("is_git_repo"):
            continue
        branch = git.get("current_branch", "")
        if branch in {"main", "master"} and git.get("dirty") is False and cursor_global_allowlist:
            risks.append(
                {
                    "source": repo["path"],
                    "message": (
                        "agent could commit silently here: clean working tree on default branch "
                        "and Cursor user allowlist is non-empty"
                    ),
                }
            )

    for vault in data.get("vaults", []):
        git = vault.get("git") or {}
        if not git.get("is_git_repo"):
            continue
        ctx = set(vault.get("context_files") or [])
        rules = (vault.get("surfaces") or {}).get("cursor_rules") or []
        if not (ctx & {"CLAUDE.md", "AGENTS.md"}) and not rules:
            risks.append(
                {
                    "source": vault["path"],
                    "message": "vault has no agent guardrails (no CLAUDE.md/AGENTS.md/.cursor/rules/)",
                }
            )

    if not risks:
        lines.append("- None")
    else:
        seen: set[tuple[str, str]] = set()
        for risk in risks:
            dedupe_key = (risk["source"], risk["message"])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            lines.append(f"- `{risk['source']}`: {risk['message']}")

    lines.append("")
    return "\n".join(lines)


def validate_extra_root(raw_value: str | None) -> Path | None:
    if raw_value is None:
        return None
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        raise ValueError("--extra-root must be an absolute path")
    if not path.is_dir():
        raise ValueError(f"--extra-root is not a directory: {path}")
    return path


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        extra_root = validate_extra_root(args.extra_root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    vault_root: Path | None = None
    if args.vault_root:
        try:
            vault_root = validate_extra_root(args.vault_root)
        except ValueError as exc:
            print(f"error: --vault-root: {exc}", file=sys.stderr)
            return 1

    data = scan(
        extra_root=extra_root,
        scan_vaults=args.scan_vaults,
        cursor_sqlite=args.cursor_sqlite,
        vault_root=vault_root,
    )
    markdown = render_markdown(data)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(markdown, encoding="utf-8")
    print(display_path(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
