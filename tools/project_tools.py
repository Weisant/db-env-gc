"""Project-level tools.

Unlike `file_tools.py`, this module understands the concept of one project directory:
1. Create the directory for the current run
2. Write the LLM-generated file set into the project directory
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent.models import GeneratedFile
from tools.file_tools import ensure_directory, write_file


def create_run_directory(output_root: Path, project_name: str) -> Path:
    """Create the output directory for one independent run.

    The directory name combines a UTC timestamp and project name, making later troubleshooting and run comparison easier.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = _sanitize_project_name(project_name)
    run_dir = output_root / f"{timestamp}-{safe_name}"
    ensure_directory(run_dir)
    return run_dir


def write_project(root: Path, files: list[GeneratedFile]) -> list[str]:
    """Write a set of generated files into the project directory.

    The return value is a list of relative paths so the main scheduler can record which files were actually written.
    """
    written_paths: list[str] = []
    for generated_file in files:
        target_path = root / generated_file.path
        write_file(target_path, generated_file.content)
        written_paths.append(generated_file.path)
    return written_paths


def _sanitize_project_name(value: str) -> str:
    """Convert a project name into a directory-safe form."""
    cleaned_chars: list[str] = []
    for char in value.lower():
        if char.isalnum() or char in {"-", "_"}:
            cleaned_chars.append(char)
        elif char in {" ", "."}:
            cleaned_chars.append("-")
    cleaned = "".join(cleaned_chars).strip("-")
    return cleaned or "db-env-project"
