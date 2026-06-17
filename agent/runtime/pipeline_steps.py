"""Main four-agent pipeline step implementations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.generator import generate_project
from agent.models import (
    EnvironmentPlan,
    EnvironmentProfile,
    EvidenceItem,
    ParsedTaskBundle,
    PipelineResult,
    ProjectArtifacts,
    TaskInput,
)
from agent.parser import parse_task_bundle
from agent.planner import build_environment_plan
from agent.profiler import build_environment_profile
from agent.runtime.progress import TerminalSpinner


@dataclass
class StepOutcome:
    """Result object displayed in the terminal for one step."""

    thought: str
    action: str
    observation: str
    result: str
    duration_seconds: float
    token_usage: dict[str, int] = field(default_factory=dict)


@dataclass
class RunState:
    """Shared intermediate state for one pipeline run."""

    parsed_bundle: ParsedTaskBundle | None = None
    task: TaskInput | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    inferred_db_type: str = ""
    vulnerability_info: dict = field(default_factory=dict)
    profile: EnvironmentProfile | None = None
    environment_plan: EnvironmentPlan | None = None
    artifacts: ProjectArtifacts | None = None
    run_dir: Path | None = None
    written_files: list[str] = field(default_factory=list)
    pipeline_result: PipelineResult | None = None


class PipelineSteps:
    """Host the main parser, profiler, planner, and generator flow."""

    def __init__(
        self,
        *,
        project_directory: Path,
        client,
        log_agent_payload: Callable[[str, dict], None],
    ) -> None:
        """Inject shared dependencies required by step execution."""
        self.project_directory = project_directory
        self.client = client
        self.log_agent_payload = log_agent_payload

    def _token_snapshot(self) -> dict[str, int]:
        """Capture cumulative LLM token usage before a step runs."""
        if hasattr(self.client, "token_usage_snapshot"):
            return self.client.token_usage_snapshot()
        return {}

    def _token_delta(self, before: dict[str, int]) -> dict[str, int]:
        """Calculate LLM token usage consumed by the current step."""
        if hasattr(self.client, "token_usage_delta"):
            return self.client.token_usage_delta(before)
        return {}

    def handlers(self) -> list[Callable[[RunState, str, float], StepOutcome]]:
        """Return all step handlers in main-flow order."""
        return [
            self.run_parser_step,
            self.run_profiler_step,
            self.run_planner_step,
            self.run_generator_step,
        ]

    def run_parser_step(
        self,
        state: RunState,
        user_input: str,
        step_start_time: float,
        *,
        refresh_cve_cache: bool = False,
    ) -> StepOutcome:
        """Run step 1: parse user input and collect evidence."""
        token_start = self._token_snapshot()
        with TerminalSpinner("Preparing Parser Module") as progress:
            state.parsed_bundle = parse_task_bundle(
                user_input,
                self.client,
                refresh_cve_cache=refresh_cve_cache,
                status_callback=progress.update,
                notice_callback=progress.notice,
            )
        state.task = state.parsed_bundle.task
        state.evidence = state.parsed_bundle.evidence
        state.inferred_db_type = state.parsed_bundle.inferred_db_type
        state.vulnerability_info = state.parsed_bundle.vulnerability_info
        self.log_agent_payload("parser", state.parsed_bundle.to_dict())
        observation = {
            "task": state.task.to_dict(),
            "evidence_count": len(state.evidence),
            "inferred_db_type": state.inferred_db_type,
            "evidence_sources": [item.source_type for item in state.evidence],
            "vulnerability_info_available": bool(state.vulnerability_info),
            "collection_error_count": len(
                state.vulnerability_info.get("collection_errors", [])
                if isinstance(state.vulnerability_info.get("collection_errors"), list)
                else []
            ),
            "collection_errors": (
                state.vulnerability_info.get("collection_errors", [])[:3]
                if isinstance(state.vulnerability_info.get("collection_errors"), list)
                else []
            ),
        }
        return StepOutcome(
            thought="Parsed the request into TaskInput and assembled cached or externally collected CVE evidence when applicable.",
            action="LLM JSON parsing -> cache/NVD lookup -> relevance classification -> advisory integration",
            observation=json.dumps(observation, ensure_ascii=False, indent=2),
            result=(
                f"Identified CVE ID: {state.task.cve_id or 'not provided'}, "
                f"database type: {state.task.db_type or state.inferred_db_type or 'unidentified'}, "
                f"collected {len(state.evidence)} evidence item(s)."
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
            token_usage=self._token_delta(token_start),
        )

    def run_profiler_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """Run step 2: build an environment profile from the task and parser context."""
        assert state.task is not None
        token_start = self._token_snapshot()
        with TerminalSpinner("Preparing Profiler Module") as progress:
            state.profile = build_environment_profile(
                state.task,
                state.inferred_db_type,
                state.vulnerability_info,
                self.client,
                status_callback=progress.update,
            )
        self.log_agent_payload("profiler", state.profile.to_dict())
        observation = {
            "profile_status": state.profile.profile_status,
            "project_name": state.profile.target.project_name,
            "db_type": state.profile.target.db_type,
            "relevance_type": state.profile.asset.relevance_type,
            "component_name": state.profile.asset.component_name,
            "requested_version": state.profile.version.requested_version,
            "final_version": state.profile.version.final_version,
            "candidate_versions": [
                item.version for item in state.profile.version.candidate_versions
            ],
            "artifact_count": len(state.profile.artifact_requirements),
        }
        return StepOutcome(
            thought="Converted the parser bundle into a reproduction profile without selecting a concrete Docker build path.",
            action="LLM EnvironmentProfile generation with schema validation",
            observation=json.dumps(observation, ensure_ascii=False, indent=2),
            result=(
                f"Generated environment profile, database type: {state.profile.target.db_type}, "
                f"final version: {state.profile.version.final_version or 'unconfirmed'}."
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
            token_usage=self._token_delta(token_start),
        )

    def run_planner_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """Run step 3: generate a build plan from the profile and probe artifacts."""
        assert state.profile is not None
        token_start = self._token_snapshot()
        with TerminalSpinner("Preparing Planner Module") as progress:
            state.environment_plan = build_environment_plan(
                state.profile,
                self.client,
                status_callback=progress.update,
            )
        payload = {"environment_plan": state.environment_plan.to_dict()}
        self.log_agent_payload("planner", payload)
        requirements = state.environment_plan.generation_requirements
        selected_version = state.environment_plan.build_plan.selected_version
        terminal_observation = {
            "project_name": requirements.get("project_name", ""),
            "db_type": requirements.get("db_type", ""),
            "selected_version": selected_version,
            "build_path": state.environment_plan.build_plan.build_path,
            "build_style": state.environment_plan.build_plan.build_style,
            "verified_artifact_count": len(state.environment_plan.verified_artifacts),
        }
        return StepOutcome(
            thought="Traversed the strategy graph using profile facts, catalog recommendations, and artifact availability.",
            action="decision graph traversal -> template lookup -> image/source/component probes",
            observation=json.dumps(terminal_observation, ensure_ascii=False, indent=2),
            result=(
                f"Generated environment plan, build path: {state.environment_plan.build_plan.build_path}, "
                f"final version: {selected_version or 'unconfirmed'}."
            ),
            duration_seconds=round(time.time() - step_start_time, 2),
            token_usage=self._token_delta(token_start),
        )

    def run_generator_step(
        self,
        state: RunState,
        _user_input: str,
        step_start_time: float,
    ) -> StepOutcome:
        """Run step 4: generate project files from the planner blueprint and write them to disk."""
        assert state.task is not None
        assert state.environment_plan is not None
        token_start = self._token_snapshot()
        with TerminalSpinner("Preparing Generator Module") as progress:
            state.artifacts, state.run_dir, state.written_files = generate_project(
                blueprint=state.environment_plan,
                output_directory=self.project_directory,
                client=self.client,
                status_callback=progress.update,
            )
        state.pipeline_result = PipelineResult(
            run_dir=state.run_dir,
            task=state.task,
            evidence=state.evidence,
            environment_plan=state.environment_plan,
            artifacts=state.artifacts,
        )
        payload = {
            "run_dir": str(state.run_dir),
            "written_files": state.written_files,
            "artifacts": state.artifacts.to_dict(),
            "pipeline_result": state.pipeline_result.to_dict(),
        }
        self.log_agent_payload("generator", payload)
        observation = {
            "run_dir": str(state.run_dir),
            "written_files": state.written_files,
            "generated_files": [file.path for file in state.artifacts.files],
        }
        return StepOutcome(
            thought="Generated the project only from EnvironmentPlan, validated implementation-level references, and wrote the resulting artifacts.",
            action="LLM generation -> constrained ReAct verification -> artifact validation -> filesystem write",
            observation=json.dumps(observation, ensure_ascii=False, indent=2),
            result=f"Project generated and written to {state.run_dir}.",
            duration_seconds=round(time.time() - step_start_time, 2),
            token_usage=self._token_delta(token_start),
        )
