"""Main scheduler."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.config import load_settings
from agent.llm import JsonChatClient
from agent.models import PipelineResult
from agent.runtime.pipeline_steps import PipelineSteps, RunState, StepOutcome


class DBEnvGenerationAgent:
    """Main scheduler for database environment project generation."""

    STAGE_NAMES = (
        "Parser Module",
        "Profiler Module",
        "Planner Module",
        "Generator Module",
    )

    def __init__(
        self,
        project_directory: Path,
        log_file_path: Path,
    ) -> None:
        """Initialize the scheduler and shared LLM client."""
        self.project_directory = project_directory
        self.log_file_path = log_file_path
        self.client = JsonChatClient(load_settings())

    def run(self, user_input: str) -> str:
        """Run the full pipeline."""
        plan = self.create_plan()
        print("\n" + "=" * 72)
        print("◆ DVEG Generation Pipeline")
        print("=" * 72)
        for index, step in enumerate(plan, start=1):
            print(
                f"  {self.get_stage_number(index)} "
                f"{self.STAGE_NAMES[index - 1]}: {step}"
            )

        runner = PipelineSteps(
            project_directory=self.project_directory,
            client=self.client,
            log_agent_payload=self.log_agent_payload,
        )
        run_state = RunState()
        step_handlers = runner.handlers()

        for index, step in enumerate(plan, start=1):
            print("\n" + "=" * 72)
            print(
                f"{self.get_stage_number(index)} "
                f"{self.STAGE_NAMES[index - 1]}"
            )
            print(f" Purpose: {step}")
            print(f" Execution: {self.get_step_executor_label(index)}")
            print("=" * 72)
            step_start_time = time.time()
            outcome = step_handlers[index - 1](run_state, user_input, step_start_time)
            self._print_outcome(outcome)

        assert run_state.pipeline_result is not None
        return self.create_final_answer(run_state.pipeline_result)

    def run_parser_only(
        self,
        user_input: str,
        *,
        refresh_cve_cache: bool = False,
    ) -> dict[str, Any]:
        """Run only the parser stage and return the parser bundle payload."""
        print("\n" + "=" * 72)
        print("◆ DVEG Parser-Only Pipeline")
        print("=" * 72)
        print(
            "  [1/1] Parser Module: structure the request and build CVE evidence context"
        )

        runner = PipelineSteps(
            project_directory=self.project_directory,
            client=self.client,
            log_agent_payload=self.log_agent_payload,
        )
        run_state = RunState()
        step_start_time = time.time()
        print("\n" + "=" * 72)
        print("[1/1] Parser Module")
        print(" Purpose: structure the request and build CVE evidence context")
        print(f" Execution: {self.get_step_executor_label(1)}")
        print("=" * 72)
        outcome = runner.run_parser_step(
            run_state,
            user_input,
            step_start_time,
            refresh_cve_cache=refresh_cve_cache,
        )
        self._print_outcome(outcome)

        assert run_state.parsed_bundle is not None
        return run_state.parsed_bundle.to_dict()

    def create_plan(self) -> list[str]:
        """Define the fixed execution plan."""
        return [
            "structure the request and build CVE evidence context",
            "derive the reproduction profile, affected asset, version, and constraints",
            "execute the decision graph and verify required build artifacts",
            "generate, validate, and write the Docker project",
        ]

    def create_final_answer(self, result: PipelineResult) -> str:
        """Build the final natural-language response."""
        generated_files = ", ".join(file.path for file in result.artifacts.files)
        build_plan = result.environment_plan.build_plan
        requirements = result.environment_plan.generation_requirements
        selected_version = build_plan.selected_version
        cve_id = str(requirements.get("cve_id") or "").strip()
        db_type = str(requirements.get("db_type") or "").strip()
        incomplete = any(
            file.path == "GENERATION_STATUS.md"
            for file in result.artifacts.files
        )
        return (
            f"Project status: {'INCOMPLETE' if incomplete else 'GENERATED'}. "
            f"Target: {cve_id + ' / ' if cve_id else ''}"
            f"{db_type or result.task.db_type} "
            f"{selected_version or result.task.version}. "
            f"Build path: {build_plan.build_path}. "
            f"Verified artifacts: {len(result.environment_plan.verified_artifacts)}. "
            f"Output: {result.run_dir}. "
            f"Files: {generated_files}."
        )

    def get_step_executor_label(self, step_index: int) -> str:
        """Return the executor label for the current stage by step index."""
        executor_labels = {
            1: "LLM JSON parsing + NVD/advisory evidence tools + local CVE cache",
            2: "LLM profile generation from structured parser context",
            3: "deterministic decision graph + template catalogs + artifact probes",
            4: "LLM project generation + constrained ReAct tools + filesystem tools",
        }
        return executor_labels.get(step_index, "unknown")

    @staticmethod
    def get_stage_number(step_index: int) -> str:
        return f"[{step_index}/4]"

    def _print_outcome(self, outcome: StepOutcome) -> None:
        """Print a single step outcome consistently."""
        print("\n Process:")
        print(outcome.thought)
        print(f"\n Implementation: {outcome.action}")
        print("\n Structured output:")
        print(outcome.observation)
        print("\n✓ Stage result: COMPLETED")
        print(outcome.result)
        print(f"\n Duration: {outcome.duration_seconds} seconds")
        print(" LLM usage:")
        print(self._format_token_usage(outcome.token_usage))
        print("-" * 72)

    @staticmethod
    def _format_token_usage(usage: dict[str, int] | None) -> str:
        """Format token counters for terminal output."""
        usage = usage or {}
        return (
            f"prompt={usage.get('prompt_tokens', 0)}, "
            f"completion={usage.get('completion_tokens', 0)}, "
            f"total={usage.get('total_tokens', 0)}, "
            f"calls={usage.get('calls', 0)}"
        )

    def log_agent_payload(self, agent_name: str, payload: dict[str, Any]) -> None:
        """Write structured stage outputs to the log file."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_name": agent_name,
            "payload": payload,
        }
        with self.log_file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, indent=2))
            file.write("\n\n")
