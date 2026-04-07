"""基础文件工具。

这里放的是最小化的文件系统操作能力：
1. 创建目录
2. 写文件
3. 读文件
4. 枚举目录下文件

这些函数都不理解“数据库环境”或“Docker 项目”本身，它们只处理文件系统层面的动作。
"""

from __future__ import annotations

from pathlib import Path


def ensure_directory(path: Path) -> None:
    """确保目标目录存在。

    参数可以是任意层级目录；如果目录已存在则不会报错。
    """
    path.mkdir(parents=True, exist_ok=True)


def write_file(path: Path, content: str) -> None:
    """以 UTF-8 编码写入单个文本文件。"""
    ensure_directory(path.parent)
    path.write_text(content, encoding="utf-8")


def read_file(path: Path) -> str:
    """读取单个文本文件内容。

    这里默认把所有项目文件视作文本文件，符合当前项目的使用场景。
    """
    return path.read_text(encoding="utf-8")


def list_files(root: Path, exclude_dirs: set[str] | None = None) -> list[Path]:
    """递归列出目录下的全部文件。

    `exclude_dirs` 用于排除不希望纳入快照的目录，例如 `state`。
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
