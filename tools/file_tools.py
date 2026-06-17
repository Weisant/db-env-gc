"""Basic file tools.

This module contains minimal filesystem operations:
1. Create directories
2. Write files
3. Read files
4. List files under a directory

These functions do not understand database environments or Docker projects themselves; they only handle filesystem-level actions.
"""

from __future__ import annotations

from pathlib import Path


def ensure_directory(path: Path) -> None:
    """Ensure the target directory exists.

    The path may be any directory depth; no error is raised if it already exists.
    """
    path.mkdir(parents=True, exist_ok=True)


def write_file(path: Path, content: str) -> None:
    """Write a single text file using UTF-8 encoding."""
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(content)


def read_file(path: Path) -> str:
    """Read the contents of a single text file.

    This project treats all project files as text files, which matches the current use case.
    """
    return path.read_text(encoding="utf-8")


def list_files(root: Path, exclude_dirs: set[str] | None = None) -> list[Path]:
    """Recursively list all files under a directory.

    `exclude_dirs` excludes directories that should not be included in snapshots, such as `state`.
    """
    exclude_dirs = exclude_dirs or set()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in exclude_dirs for part in relative_parts[:-1]):
            continue
        files.append(path)
    return sorted(files)
