"""High-confidence local Python checks; only path, line and message summaries may be submitted."""

import ast
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from review_agent_cli.git import ChangedFile

RUFF_CODES = {"E902", "E999", "F821", "F822", "F823"}


@dataclass(frozen=True)
class LocalFinding:
    tool: str
    path: str
    line: int
    message: str


def _python_files(root: Path, files: tuple[ChangedFile, ...]) -> list[tuple[str, Path]]:
    return [
        (item.path, root / item.path)
        for item in files
        if not item.binary and item.path.endswith(".py") and (root / item.path).is_file()
    ]


def _ast_findings(files: list[tuple[str, Path]]) -> list[LocalFinding]:
    findings: list[LocalFinding] = []
    for relative, path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeDecodeError):
            continue
        except SyntaxError as error:
            findings.append(LocalFinding("AST", relative, error.lineno or 1, error.msg))
    return findings


def _ruff_findings(root: Path, files: list[tuple[str, Path]]) -> list[LocalFinding]:
    if not files or shutil.which("ruff") is None:
        return []
    completed = subprocess.run(
        ["ruff", "check", "--output-format", "json", *[str(path) for _, path in files]],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        rows = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    return [
        LocalFinding("Ruff", str(row["filename"]), int(row["location"]["row"]), str(row["message"]))
        for row in rows
        if isinstance(row, dict)
        and row.get("code") in RUFF_CODES
        and isinstance(row.get("filename"), str)
        and isinstance(row.get("location"), dict)
        and isinstance(row["location"].get("row"), int)
    ]


def _bandit_findings(root: Path, files: list[tuple[str, Path]]) -> list[LocalFinding]:
    if not files or shutil.which("bandit") is None:
        return []
    completed = subprocess.run(
        ["bandit", "--quiet", "--format", "json", *[str(path) for _, path in files]],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        data = json.loads(completed.stdout or "{}")
        rows = data.get("results", [])
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    return [
        LocalFinding(
            "Bandit",
            str(row["filename"]),
            int(row["line_number"]),
            str(row["issue_text"]),
        )
        for row in rows
        if isinstance(row, dict)
        and row.get("issue_severity") == "HIGH"
        and row.get("issue_confidence") == "HIGH"
        and isinstance(row.get("filename"), str)
        and isinstance(row.get("line_number"), int)
    ]


def run_local_analysis(root: Path, files: tuple[ChangedFile, ...]) -> list[LocalFinding]:
    """Run AST, Ruff and Bandit only on changed, existing Python files."""
    python_files = _python_files(root, files)
    return (
        _ast_findings(python_files)
        + _ruff_findings(root, python_files)
        + _bandit_findings(root, python_files)
    )
