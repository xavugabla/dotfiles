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
import datetime as dt
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
OUTPUT_DIR = CONFIG_HOME / "dev" / "visibility"
OUTPUT_PATH = OUTPUT_DIR / "agent-visibility.md"
OUTPUT_JSON_PATH = OUTPUT_DIR / "agent-visibility.json"
OUTPUT_MATRIX_JSON_PATH = OUTPUT_DIR / "agent-visibility.matrix.json"
ACTIVE_REPOS_FILE = CONFIG_HOME / "dev" / "active-repos.txt"
STRICT_REPOS_FILE = CONFIG_HOME / "dev" / "agent-strict-repos.txt"
LCD_POLICY_PATH_CANDIDATES = (
    CONFIG_HOME / "dev" / "policy-lcd.json",
    HOME / ".local/share/chezmoi/private_dot_config/private_dev/policy-lcd.json",
)

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

SHELL_STARTUP_FILES = (
    HOME / ".zshenv",
    HOME / ".zprofile",
    HOME / ".zshrc",
    HOME / ".zlogin",
    HOME / ".bash_profile",
    HOME / ".bashrc",
    HOME / ".profile",
    HOME / ".local/share/chezmoi/dot_zshrc.tmpl",
    HOME / ".local/share/chezmoi/dot_bashrc.tmpl",
)
SHELL_SECRET_PATTERNS = (
    (
        re.compile(r"(^|[^A-Za-z0-9_])op\s+read([^A-Za-z0-9_]|$)"),
        "runs `op read` during shell startup",
    ),
    (
        re.compile(r"(^|\s)(export\s+)?(GH_TOKEN|GITHUB_TOKEN)="),
        "assigns a GitHub token during shell startup",
    ),
)
GH_HOSTS_PATH = CONFIG_HOME / "gh" / "hosts.yml"
OP_CONFIG_PATH = CONFIG_HOME / "op" / "config"
OP_DAEMON_SOCKET = CONFIG_HOME / "op" / "op-daemon.sock"
ONEPASSWORD_CLI_SOCKET = (
    HOME / "Library/Group Containers/2BUA8C4S2C.com.1password/t/s.sock"
)
ONEPASSWORD_SSH_SOCKET = HOME / ".1password" / "agent.sock"
LEGACY_OP_TEMPLATE_DIR = CONFIG_HOME / "dev" / "1password"

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
    parser.add_argument(
        "--format",
        choices=("markdown", "json", "matrix-json"),
        default="markdown",
        help="Output format written to disk (default: markdown).",
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


def socket_state(path: Path) -> dict[str, Any]:
    try:
        stat_result = path.stat()
    except OSError:
        return {"path": display_path(path), "present": False, "mtime_epoch": None}
    return {
        "path": display_path(path),
        "present": path.is_socket(),
        "mtime_epoch": int(stat_result.st_mtime),
    }


def collect_shell_startup_secret_matches() -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in SHELL_STARTUP_FILES:
        text = read_text(path)
        if text is None:
            continue
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for pattern, message in SHELL_SECRET_PATTERNS:
                if pattern.search(raw_line):
                    matches.append(
                        {
                            "source": display_path(path),
                            "line": line_no,
                            "message": message,
                        }
                    )
    return matches


def gh_hosts_state() -> dict[str, str]:
    text = read_text(GH_HOSTS_PATH)
    if text is None:
        state = "missing"
    elif not text.strip() or text.strip() == "{}":
        state = "empty"
    elif "github.com:" in text:
        state = "configured"
    else:
        state = "present"
    return {"path": display_path(GH_HOSTS_PATH), "state": state}


def op_config_state() -> dict[str, str]:
    data = parse_json(OP_CONFIG_PATH)
    if not isinstance(data, dict):
        return {
            "path": display_path(OP_CONFIG_PATH),
            "state": "missing or unreadable",
            "accounts": "unknown",
            "latest_signin": "unknown",
            "system_auth_latest_signin": "unknown",
        }

    accounts = data.get("accounts")
    if accounts is None:
        accounts_state = "none"
    elif isinstance(accounts, list):
        accounts_state = f"configured ({len(accounts)})"
    else:
        accounts_state = "configured"

    return {
        "path": display_path(OP_CONFIG_PATH),
        "state": "present",
        "accounts": accounts_state,
        "latest_signin": "set" if data.get("latest_signin") else "unset",
        "system_auth_latest_signin": (
            "set" if data.get("system_auth_latest_signin") else "unset"
        ),
    }


def scan_workstation_auth() -> dict[str, Any]:
    shell_matches = collect_shell_startup_secret_matches()
    gh_hosts = gh_hosts_state()
    op_config = op_config_state()
    legacy_op_templates = sorted(LEGACY_OP_TEMPLATE_DIR.glob("*.env.tpl"))
    sockets = {
        "1password ssh": socket_state(ONEPASSWORD_SSH_SOCKET),
        "1password cli": socket_state(ONEPASSWORD_CLI_SOCKET),
        "op daemon": socket_state(OP_DAEMON_SOCKET),
    }
    token_env = {
        "GH_TOKEN": "set" if os.environ.get("GH_TOKEN") else "unset",
        "GITHUB_TOKEN": "set" if os.environ.get("GITHUB_TOKEN") else "unset",
    }

    risks: list[dict[str, str]] = []
    for match in shell_matches:
        risks.append(
            {
                "source": match["source"],
                "message": f"line {match['line']} {match['message']}",
            }
        )

    if gh_hosts["state"] in {"missing", "empty"}:
        risks.append(
            {
                "source": gh_hosts["path"],
                "message": "GitHub CLI has no native host auth; use `gh auth login` instead of shell-startup token exports",
            }
        )

    if (
        legacy_op_templates
        and op_config["accounts"] == "none"
        and not sockets["1password cli"]["present"]
    ):
        risks.append(
            {
                "source": op_config["path"],
                "message": "legacy 1Password env templates exist, but CLI account/app-integration auth is unavailable",
            }
        )

    return {
        "token_env": token_env,
        "gh_hosts": gh_hosts,
        "op_config": op_config,
        "legacy_op_template_count": len(legacy_op_templates),
        "sockets": sockets,
        "shell_startup_secret_matches": shell_matches,
        "risks": risks,
    }


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
            resolved = repo_path.resolve()
            deduped[str(resolved)] = resolved
            for nested in iter_repo_candidates(repo_path):
                nested_resolved = nested.resolve()
                if (nested_resolved / ".git").is_dir():
                    deduped[str(nested_resolved)] = nested_resolved

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
        "workstation_auth": scan_workstation_auth(),
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

    auth = data.get("workstation_auth")
    if auth:
        lines.append("## Workstation auth")
        token_env = auth.get("token_env") or {}
        lines.append(
            "- Current token env: "
            f"GH_TOKEN=`{token_env.get('GH_TOKEN', 'unknown')}` · "
            f"GITHUB_TOKEN=`{token_env.get('GITHUB_TOKEN', 'unknown')}`"
        )
        gh_hosts = auth.get("gh_hosts") or {}
        lines.append(
            "- GitHub CLI native auth: "
            f"`{gh_hosts.get('state', 'unknown')}` at `{gh_hosts.get('path', '?')}`"
        )
        op_config = auth.get("op_config") or {}
        lines.append(
            "- 1Password CLI config: "
            f"accounts=`{op_config.get('accounts', 'unknown')}` · "
            f"latest_signin=`{op_config.get('latest_signin', 'unknown')}` · "
            f"system_auth_latest_signin=`{op_config.get('system_auth_latest_signin', 'unknown')}`"
        )
        lines.append(
            "- Legacy 1Password env templates: "
            f"`{auth.get('legacy_op_template_count', 0)}`"
        )
        sockets = auth.get("sockets") or {}
        if sockets:
            lines.append("- 1Password sockets:")
            for name, state in sockets.items():
                status = "present" if state.get("present") else "missing"
                mtime = state.get("mtime_epoch")
                suffix = f" · mtime_epoch=`{mtime}`" if mtime is not None else ""
                lines.append(f"  - `{name}`: `{status}` at `{state.get('path', '?')}`{suffix}")
        shell_matches = auth.get("shell_startup_secret_matches") or []
        if shell_matches:
            lines.append("- Shell startup secret reads:")
            for match in shell_matches:
                lines.append(
                    f"  - `{match['source']}:{match['line']}` {match['message']}"
                )
        else:
            lines.append("- Shell startup secret reads: None")
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
    if data.get("workstation_auth"):
        risks.extend(data["workstation_auth"].get("risks", []))
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


def expand_display_path(value: str) -> Path:
    if value == "~":
        return HOME
    if value.startswith("~/"):
        return HOME / value[2:]
    return Path(value)


def parse_strict_repos(path: Path = STRICT_REPOS_FILE) -> set[str]:
    repos: set[str] = set()
    text = read_text(path)
    if text is None:
        return repos
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line).expanduser()
        if candidate.is_absolute():
            repos.add(str(candidate))
    return repos


def extract_profiles_from_envrc_text(text: str) -> list[str]:
    matches = re.findall(r"dev\s+secrets\s+profile-path\s+([A-Za-z0-9_-]+)", text)
    return sorted(set(matches))


def infer_env_policy(repo_path: Path) -> dict[str, Any]:
    envrc_path = repo_path / ".envrc"
    if not envrc_path.is_file():
        return {
            "has_envrc": False,
            "source_up": False,
            "profiles_explicit": [],
            "profiles_effective": [],
            "policy_note": "no .envrc",
        }

    text = read_text(envrc_path) or ""
    source_up = bool(re.search(r"(^|\s)source_up(\s|$)", text))
    explicit_profiles = extract_profiles_from_envrc_text(text)
    effective_profiles = list(explicit_profiles)
    notes: list[str] = []
    if source_up:
        parent = repo_path.parent
        while parent != parent.parent:
            parent_envrc = parent / ".envrc"
            if parent_envrc.is_file():
                parent_profiles = extract_profiles_from_envrc_text(read_text(parent_envrc) or "")
                for profile in parent_profiles:
                    if profile not in effective_profiles:
                        effective_profiles.append(profile)
                notes.append(f"inherits from {display_path(parent_envrc)}")
                break
            parent = parent.parent

    return {
        "has_envrc": True,
        "source_up": source_up,
        "profiles_explicit": explicit_profiles,
        "profiles_effective": sorted(effective_profiles),
        "policy_note": "; ".join(notes) if notes else "repo-local only",
    }


def read_managed_policy_mode(path: Path) -> str:
    text = read_text(path)
    if text is None:
        return "missing"
    if "<!-- dev-agent-policy:start -->" not in text or "<!-- dev-agent-policy:end -->" not in text:
        return "no-managed-block"
    if "Managed Agent Policy (Strict Override)" in text:
        return "strict"
    if "Managed Agent Policy (Lax Safe Default)" in text or "Managed Agent Policy (Default Lax)" in text:
        return "lax"
    return "managed-unknown"


def _glob_files(repo_path: Path, pattern: str, limit: int = 50) -> list[Path]:
    matches: list[Path] = []
    try:
        for candidate in repo_path.glob(pattern):
            if candidate.is_file():
                matches.append(candidate)
            if len(matches) >= limit:
                break
    except OSError:
        return []
    return sorted(matches)


def collect_repo_contract_signals(repo_path: Path) -> dict[str, Any]:
    commit_guidelines = _glob_files(repo_path, ".claude/rules/*commit*guideline*.md")
    pr_guidelines = _glob_files(repo_path, ".claude/rules/*pr*guideline*.md")
    git_guides = _glob_files(repo_path, ".claude/rules/*git*.md")

    roadmap_docs = _glob_files(repo_path, "docs/**/*ROADMAP*.md")
    if not roadmap_docs:
        roadmap_docs = _glob_files(repo_path, "docs/**/*roadmap*.md")

    memory_files = (
        _glob_files(repo_path, ".codex/memories/*")
        + _glob_files(repo_path, ".claude/memory*")
        + _glob_files(repo_path, ".cursor/memory*")
        + _glob_files(repo_path, "MEMORY*.md")
    )
    skills_files = (
        _glob_files(repo_path, ".claude/skills/**/SKILL.md")
        + _glob_files(repo_path, ".codex/skills/**/SKILL.md")
        + _glob_files(repo_path, ".cursor/skills-cursor/**/SKILL.md")
        + _glob_files(repo_path, ".cursor/.cursor-user-skills/**/SKILL.md")
    )

    docs_conventions = _glob_files(repo_path, "docs/**/*convention*.md") + _glob_files(repo_path, "docs/**/*guideline*.md")

    matched = {
        "commit_guidelines": commit_guidelines,
        "pr_guidelines": pr_guidelines,
        "git_guides": git_guides,
        "roadmap_docs": roadmap_docs,
        "memory_files": memory_files,
        "skills_files": skills_files,
        "docs_conventions": docs_conventions,
    }
    policy_stack_depth = 0
    if (repo_path / "AGENTS.md").is_file():
        policy_stack_depth += 1
    if (repo_path / "CLAUDE.md").is_file():
        policy_stack_depth += 1
    if any(_glob_files(repo_path, ".claude/rules/*.md", limit=1)):
        policy_stack_depth += 1
    if any(_glob_files(repo_path, ".cursor/rules/*.mdc", limit=1)):
        policy_stack_depth += 1

    return {
        "has_commit_guidelines": bool(commit_guidelines),
        "has_pr_guidelines": bool(pr_guidelines),
        "has_git_guides": bool(git_guides),
        "has_roadmap_conventions": bool(roadmap_docs),
        "has_memory_surface": bool(memory_files),
        "has_skills_surface": bool(skills_files),
        "has_docs_contract": bool(docs_conventions or roadmap_docs),
        "policy_stack_depth": policy_stack_depth,
        "matched_files": {
            key: [display_path(path) for path in value[:12]]
            for key, value in matched.items()
            if value
        },
    }


DEFAULT_LCD_POLICY = {
    "schema_version": "v1",
    "profile": "lcd_safe_v1",
    "allow_flags": {
        "allow_destructive_git": False,
        "allow_system_mutation_without_authorization": False,
        "allow_git_commit_without_authorization": False,
        "allow_git_push_without_authorization": False,
        "allow_branch_or_pr_without_authorization": False,
        "allow_scope_outside_active_repo": False,
    },
    "required_guards": {
        "authorization": True,
        "system_mutation_authorization": True,
    },
}


def load_lcd_policy() -> dict[str, Any]:
    policy: dict[str, Any] = json.loads(json.dumps(DEFAULT_LCD_POLICY))
    for candidate in LCD_POLICY_PATH_CANDIDATES:
        raw = parse_json(candidate)
        if not isinstance(raw, dict):
            continue
        allow = raw.get("allow_flags")
        if isinstance(allow, dict):
            for key, value in allow.items():
                if key in policy["allow_flags"] and isinstance(value, bool):
                    policy["allow_flags"][key] = value
        guards = raw.get("required_guards")
        if isinstance(guards, dict):
            for key, value in guards.items():
                if key in policy["required_guards"] and isinstance(value, bool):
                    policy["required_guards"][key] = value
        if isinstance(raw.get("schema_version"), str):
            policy["schema_version"] = raw["schema_version"]
        if isinstance(raw.get("profile"), str):
            policy["profile"] = raw["profile"]
        policy["source"] = display_path(candidate)
        return policy
    policy["source"] = "(built-in default)"
    return policy


DEFAULT_POLICY_TIERS = {
    "schema_version": "v1",
    "profile": "agent_tiers_v1",
    "anchors": {"tier_4": ["~/code/daisychain/elo-backend-dev"], "tier_3": ["~/code/daisychain/dc_platform"]},
    "tier_2_standard": {
        "min_policy_stack_depth": 2,
        "require_authorization_guard": True,
        "require_system_mutation_guard": True,
        "forbid_wildcard_pattern": True,
        "required_false_allow_flags": [
            "allow_destructive_git",
            "allow_system_mutation_without_authorization",
            "allow_git_commit_without_authorization",
            "allow_git_push_without_authorization",
            "allow_branch_or_pr_without_authorization",
            "allow_scope_outside_active_repo",
        ],
    },
    "targets": {"tier_4": 4, "tier_3": 3, "default_minimum": 2},
}

POLICY_TIERS_PATH_CANDIDATES = (
    CONFIG_HOME / "dev" / "policy-tiers.json",
    HOME / ".local/share/chezmoi/private_dot_config/private_dev/policy-tiers.json",
)


def load_policy_tiers() -> dict[str, Any]:
    tiers: dict[str, Any] = json.loads(json.dumps(DEFAULT_POLICY_TIERS))
    for candidate in POLICY_TIERS_PATH_CANDIDATES:
        raw = parse_json(candidate)
        if not isinstance(raw, dict):
            continue
        for key in ("schema_version", "profile"):
            if isinstance(raw.get(key), str):
                tiers[key] = raw[key]
        if isinstance(raw.get("anchors"), dict):
            for anchor_key in ("tier_4", "tier_3"):
                values = raw["anchors"].get(anchor_key)
                if isinstance(values, list):
                    tiers["anchors"][anchor_key] = [str(v) for v in values if isinstance(v, str)]
        if isinstance(raw.get("tier_2_standard"), dict):
            for key, value in raw["tier_2_standard"].items():
                tiers["tier_2_standard"][key] = value
        if isinstance(raw.get("targets"), dict):
            for key, value in raw["targets"].items():
                tiers["targets"][key] = value
        tiers["source"] = display_path(candidate)
        return tiers
    tiers["source"] = "(built-in default)"
    return tiers


DESTRUCTIVE_GIT_ALLOW_RE = re.compile(
    r"(allow_destructive_git\s*:\s*true|git\s+push\s+--force|git\s+reset\s+--hard)",
    re.IGNORECASE,
)
UNAUTH_COMMIT_ALLOW_RE = re.compile(
    r"(allow_git_commit_without_authorization\s*:\s*true|commit without authorization)",
    re.IGNORECASE,
)
UNAUTH_PUSH_ALLOW_RE = re.compile(
    r"(allow_git_push_without_authorization\s*:\s*true|push without authorization)",
    re.IGNORECASE,
)
UNAUTH_BRANCH_ALLOW_RE = re.compile(
    r"(allow_branch_or_pr_without_authorization\s*:\s*true|branch without authorization|pr without authorization)",
    re.IGNORECASE,
)
UNAUTH_SYSTEM_MUT_ALLOW_RE = re.compile(
    r"(allow_system_mutation_without_authorization\s*:\s*true|system mutation without authorization)",
    re.IGNORECASE,
)
SCOPE_OUTSIDE_ALLOW_RE = re.compile(
    r"(allow_scope_outside_active_repo\s*:\s*true|outside active repo without authorization)",
    re.IGNORECASE,
)
AUTH_GUARD_RE = re.compile(r"(explicit user intent|without authorization:\s*false|ask before)", re.IGNORECASE)
SYSTEM_MUTATION_GUARD_RE = re.compile(
    r"(allow_system_mutation_without_authorization\s*:\s*false|ask before .*system|system.*authorization)",
    re.IGNORECASE,
)
WILDCARD_RE = re.compile(r"(\*\*\/\*|\ballow\s*:\s*\[\s*\"?\*\"?\s*\]|wildcard)", re.IGNORECASE)


def _policy_surface_paths(repo_path: Path) -> list[Path]:
    paths: list[Path] = []
    for rel in (
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/rules/agent-policy.md",
        ".cursor/rules/agent-policy.mdc",
    ):
        p = repo_path / rel
        if p.is_file():
            paths.append(p)
    return paths


def parse_policy_effective_signals(repo_path: Path, lcd_policy: dict[str, Any]) -> dict[str, Any]:
    allow = {key: False for key in lcd_policy["allow_flags"].keys()}
    guards = {
        "has_authorization_guard": False,
        "has_system_mutation_guard": False,
        "has_wildcard_pattern": False,
    }
    matched_sources: dict[str, list[str]] = {}

    for path in _policy_surface_paths(repo_path):
        text = read_text(path) or ""
        src = display_path(path)

        checks = [
            ("allow_destructive_git", DESTRUCTIVE_GIT_ALLOW_RE),
            ("allow_git_commit_without_authorization", UNAUTH_COMMIT_ALLOW_RE),
            ("allow_git_push_without_authorization", UNAUTH_PUSH_ALLOW_RE),
            ("allow_branch_or_pr_without_authorization", UNAUTH_BRANCH_ALLOW_RE),
            ("allow_system_mutation_without_authorization", UNAUTH_SYSTEM_MUT_ALLOW_RE),
            ("allow_scope_outside_active_repo", SCOPE_OUTSIDE_ALLOW_RE),
        ]
        for key, pattern in checks:
            if pattern.search(text):
                allow[key] = True
                matched_sources.setdefault(key, []).append(src)

        if AUTH_GUARD_RE.search(text):
            guards["has_authorization_guard"] = True
            matched_sources.setdefault("has_authorization_guard", []).append(src)
        if SYSTEM_MUTATION_GUARD_RE.search(text):
            guards["has_system_mutation_guard"] = True
            matched_sources.setdefault("has_system_mutation_guard", []).append(src)
        if WILDCARD_RE.search(text):
            guards["has_wildcard_pattern"] = True
            matched_sources.setdefault("has_wildcard_pattern", []).append(src)

    violations = [
        key
        for key, value in allow.items()
        if value != lcd_policy["allow_flags"].get(key, False)
    ]
    if guards["has_wildcard_pattern"]:
        violations.append("has_wildcard_pattern")
    if lcd_policy["required_guards"].get("authorization", True) and not guards["has_authorization_guard"]:
        violations.append("missing_authorization_guard")
    if (
        lcd_policy["required_guards"].get("system_mutation_authorization", True)
        and not guards["has_system_mutation_guard"]
    ):
        violations.append("missing_system_mutation_guard")

    compliance = {
        "lcd_compliant": len(violations) == 0,
        "violations": violations,
    }

    return {
        "allow_flags_effective": allow,
        "guard_signals": guards,
        "compliance": compliance,
        "matched_policy_sources": matched_sources,
    }


def classify_tier(
    path_display: str,
    contract: dict[str, Any],
    effective: dict[str, Any],
    is_vault: bool,
    is_external: bool,
    tiers: dict[str, Any],
) -> tuple[int | None, int | None, bool]:
    if is_vault:
        return None, None, False

    anchors = tiers.get("anchors", {})
    tier4 = set(anchors.get("tier_4", []))
    tier3 = set(anchors.get("tier_3", []))

    if path_display in tier4:
        current = 4
    elif path_display in tier3:
        current = 3
    else:
        std = tiers.get("tier_2_standard", {})
        required_false = std.get("required_false_allow_flags", [])
        allow_flags = effective.get("allow_flags_effective", {})
        guards = effective.get("guard_signals", {})
        tier2_ready = (
            contract.get("policy_stack_depth", 0) >= int(std.get("min_policy_stack_depth", 2))
            and (not std.get("require_authorization_guard", True) or guards.get("has_authorization_guard", False))
            and (
                not std.get("require_system_mutation_guard", True)
                or guards.get("has_system_mutation_guard", False)
            )
            and (not std.get("forbid_wildcard_pattern", True) or not guards.get("has_wildcard_pattern", False))
            and all(not allow_flags.get(flag, False) for flag in required_false if isinstance(flag, str))
        )
        current = 2 if tier2_ready else 1

    targets = tiers.get("targets", {})
    if current == 4:
        target = int(targets.get("tier_4", 4))
    elif current == 3:
        target = int(targets.get("tier_3", 3))
    else:
        target = int(targets.get("default_minimum", 2))

    if is_external:
        target = min(target, current)

    return current, target, current < target


def build_matrix_json(data: dict[str, Any]) -> dict[str, Any]:
    strict_repos = parse_strict_repos()
    lcd_policy = load_lcd_policy()
    tiers_policy = load_policy_tiers()
    rows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    entries = list(data.get("repos", [])) + list(data.get("vaults", []))

    for entry in entries:
        repo_path = expand_display_path(entry["path"])
        repo_key = str(repo_path)
        is_vault = bool(entry.get("is_vault"))
        expected_agent_mode = "n/a" if is_vault else ("strict" if repo_key in strict_repos else "lax")
        agent_policy_mode = read_managed_policy_mode(repo_path / "AGENTS.md")
        env_policy = infer_env_policy(repo_path)
        is_external = repo_path.is_relative_to(HOME / "code" / "External")
        contract = collect_repo_contract_signals(repo_path) if not is_vault else {
            "has_commit_guidelines": False,
            "has_pr_guidelines": False,
            "has_git_guides": False,
            "has_roadmap_conventions": False,
            "has_memory_surface": False,
            "has_skills_surface": False,
            "has_docs_contract": False,
            "policy_stack_depth": 0,
            "matched_files": {},
        }
        effective = parse_policy_effective_signals(repo_path, lcd_policy) if not is_vault else {
            "allow_flags_effective": dict(lcd_policy["allow_flags"]),
            "guard_signals": {
                "has_authorization_guard": False,
                "has_system_mutation_guard": False,
                "has_wildcard_pattern": False,
            },
            "compliance": {"lcd_compliant": True, "violations": []},
            "matched_policy_sources": {},
        }
        drift = False if is_vault else agent_policy_mode not in {"missing", expected_agent_mode}
        if is_vault or is_external:
            sync_mode = "hands_off"
        elif contract["policy_stack_depth"] >= 3 or any(
            (
                contract["has_commit_guidelines"],
                contract["has_pr_guidelines"],
                contract["has_roadmap_conventions"],
                contract["has_memory_surface"],
                contract["has_skills_surface"],
            )
        ):
            sync_mode = "baseline_plus_repo_contract"
        else:
            sync_mode = "baseline_only"

        reconcile_action = f"dev agent sync --repo {repo_path}" if (drift and not is_vault) else None
        tier_current, tier_target, tier_revamp_required = classify_tier(
            entry["path"], contract, effective, is_vault, is_external, tiers_policy
        )
        revert_action = None
        git_info = entry.get("git") or {}
        if git_info.get("is_git_repo") and not is_vault:
            revert_action = (
                f"git -C {repo_path} restore AGENTS.md CLAUDE.md "
                ".claude/rules/agent-policy.md .cursor/rules/agent-policy.mdc"
            )

        row = {
            "path": entry["path"],
            "is_vault": is_vault,
            "is_external": is_external,
            "git_branch": git_info.get("current_branch"),
            "allowlist_mode": "strict" if (not is_vault and repo_key in strict_repos) else ("n/a" if is_vault else "lax"),
            "expected_agent_mode": expected_agent_mode,
            "agent_policy_mode": agent_policy_mode,
            "agent_policy_drift": drift,
            "policy_floor_mode": expected_agent_mode,
            "policy_stack_depth": contract["policy_stack_depth"],
            "sync_mode": sync_mode,
            "has_commit_guidelines": contract["has_commit_guidelines"],
            "has_pr_guidelines": contract["has_pr_guidelines"],
            "has_git_guides": contract["has_git_guides"],
            "has_roadmap_conventions": contract["has_roadmap_conventions"],
            "has_memory_surface": contract["has_memory_surface"],
            "has_skills_surface": contract["has_skills_surface"],
            "has_docs_contract": contract["has_docs_contract"],
            "matched_contract_files": contract["matched_files"],
            "allow_flags_effective": effective["allow_flags_effective"],
            "guard_signals": effective["guard_signals"],
            "lcd_compliant": effective["compliance"]["lcd_compliant"],
            "lcd_violations": effective["compliance"]["violations"],
            "matched_policy_sources": effective["matched_policy_sources"],
            "tier_current": tier_current,
            "tier_target": tier_target,
            "tier_revamp_required": tier_revamp_required,
            "env_source_up": env_policy["source_up"],
            "env_profiles_explicit": env_policy["profiles_explicit"],
            "env_profiles_effective": env_policy["profiles_effective"],
            "env_policy_note": env_policy["policy_note"],
            "risk_count": len(entry.get("risks") or []),
            "reconcile_action": reconcile_action,
            "revert_action": revert_action,
        }
        rows.append(row)

        if drift and not entry.get("is_vault"):
            actions.append(
                {
                    "type": "reconcile-agent-policy",
                    "path": entry["path"],
                    "command": reconcile_action,
                    "expected_mode": expected_agent_mode,
                    "observed_mode": agent_policy_mode,
                    "revert_command": revert_action,
                }
            )
        if (not is_vault) and effective["compliance"]["violations"]:
            actions.append(
                {
                    "type": "tighten-policy-lcd",
                    "path": entry["path"],
                    "command": f"dev agent sync --repo {repo_path}",
                    "violations": effective["compliance"]["violations"],
                    "revert_command": revert_action,
                }
            )
        if (not is_vault) and tier_revamp_required:
            actions.append(
                {
                    "type": "tier-revamp",
                    "path": entry["path"],
                    "command": f"dev agent sync --repo {repo_path}",
                    "tier_current": tier_current,
                    "tier_target": tier_target,
                    "revert_command": revert_action,
                }
            )

    rows.sort(key=lambda item: item["path"])
    actions.sort(key=lambda item: item["path"])
    lcd_non_compliant = [row["path"] for row in rows if (not row["is_vault"]) and not row["lcd_compliant"]]
    tier_counts: dict[str, int] = {}
    for row in rows:
        t = row.get("tier_current")
        if t is None:
            continue
        key = f"tier_{t}"
        tier_counts[key] = tier_counts.get(key, 0) + 1
    tier_revamp_paths = [row["path"] for row in rows if row.get("tier_revamp_required")]
    return {
        "schema_version": "v3",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "desired_policy_lcd": lcd_policy,
        "desired_policy_tiers": tiers_policy,
        "lcd_non_compliant_count": len(lcd_non_compliant),
        "lcd_non_compliant_paths": lcd_non_compliant,
        "tier_counts": tier_counts,
        "tier_revamp_count": len(tier_revamp_paths),
        "tier_revamp_paths": tier_revamp_paths,
        "row_count": len(rows),
        "rows": rows,
        "actions": actions,
    }


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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.format == "markdown":
        markdown = render_markdown(data)
        OUTPUT_PATH.write_text(markdown, encoding="utf-8")
        print(display_path(OUTPUT_PATH))
        return 0

    payload = {
        "schema_version": "v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "state": data,
    }
    if args.format == "json":
        OUTPUT_JSON_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(display_path(OUTPUT_JSON_PATH))
        return 0

    matrix = build_matrix_json(data)
    OUTPUT_MATRIX_JSON_PATH.write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(display_path(OUTPUT_MATRIX_JSON_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
