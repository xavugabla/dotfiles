#!/usr/bin/env python3
"""Audit/sync agent policy with lax-at-root defaults.

Model:
- Canonical default policy lives at ~/code/AGENTS.md.
- Repo-specific strict policy is opt-in via ~/.config/dev/agent-strict-repos.txt.
- Optional all-repo mode applies policy across full repo surfaces:
  AGENTS.md, CLAUDE.md, .claude/rules/agent-policy.md, .cursor/rules/agent-policy.mdc.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


HOME = Path.home()
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")))
CODE_ROOT = HOME / "code"
STRICT_REPOS_FILE = CONFIG_HOME / "dev" / "agent-strict-repos.txt"
ACTIVE_REPOS_FILE = CONFIG_HOME / "dev" / "active-repos.txt"

START = "<!-- dev-agent-policy:start -->"
END = "<!-- dev-agent-policy:end -->"
BLOCK_RE = re.compile(
    rf"{re.escape(START)}\n.*?\n{re.escape(END)}",
    re.DOTALL,
)
MDC_HEADER = """---
description: Managed cross-repo agent policy baseline
alwaysApply: true
---"""

LAX_BLOCK = """<!-- dev-agent-policy:start -->
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
<!-- dev-agent-policy:end -->"""

STRICT_BLOCK = """<!-- dev-agent-policy:start -->
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
<!-- dev-agent-policy:end -->"""

SURFACES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/rules/agent-policy.md",
    ".cursor/rules/agent-policy.mdc",
)


@dataclass(frozen=True)
class Target:
    path: Path
    block: str
    create_content: str
    kind: str


@dataclass
class Result:
    target: Target
    action: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dev agent policy",
        description="Audit and sync root+strict agent policy blocks.",
    )
    parser.add_argument(
        "--mode",
        choices=("audit", "sync"),
        required=True,
        help="audit reports drift; sync updates managed blocks.",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="strict repo absolute path override; may be repeated",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="create missing files (safe for AGENTS.md targets)",
    )
    parser.add_argument(
        "--all-repos",
        action="store_true",
        help="apply policy to all discovered repos (strict repos get strict block)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    return parser.parse_args(argv)


def parse_strict_repo_file() -> list[Path]:
    repos: list[Path] = []
    if not STRICT_REPOS_FILE.is_file():
        return repos
    text = STRICT_REPOS_FILE.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line).expanduser()
        if path.is_absolute() and (path / ".git").is_dir():
            repos.append(path.resolve())
    uniq: dict[str, Path] = {}
    for repo in repos:
        uniq[str(repo)] = repo
    return sorted(uniq.values(), key=lambda p: str(p).lower())


def parse_repo_args(raw_repos: list[str]) -> list[Path]:
    repos: list[Path] = []
    for raw in raw_repos:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError(f"--repo must be absolute: {raw}")
        if not (path / ".git").is_dir():
            raise ValueError(f"--repo is not a git repo: {path}")
        repos.append(path.resolve())
    return repos


def discover_repos() -> list[Path]:
    repos: dict[str, Path] = {}

    if CODE_ROOT.is_dir():
        for child in CODE_ROOT.iterdir():
            if child.is_dir() and (child / ".git").is_dir():
                repos[str(child.resolve())] = child.resolve()
            if child.is_dir():
                for sub in child.iterdir():
                    if sub.is_dir() and (sub / ".git").is_dir():
                        repos[str(sub.resolve())] = sub.resolve()

    if ACTIVE_REPOS_FILE.is_file():
        text = ACTIVE_REPOS_FILE.read_text(encoding="utf-8")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            repo = Path(line).expanduser()
            if repo.is_absolute() and (repo / ".git").is_dir():
                repos[str(repo.resolve())] = repo.resolve()

    return sorted(repos.values(), key=lambda p: str(p).lower())


def normalize(text: str) -> str:
    return text.strip().replace("\r\n", "\n")


def should_manage_surface(repo: Path, rel_path: str) -> bool:
    path = repo / rel_path
    if path.exists():
        return True
    if rel_path == "AGENTS.md":
        return True
    if rel_path == "CLAUDE.md":
        return (repo / ".claude").is_dir()
    if rel_path.startswith(".claude/"):
        return (repo / ".claude").is_dir()
    if rel_path.startswith(".cursor/"):
        return (repo / ".cursor").is_dir()
    return False


def create_content_for(rel_path: str, block: str) -> str:
    if rel_path.endswith(".mdc"):
        return f"{MDC_HEADER}\n\n{block}\n"
    return f"{block}\n"


def sync_target(target: Target, mode: str, bootstrap: bool) -> Result:
    path = target.path
    if not path.exists():
        if mode == "sync" and bootstrap:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(target.create_content, encoding="utf-8")
            return Result(target, "created")
        return Result(target, "missing")

    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Result(target, "skipped-binary")

    match = BLOCK_RE.search(original)
    if not match:
        if mode == "sync":
            updated = original.rstrip() + "\n\n" + target.block + "\n"
            path.write_text(updated, encoding="utf-8")
            return Result(target, "appended")
        return Result(target, "no-managed-block")

    existing = match.group(0)
    if normalize(existing) == normalize(target.block):
        return Result(target, "ok")

    if mode == "sync":
        updated = BLOCK_RE.sub(target.block, original, count=1)
        path.write_text(updated, encoding="utf-8")
        return Result(target, "updated")

    return Result(target, "drift")


def build_targets(strict_repos: list[Path], all_repos: bool) -> list[Target]:
    targets = [
        Target(
            CODE_ROOT / "AGENTS.md",
            LAX_BLOCK,
            create_content_for("AGENTS.md", LAX_BLOCK),
            "root-lax:agents",
        )
    ]
    strict_set = {str(repo.resolve()) for repo in strict_repos}

    if all_repos:
        for repo in discover_repos():
            key = str(repo.resolve())
            block = STRICT_BLOCK if key in strict_set else LAX_BLOCK
            prefix = "repo-strict" if key in strict_set else "repo-lax"
            for rel_path in SURFACES:
                if not should_manage_surface(repo, rel_path):
                    continue
                kind = f"{prefix}:{rel_path}"
                targets.append(
                    Target(
                        repo / rel_path,
                        block,
                        create_content_for(rel_path, block),
                        kind,
                    )
                )
    else:
        for repo in strict_repos:
            for rel_path in SURFACES:
                if not should_manage_surface(repo, rel_path):
                    continue
                targets.append(
                    Target(
                        repo / rel_path,
                        STRICT_BLOCK,
                        create_content_for(rel_path, STRICT_BLOCK),
                        f"repo-strict:{rel_path}",
                    )
                )
    return targets


def run(
    mode: str,
    strict_repos: list[Path],
    bootstrap: bool,
    all_repos: bool,
    output_format: str,
) -> int:
    targets = build_targets(strict_repos, all_repos)
    results = [sync_target(target, mode, bootstrap) for target in targets]

    changed_actions = {"created", "appended", "updated"}
    changed = [r for r in results if r.action in changed_actions]
    drift = [r for r in results if r.action in {"drift", "no-managed-block"}]

    if output_format == "json":
        def repo_root_for(path: Path) -> Path:
            candidate = path if path.is_dir() else path.parent
            for parent in [candidate, *candidate.parents]:
                if (parent / ".git").is_dir():
                    return parent
            return candidate

        payload = {
            "mode": mode,
            "targets": len(targets),
            "strict_repos": len(strict_repos),
            "all_repos": all_repos,
            "changed": len(changed),
            "drift": len(drift),
            "results": [
                {
                    "kind": r.target.kind,
                    "path": str(r.target.path),
                    "action": r.action,
                }
                for r in results
            ],
            "actions": [
                {
                    "type": "reconcile-agent-policy",
                    "path": str(r.target.path),
                    "command": (
                        "dev agent sync --all-repos"
                        if all_repos
                        else f"dev agent sync --repo {repo_root_for(r.target.path)}"
                    ),
                }
                for r in drift
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"{result.target.kind}:{result.target.path} -> {result.action}")

        print(
            f"\nsummary mode={mode} targets={len(targets)} "
            f"strict_repos={len(strict_repos)} all_repos={all_repos} "
            f"changed={len(changed)} drift={len(drift)}"
        )

    if mode == "audit" and drift:
        return 2
    return 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        explicit_repos = parse_repo_args(args.repo)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    strict_repos = explicit_repos or parse_strict_repo_file()
    return run(args.mode, strict_repos, args.bootstrap, args.all_repos, args.format)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
