"""项目级工具。

和 `file_tools.py` 不同，这里开始理解“一个项目目录”这个概念：
1. 创建本次运行目录
2. 把 LLM 生成的文件集合写到项目目录
3. 读取项目真实磁盘快照，供 validator 使用
4. 在修复阶段覆盖现有项目文件
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent.models import GeneratedFile, ProjectSnapshot, ProjectSnapshotFile
from agent.tools.file_tools import ensure_directory, list_files, read_file, write_file


def create_run_directory(output_root: Path, project_name: str) -> Path:
    """创建一次独立运行的输出目录。

    目录名由 UTC 时间戳和项目名拼成，便于后续排查和对比不同运行结果。
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = _sanitize_project_name(project_name)
    run_dir = output_root / f"{timestamp}-{safe_name}"
    ensure_directory(run_dir)
    return run_dir


def write_project(root: Path, files: list[GeneratedFile]) -> list[str]:
    """把一组生成文件写入项目目录。

    返回值是相对路径列表，便于主调度器记录实际写入了哪些文件。
    """
    written_paths: list[str] = []
    for generated_file in files:
        target_path = root / generated_file.path
        write_file(target_path, generated_file.content)
        written_paths.append(generated_file.path)
    return written_paths


def overwrite_project_files(root: Path, files: list[GeneratedFile]) -> list[str]:
    """在修复阶段用新文件集合覆盖现有项目。

    当前实现会先清空项目目录中的非 `state/` 文件，再写入修复后的文件，
    这样可以避免旧文件残留导致 validator 看到不一致的磁盘状态。
    """
    _clear_project_files(root)
    return write_project(root, files)


def read_project_snapshot(root: Path) -> ProjectSnapshot:
    """读取当前项目目录的真实文本快照。

    validator 不再只看内存里的 `ProjectArtifacts`，而是直接检查磁盘上的最终交付物。
    """
    snapshot_files = [
        ProjectSnapshotFile(
            path=str(path.relative_to(root)),
            content=read_file(path),
        )
        for path in list_files(root, exclude_dirs={"state"})
    ]
    return ProjectSnapshot(root_dir=root, files=snapshot_files)


def _clear_project_files(root: Path) -> None:
    """删除项目目录中的非状态文件。

    这个函数只在修复阶段使用，且作用域限制在当前生成目录内，不会删除目录外内容。
    """
    for path in reversed(list(root.rglob("*"))):
        if path == root:
            continue
        relative_parts = path.relative_to(root).parts
        if relative_parts and relative_parts[0] == "state":
            continue
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                # 目录非空时暂时跳过，后续子文件删除完再由更外层目录自然清理。
                pass


def _sanitize_project_name(value: str) -> str:
    """把项目名转换成适合目录名的形式。"""
    cleaned_chars: list[str] = []
    for char in value.lower():
        if char.isalnum() or char in {"-", "_"}:
            cleaned_chars.append(char)
        elif char in {" ", "."}:
            cleaned_chars.append("-")
    cleaned = "".join(cleaned_chars).strip("-")
    return cleaned or "db-env-project"
