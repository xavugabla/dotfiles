#!/usr/bin/env python3
"""Collect repo-level agent guidance into one local catalog."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path


HOME = Path.home()
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")))
OUTPUT_ROOT = CONFIG_HOME / "dev" / "agent-catalog"
ACTIVE_REPOS_FILE = CONFIG_HOME / "dev" / "active-repos.txt"
CODE_ROOT = HOME / "code"

TARGET_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTEXT.md",
    ".codex/AGENTS.md",
)
TARGET_GLOBS = (
    ".claude/rules/*.md",
    ".cursor/rules/*.mdc",
)

STRICT_HINT_PATTERN = re.compile(
    r"\b(must|never|require|required|strict|do not|forbidden|only)\b",
    re.IGNORECASE,
)


@dataclass
class RuleFile:
    abs_path: Path
    repo: Path
    repo_label: str
    rel_path: str
    sha256: str
    bytes_size: int
    strict_hints: int
    title: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dev agent catalog",
        description="Import repo-level agent rules into one local catalog.",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="absolute repo path; may be repeated",
    )
    parser.add_argument(
        "--include-worktrees",
        action="store_true",
        help="include .claude/.cursor worktree copies (off by default)",
    )
    return parser.parse_args()


def display(path: Path) -> str:
    try:
        return "~/" + path.relative_to(HOME).as_posix()
    except ValueError:
        return str(path)


def repo_candidates() -> list[Path]:
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
        for raw in ACTIVE_REPOS_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            path = Path(line).expanduser()
            if path.is_absolute() and (path / ".git").is_dir():
                repos[str(path.resolve())] = path.resolve()

    return sorted(repos.values(), key=lambda p: str(p).lower())


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


def repo_label(repo: Path) -> str:
    try:
        return repo.relative_to(CODE_ROOT).as_posix()
    except ValueError:
        return repo.name


def first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def collect_rule_files(repo: Path, include_worktrees: bool) -> list[RuleFile]:
    found: list[RuleFile] = []
    for rel in TARGET_FILES:
        path = repo / rel
        if path.is_file():
            found.append(build_entry(path, repo))
    for pattern in TARGET_GLOBS:
        for path in sorted(repo.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(repo).as_posix()
            if not include_worktrees and "/worktrees/" in rel:
                continue
            found.append(build_entry(path, repo))
    return found


def build_entry(path: Path, repo: Path) -> RuleFile:
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    strict_hints = len(STRICT_HINT_PATTERN.findall(text))
    return RuleFile(
        abs_path=path,
        repo=repo,
        repo_label=repo_label(repo),
        rel_path=path.relative_to(repo).as_posix(),
        sha256=digest,
        bytes_size=len(text.encode("utf-8")),
        strict_hints=strict_hints,
        title=first_heading(text),
    )


def copy_snapshots(rule_files: list[RuleFile]) -> None:
    snapshots_root = OUTPUT_ROOT / "snapshots"
    for item in rule_files:
        source_text = item.abs_path.read_text(encoding="utf-8", errors="replace")
        target = snapshots_root / item.repo_label / item.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text, encoding="utf-8")


def write_index(rule_files: list[RuleFile], repo_count: int) -> Path:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Agent Rule Catalog")
    lines.append("")
    lines.append(
        f"- Repos scanned: `{repo_count}`"
    )
    lines.append(
        f"- Rule files imported: `{len(rule_files)}`"
    )
    lines.append(
        f"- Snapshot root: `{display(OUTPUT_ROOT / 'snapshots')}`"
    )
    lines.append("")

    by_repo: dict[str, list[RuleFile]] = {}
    for item in rule_files:
        by_repo.setdefault(item.repo_label, []).append(item)

    for repo in sorted(by_repo.keys()):
        items = sorted(by_repo[repo], key=lambda i: i.rel_path)
        strict_total = sum(i.strict_hints for i in items)
        lines.append(f"## {repo}")
        lines.append(f"- files: `{len(items)}`")
        lines.append(f"- strict-hint-count: `{strict_total}`")
        lines.append("")
        for item in items:
            title = f" — {item.title}" if item.title else ""
            lines.append(
                f"- `{item.rel_path}`{title} "
                f"(hints=`{item.strict_hints}`, bytes=`{item.bytes_size}`, sha256=`{item.sha256[:12]}`)"
            )
        lines.append("")

    index_path = OUTPUT_ROOT / "index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def main() -> int:
    args = parse_args()
    try:
        repos = parse_repo_args(args.repo)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    if not repos:
        repos = repo_candidates()

    all_files: list[RuleFile] = []
    for repo in repos:
        all_files.extend(collect_rule_files(repo, args.include_worktrees))

    copy_snapshots(all_files)
    index = write_index(all_files, len(repos))
    print(display(index))
    print(f"imported_files={len(all_files)} repos_scanned={len(repos)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
