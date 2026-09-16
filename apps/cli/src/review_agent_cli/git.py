"""Git-only input collection; commands use argument vectors for Windows compatibility."""

from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess, run
from typing import cast

from review_agent_cli.safety import normalize_repository_path


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    binary: bool


@dataclass(frozen=True)
class ReviewInput:
    repository_root: Path
    diff: str
    files: tuple[ChangedFile, ...]


def _git(
    cwd: Path, *args: str, text: bool = True
) -> CompletedProcess[str] | CompletedProcess[bytes]:
    return run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
    )


def repository_root(cwd: Path) -> Path:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(str(result.stdout).strip())


def _name_status(cwd: Path, base: str) -> list[tuple[str, str]]:
    result = _git(cwd, "diff", "--no-ext-diff", "--name-status", "-z", base, "--", text=False)
    parts = cast(bytes, result.stdout).split(b"\0")
    rows: list[tuple[str, str]] = []
    index = 0
    while index < len(parts) and parts[index]:
        status = parts[index].decode("utf-8", "surrogateescape")
        index += 1
        count = 2 if status[:1] in {"R", "C"} else 1
        for _ in range(count):
            if index >= len(parts) or not parts[index]:
                raise ValueError("Git 返回了无效的文件清单")
            path = normalize_repository_path(parts[index].decode("utf-8", "surrogateescape"))
            rows.append((path, status[:1]))
            index += 1
    return rows


def _binary_paths(cwd: Path, base: str) -> set[str]:
    result = _git(cwd, "diff", "--no-ext-diff", "--numstat", "-z", base, "--", text=False)
    parts = cast(bytes, result.stdout).split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(parts) and parts[index]:
        header = parts[index].decode("utf-8", "surrogateescape")
        index += 1
        added, deleted, path = header.split("\t", 2)
        if path:
            if added == "-" or deleted == "-":
                paths.add(normalize_repository_path(path))
            continue
        if index + 1 >= len(parts):
            raise ValueError("Git 返回了无效的二进制文件清单")
        old_path = normalize_repository_path(parts[index].decode("utf-8", "surrogateescape"))
        new_path = normalize_repository_path(parts[index + 1].decode("utf-8", "surrogateescape"))
        if added == "-" or deleted == "-":
            paths.update({old_path, new_path})
        index += 2
    return paths


def collect_review_input(cwd: Path, base: str) -> ReviewInput:
    root = repository_root(cwd)
    files = _name_status(root, base)
    binary = _binary_paths(root, base)
    diff_result = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--unified=3", base, "--")
    return ReviewInput(
        repository_root=root,
        diff=str(diff_result.stdout),
        files=tuple(ChangedFile(path, status, path in binary) for path, status in files),
    )
