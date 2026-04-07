"""DB Env GC 命令行入口。"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.agent import DBEnvGenerationAgent


class TeeStream:
    """将终端输出同时写入日志文件。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data: str) -> None:
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def build_parser() -> argparse.ArgumentParser:
    """构建参数解析器。"""
    parser = argparse.ArgumentParser(
        description="Generate database environment Docker projects."
    )
    parser.add_argument(
        "output_directory",
        nargs="?",
        default=None,
        help="Directory where generated projects will be written.",
    )
    parser.add_argument(
        "--skip-validator",
        action="store_true",
        help="Skip the validator stage and only generate/write project files.",
    )
    return parser


def clear_runtime_logs(base_dir: Path) -> tuple[Path, Path]:
    """清空本次执行相关日志。"""
    terminal_log_path = base_dir / "terminal_log.txt"
    agents_log_path = base_dir / "agents_log.txt"
    for path in (terminal_log_path, agents_log_path):
        path.write_text("", encoding="utf-8")
    return terminal_log_path, agents_log_path


def get_utc_timestamp() -> str:
    """返回统一格式的 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_interactive_task() -> str:
    """从终端接收多行任务输入。"""
    lines: list[str] = []
    first_line = True
    while True:
        prompt = "请输入任务：" if first_line else ""
        line = input(prompt)
        first_line = False
        if not line.strip():
            break
        lines.append(line.rstrip())
    if not lines:
        raise SystemExit("未检测到输入，程序结束。")
    return "\n".join(lines)


def main() -> None:
    """CLI 主入口。"""
    args = build_parser().parse_args()
    base_dir = Path(__file__).resolve().parent
    # 除非用户在 CLI 中显式指定其他路径，否则默认输出到当前项目根目录下的 output/。
    output_directory = (
        Path(args.output_directory).resolve()
        if args.output_directory
        else (base_dir / "output").resolve()
    )
    enable_validator = not args.skip_validator
    output_directory.mkdir(parents=True, exist_ok=True)

    terminal_log_path, agents_log_path = clear_runtime_logs(base_dir)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    # 总耗时不再从 main 启动时开始算，而是从用户真正提交任务后开始算。
    start_time: float | None = None
    start_timestamp = ""
    task = ""
    run_status = "SUCCESS"

    with terminal_log_path.open("a", encoding="utf-8") as terminal_log_file:
        sys.stdout = TeeStream(original_stdout, terminal_log_file)
        sys.stderr = TeeStream(original_stderr, terminal_log_file)

        try:
            command_text = " ".join([os.path.basename(sys.executable), *sys.argv])
            print("=" * 72)
            print("运行摘要（开始）")
            print("=" * 72)
            print(f"运行命令: {command_text}")
            print(f"输出目录: {output_directory}")
            print(f"启用 validator: {'是' if enable_validator else '否'}")
            print("=" * 72)
            print(command_text)

            agent = DBEnvGenerationAgent(
                project_directory=output_directory,
                log_file_path=agents_log_path,
                enable_validator=enable_validator,
            )
            task = read_interactive_task()
            start_time = time.time()
            start_timestamp = get_utc_timestamp()
            print(f"任务开始时间: {start_timestamp}")
            print(f"任务内容: {task}")
            print(task)
            final_answer = agent.run(task)
            print(f"\nFinal Answer: {final_answer}")
        except Exception:
            run_status = "FAILED"
            raise
        finally:
            end_timestamp = get_utc_timestamp()
            duration_seconds = round(time.time() - start_time, 2) if start_time else 0
            print("\n" + "=" * 72)
            print("运行摘要（结束）")
            print("=" * 72)
            print(f"任务开始时间: {start_timestamp or '未开始'}")
            print(f"结束时间: {end_timestamp}")
            print(f"运行状态: {run_status}")
            print(f"总耗时: {duration_seconds} 秒")
            print(f"输出目录: {output_directory}")
            print(f"启用 validator: {'是' if enable_validator else '否'}")
            print(f"任务内容: {task or '未输入任务'}")
            print("=" * 72)
            sys.stdout = original_stdout
            sys.stderr = original_stderr


if __name__ == "__main__":
    main()
