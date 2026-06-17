"""Strategy-graph-driven build plan generator.

The planner consumes only the environment profile provided by the profiler. It handles artifact probing, build path/template selection, and build plan creation. It does not regenerate the profile or re-decide database type, version, or configuration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from agent.config import BASE_DIR
from agent.llm import JsonChatClient
from agent.models import (
    ArtifactFact,
    BuildPlan,
    EnvironmentPlan,
    EnvironmentProfile,
    ProbeRequest,
)
from tools.url_probe_tools import check_download_url
from tools.registry_tools import check_image_ref, resolve_image_source_for_candidates


MAX_PROBE_REQUESTS = 6
SOURCE_ARTIFACT_KINDS = {"source_archive", "git_repo"}
PROBEABLE_COMPONENT_ARTIFACT_KINDS = {"source_archive", "git_repo", "binary_archive"}
PACKAGE_ECOSYSTEMS = {"debian", "ubuntu", "alpine", "redhat"}
LANGUAGE_PACKAGE_ECOSYSTEMS = {"maven", "npm", "pip", "gem", "cargo", "go", "nuget"}
PREBUILT_DISTRO_CANDIDATES = [
    "ubuntu2204",
    "ubuntu2004",
    "ubuntu1804",
    "ubuntu1604",
    "ubuntu1404",
    "debian12",
    "debian11",
    "debian10",
    "debian92",
    "debian81",
]
StatusCallback = Callable[[str], None]


def _update_status(status_callback: StatusCallback | None, operation: str) -> None:
    if status_callback is not None:
        status_callback(operation)


def build_environment_plan(
    profile: EnvironmentProfile,
    client: JsonChatClient,
    status_callback: StatusCallback | None = None,
) -> EnvironmentPlan:
    """Read and execute decision_graph.yaml to generate a build plan from the profiler profile."""
    _update_status(status_callback, "Loading the build strategy decision graph")
    graph = _load_decision_graph()
    _update_status(status_callback, "Reading the database build-path catalog")
    template_recommendation = _load_template_recommendation(profile)
    _update_status(status_callback, "Checking profile-declared runtime images")
    host_image_facts = _probe_primary_database_container_images(profile)
    _update_status(status_callback, "Probing the recommended prebuilt binary")
    prebuilt_facts = _probe_recommended_prebuilt_binary(
        profile,
        template_recommendation,
    )
    execution = _execute_graph(
        profile,
        graph,
        client,
        pre_facts=[*host_image_facts, *prebuilt_facts],
        template_recommendation=template_recommendation,
        status_callback=status_callback,
    )
    artifact_facts = execution["artifact_facts"]
    template_recommendation = execution["template_recommendation"]
    terminal_id = execution["terminal_id"]
    terminal_plan = _terminal_plan(graph, terminal_id)
    terminal_build_path = str(terminal_plan.get("build_path", terminal_id))
    _update_status(
        status_callback,
        f"Selected build path: {terminal_build_path}",
    )
    image_fact = (
        _first_available_fact(artifact_facts, "dockerhub_tag")
        if terminal_build_path.startswith("official_image")
        else None
    )
    build_plan = _build_plan(
        profile=profile,
        template_recommendation=template_recommendation,
        build_path=terminal_build_path,
        build_style=str(terminal_plan.get("build_style", "")),
        image_fact=image_fact,
    )
    prebuilt_fact = _first_available_fact(artifact_facts, "prebuilt_binary_url")
    if build_plan.build_path == "prebuilt_binary" and prebuilt_fact is not None:
        build_plan = BuildPlan(
            build_path=build_plan.build_path,
            selected_version=prebuilt_fact.version,
            selected_image=build_plan.selected_image,
            selected_download_url=prebuilt_fact.ref,
            selected_package_repo=build_plan.selected_package_repo,
            selected_package_name=build_plan.selected_package_name,
            build_style=build_plan.build_style,
        )
    source_facts: list[ArtifactFact] = []
    if build_plan.build_path == "source_compile":
        _update_status(status_callback, "Resolving and probing source artifacts")
        if not _catalog_entry(template_recommendation):
            template_recommendation = _load_template_recommendation(profile)
        build_plan, source_facts = _resolve_source_artifact(
            profile=profile,
            catalog_entry=_catalog_entry(template_recommendation),
            build_plan=build_plan,
        )
    if build_plan.build_path != "source_compile":
        _update_status(status_callback, "Probing required affected-component artifacts")
    component_facts = (
        []
        if build_plan.build_path == "source_compile"
        else _probe_required_affected_component_artifacts(profile)
    )
    all_artifact_facts = [*artifact_facts, *source_facts, *component_facts]
    _update_status(status_callback, "Assembling the final EnvironmentPlan")
    return EnvironmentPlan(
        build_plan=build_plan,
        generation_requirements=_generation_requirements(
            profile=profile,
            build_plan=build_plan,
            template_recommendation=template_recommendation,
            artifact_facts=all_artifact_facts,
        ),
        verified_artifacts=_verified_artifacts(all_artifact_facts),
    )


def _load_decision_graph() -> dict[str, Any]:
    graph_path = BASE_DIR.parent / "strategy-selection" / "decision_graph.yaml"
    graph = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise ValueError(f"Invalid decision graph: {graph_path}")
    return graph


def _execute_graph(
    profile: EnvironmentProfile,
    graph: dict[str, Any],
    client: JsonChatClient,
    pre_facts: list[ArtifactFact] | None = None,
    template_recommendation: dict[str, Any] | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    edges = [
        edge
        for edge in graph.get("edges", [])
        if isinstance(edge, dict)
    ]
    current = str(graph.get("entry_node", ""))
    if current not in nodes:
        raise ValueError(f"Invalid graph entry_node: {current}")

    state: dict[str, Any] = {
        "artifact_facts": list(pre_facts or []),
        "template_recommendation": template_recommendation or {},
        "notes": [],
    }
    steps: list[str] = []
    visited = 0
    while current:
        visited += 1
        if visited > 64:
            raise RuntimeError("Decision graph exceeded maximum traversal depth.")
        steps.append(current)
        node = nodes[current]
        _update_status(
            status_callback,
            f"Decision graph node: {current} ({node.get('type', 'unknown')})",
        )
        _execute_node(
            profile,
            node,
            state,
            client,
            status_callback=status_callback,
        )
        if node.get("type") == "terminal":
            return {
                "terminal_id": current,
                "steps": steps,
                "artifact_facts": state["artifact_facts"],
                "template_recommendation": state["template_recommendation"],
                "notes": state["notes"],
            }
        next_edge = _select_edge(profile, graph, edges, current, state)
        if next_edge is None:
            raise RuntimeError(f"No matching edge from decision graph node: {current}")
        current = str(next_edge.get("to", ""))
    raise RuntimeError("Decision graph traversal ended without terminal node.")


def _execute_node(
    profile: EnvironmentProfile,
    node: dict[str, Any],
    state: dict[str, Any],
    client: JsonChatClient,
    *,
    status_callback: StatusCallback | None = None,
) -> None:
    node_type = node.get("type")
    node_id = node.get("id")
    if node_type == "tool_check" and node.get("tool") == "check_image":
        _update_status(status_callback, "Probing official Docker image candidates")
        facts = [*state.get("artifact_facts", []), *_probe_official_images(profile, client)]
        state["artifact_facts"] = facts
        state["image_available"] = _first_available_fact(facts, "dockerhub_tag") is not None
        return
    if node_type == "template_read":
        _update_status(status_callback, "Reading the database build-path catalog")
        recommendation = _load_template_recommendation(profile)
        state["template_recommendation"] = recommendation
        state["catalog_next_path"] = _next_catalog_raw_path(
            profile=profile,
            template_recommendation=recommendation,
            image_available=bool(state.get("image_available")),
            prebuilt_binary_available=(
                _first_available_fact(
                    state.get("artifact_facts", []),
                    "prebuilt_binary_url",
                )
                is not None
            ),
        )
        return
    if node_id == "source_build":
        if not _catalog_entry(state.get("template_recommendation", {})):
            state["template_recommendation"] = _load_template_recommendation(profile)
        state["source_build_style"] = _source_build_style(
            profile,
            state.get("template_recommendation", {}),
        )
    if node_id == "package_repo":
        state["package_repo_path"] = _select_package_repo_path(
            profile,
            state.get("template_recommendation", {}),
        )


def _select_edge(
    profile: EnvironmentProfile,
    graph: dict[str, Any],
    edges: list[dict[str, Any]],
    current: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    outgoing = [edge for edge in edges if edge.get("from") == current]
    default_edge: dict[str, Any] | None = None
    for edge in outgoing:
        condition = edge.get("condition")
        if isinstance(condition, dict) and condition.get("default"):
            default_edge = edge
            continue
        if _condition_matches(profile, graph, condition, state):
            return edge
    return default_edge


def _condition_matches(
    profile: EnvironmentProfile,
    graph: dict[str, Any],
    condition: Any,
    state: dict[str, Any],
) -> bool:
    if condition is None:
        return True
    if not isinstance(condition, dict):
        return False
    if condition.get("always"):
        return True
    if "any" in condition:
        return any(
            _condition_matches(profile, graph, item, state)
            for item in condition.get("any", [])
        )
    if "all" in condition:
        return all(
            _condition_matches(profile, graph, item, state)
            for item in condition.get("all", [])
        )
    actual = _condition_value(profile, graph, condition, state)
    expected = condition.get("value")
    op = condition.get("op", "eq")
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in (expected or [])
    return False


def _condition_value(
    profile: EnvironmentProfile,
    graph: dict[str, Any],
    condition: dict[str, Any],
    state: dict[str, Any],
) -> Any:
    if "field" in condition:
        return _profile_value(profile, str(condition["field"]))
    if "fact" in condition:
        return _fact_value(profile, graph, str(condition["fact"]), state)
    return None


def _profile_value(profile: EnvironmentProfile, path: str) -> Any:
    value: Any = profile
    for part in path.split("."):
        value = getattr(value, part)
    return value


def _fact_value(
    profile: EnvironmentProfile,
    graph: dict[str, Any],
    name: str,
    state: dict[str, Any],
) -> Any:
    if name == "prebuilt_binary_available":
        return _first_available_fact(
            state.get("artifact_facts", []),
            "prebuilt_binary_url",
        ) is not None
    if name == "source_build_mandatory":
        return profile.construction_constraints.requires_source_build
    if name == "image_available":
        return bool(state.get("image_available"))
    if name == "source_required_after_image_miss":
        return not bool(state.get("image_available")) and _requires_source_build(profile)
    if name == "needs_extended_image":
        return _needs_extended_image(profile, state.get("template_recommendation", {}))
    if name == "source_build_style":
        return state.get("source_build_style") or _source_build_style(
            profile,
            state.get("template_recommendation", {}),
        )
    if name == "language_package_sufficient":
        return (
            profile.asset.package_ecosystem in LANGUAGE_PACKAGE_ECOSYSTEMS
            and bool(profile.asset.package_name)
        )
    if name == "system_package_sufficient":
        return _select_package_repo_path(profile, state.get("template_recommendation", {})) == "system_package_repo"
    if name == "custom_package_required":
        return _select_package_repo_path(profile, state.get("template_recommendation", {})) == "custom_package_repo"
    if name == "catalog_next_path":
        return state.get("catalog_next_path") or _next_catalog_raw_path(
            profile=profile,
            template_recommendation=state.get("template_recommendation", {}),
            image_available=bool(state.get("image_available")),
            prebuilt_binary_available=(
                _first_available_fact(
                    state.get("artifact_facts", []),
                    "prebuilt_binary_url",
                )
                is not None
            ),
        )
    return None


def _terminal_plan(graph: dict[str, Any], terminal_id: str) -> dict[str, Any]:
    plans = graph.get("terminal_plans")
    if isinstance(plans, dict):
        plan = plans.get(terminal_id)
        if isinstance(plan, dict):
            return plan
    return {"build_path": terminal_id}


def _probe_official_images(
    profile: EnvironmentProfile,
    client: JsonChatClient,
) -> list[ArtifactFact]:
    facts: list[ArtifactFact] = []
    profile_facts = _probe_profiler_dockerhub_image_candidates(profile)
    facts.extend(profile_facts)
    if _first_available_fact(profile_facts, "dockerhub_tag") is not None:
        return facts

    image_selection = _select_dockerhub_images(profile, client)
    selected_images = image_selection["selected_images"]
    if not selected_images:
        facts.append(
            ArtifactFact(
                fact_type="dockerhub_tag",
                source="docker_hub",
                identifier=profile.target.db_type,
                version=_fallback_version(profile),
                ref="",
                available=False,
                notes=[
                    str(image_selection.get("reason", ""))[:240]
                    or "planner did not select a DockerHub image candidate."
                ],
            )
        )
        return facts
    versions = _candidate_versions(profile) or [profile.version.final_version or ""]
    for version in [item for item in versions if item][:MAX_PROBE_REQUESTS]:
        request = ProbeRequest(
            action="check_image",
            db_type=profile.target.db_type,
            version=version,
        )
        fact = _probe_image_fact(
            profile=profile,
            request=request,
            image_candidates=selected_images,
            selection_reason=str(image_selection.get("reason", "")),
        )
        _upsert_fact(facts, fact)
        if fact.available:
            break
    return facts


def _probe_profiler_dockerhub_image_candidates(
    profile: EnvironmentProfile,
) -> list[ArtifactFact]:
    facts: list[ArtifactFact] = []
    for candidate in profile.dockerhub_image_candidates:
        repository = candidate.repository.strip()
        if not repository:
            continue
        versions = candidate.tags or _candidate_versions(profile) or [
            profile.version.final_version or ""
        ]
        for version in [item for item in versions if item][:MAX_PROBE_REQUESTS]:
            request = ProbeRequest(
                action="check_image",
                db_type=profile.target.db_type,
                version=version,
            )
            fact = _probe_image_fact(
                profile=profile,
                request=request,
                image_candidates=[repository],
                selection_reason=_profiler_image_selection_reason(candidate.reason),
            )
            _upsert_fact(facts, fact)
            if fact.available:
                return facts
    return facts


def _profiler_image_selection_reason(reason: str) -> str:
    suffix = reason.strip()
    base = (
        "Selected from profiler-provided DockerHub image candidates before "
        "catalog fallback."
    )
    return f"{base} {suffix}" if suffix else base


def _select_dockerhub_images(
    profile: EnvironmentProfile,
    _client: JsonChatClient,
) -> dict[str, Any]:
    """Determine the image to probe from the DockerHub catalog by normalized db_type."""
    catalog = _load_dockerhub_repository_catalog()
    if not catalog["entries"]:
        return {
            "selected_images": [],
            "reason": "dockerhub_repository_catalog.jsonl is empty or unavailable.",
            "notes": catalog["parse_errors"],
        }

    db_type = profile.target.db_type.strip().lower()
    notes = list(catalog["parse_errors"])
    for entry in catalog["entries"]:
        if str(entry.get("db_type", "")).strip().lower() != db_type:
            continue
        notes.extend(_strings_from_list(entry.get("notes")))
        selected_images = _strings_from_list(entry.get("images"))
        policy = str(entry.get("policy", "")).strip().lower()
        if policy == "skip_if_no_suitable_image" or not selected_images:
            return {
                "selected_images": [],
                "reason": f"DockerHub check skipped by catalog policy for db_type={db_type}.",
                "confidence": "high",
                "notes": notes,
            }
        return {
            "selected_images": selected_images,
            "reason": f"Selected DockerHub images by catalog db_type match: {db_type}.",
            "confidence": "high",
            "notes": notes,
        }
    return {
        "selected_images": [],
        "reason": f"No DockerHub catalog entry for db_type={db_type}.",
        "confidence": "high",
        "notes": notes,
    }


def _load_dockerhub_repository_catalog() -> dict[str, Any]:
    catalog_path = BASE_DIR.parent / "templates" / "dockerhub_repository_catalog.jsonl"
    if not catalog_path.exists():
        return {"entries": [], "parse_errors": [f"{catalog_path} not found."]}
    entries, parse_errors = _read_json_catalog_objects(catalog_path)
    return {
        "entries": entries,
        "parse_errors": parse_errors,
        "catalog_path": str(catalog_path),
    }


def _strings_from_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _load_template_recommendation(profile: EnvironmentProfile) -> dict[str, Any]:
    """Read the local database build-path recommendation table without any external download probing."""
    catalog_path = BASE_DIR.parent / "templates" / "db_build_path_catalog.jsonl"
    db_type = _normalize_key(profile.target.db_type)
    if not catalog_path.exists():
        return {
            "matched": False,
            "db_type": profile.target.db_type,
            "catalog_path": str(catalog_path),
            "notes": ["db_build_path_catalog.jsonl not found."],
        }

    entries, parse_errors = _read_json_catalog_objects(catalog_path)

    for entry in entries:
        entry_db_type = _normalize_key(str(entry.get("db_type", "")))
        if entry_db_type == db_type:
            return {
                "matched": True,
                "catalog_path": str(catalog_path),
                "entry": entry,
                "notes": parse_errors,
            }

    return {
        "matched": False,
        "db_type": profile.target.db_type,
        "catalog_path": str(catalog_path),
        "available_db_types": [
            str(entry.get("db_type", "")).strip()
            for entry in entries
            if str(entry.get("db_type", "")).strip()
        ],
        "notes": parse_errors,
    }


def _probe_image_fact(
    *,
    profile: EnvironmentProfile,
    request: ProbeRequest,
    image_candidates: list[str],
    selection_reason: str,
) -> ArtifactFact:
    """Check whether the Docker Hub tag for the specified version exists."""
    image_resolution = resolve_image_source_for_candidates(
        db_type=request.db_type or profile.target.db_type,
        version=request.version or _fallback_version(profile),
        image_candidates=image_candidates,
    )
    identifier = image_resolution.repository or request.db_type
    if image_resolution.namespace and image_resolution.namespace != "library":
        identifier = f"{image_resolution.namespace}/{identifier}"
    notes = [item for item in [selection_reason, *image_resolution.notes] if item]
    return ArtifactFact(
        fact_type="dockerhub_tag",
        source="docker_hub",
        identifier=identifier,
        version=request.version,
        ref=image_resolution.image_ref,
        available=image_resolution.availability == "tag_found",
        notes=notes[:3],
    )


def _probe_primary_database_container_images(profile: EnvironmentProfile) -> list[ArtifactFact]:
    facts: list[ArtifactFact] = []
    for artifact in profile.artifact_requirements:
        if artifact.kind != "container_image" or artifact.purpose != "primary_database":
            continue
        image_ref = _artifact_image_ref(artifact.identifier, artifact.version_constraint)
        if not image_ref:
            continue
        result = check_image_ref(image_ref)
        facts.append(
            ArtifactFact(
                fact_type="dockerhub_tag",
                source="docker_hub",
                identifier=str(result.get("repository") or artifact.identifier),
                version=str(result.get("tag") or artifact.version_constraint),
                ref=str(result.get("image_ref") or image_ref),
                available=bool(result.get("available")),
                notes=[
                    "purpose=primary_database",
                    *[str(item) for item in result.get("notes", [])],
                ],
            )
        )
    return facts


def _probe_recommended_prebuilt_binary(
    profile: EnvironmentProfile,
    template_recommendation: dict[str, Any],
) -> list[ArtifactFact]:
    """Probe a catalog-recommended prebuilt binary before source fallback."""
    entry = _catalog_entry(template_recommendation)
    if str(entry.get("recommended_path", "")).strip() != "prebuilt_binary":
        return []
    version = _selected_version(profile)
    binary_url = _render_source_url(
        str(entry.get("binary_url", "") or ""),
        version,
    )
    urls = _prebuilt_binary_url_candidates(binary_url)
    facts: list[ArtifactFact] = []
    for url in urls:
        result = check_download_url(url)
        facts.append(
            ArtifactFact(
                fact_type="prebuilt_binary_url",
                source="planner",
                identifier=profile.target.db_type,
                version=version,
                ref=url,
                available=bool(result.get("available")),
                notes=[
                    *(
                        [f"expanded $DISTRO candidate from template: {binary_url}"]
                        if "$DISTRO" in binary_url or "${DISTRO}" in binary_url
                        else []
                    ),
                    *[str(item) for item in result.get("notes", [])],
                    f"status_code={result.get('status_code', 0)}",
                ],
            )
        )
        if facts[-1].available:
            break
    return facts


def _prebuilt_binary_url_candidates(binary_url: str) -> list[str]:
    """Expand known distribution placeholders before probing prebuilt binaries."""
    url = binary_url.strip()
    if not url:
        return []
    if "$DISTRO" not in url and "${DISTRO}" not in url:
        return [url]
    return [
        url.replace("${DISTRO}", distro).replace("$DISTRO", distro)
        for distro in PREBUILT_DISTRO_CANDIDATES
    ]


def _artifact_image_ref(identifier: str, version_constraint: str) -> str:
    image_ref = identifier.strip()
    if not image_ref:
        return ""
    if ":" in image_ref.rsplit("/", 1)[-1]:
        return image_ref
    version = version_constraint.strip()
    return f"{image_ref}:{version}" if version else ""


def _fallback_version(profile: EnvironmentProfile) -> str:
    if profile.version.candidate_versions:
        return profile.version.candidate_versions[0].version
    return profile.version.final_version or ""


def _build_plan(
    *,
    profile: EnvironmentProfile,
    template_recommendation: dict[str, Any],
    build_path: str,
    build_style: str,
    image_fact: ArtifactFact | None = None,
) -> BuildPlan:
    catalog_entry = _catalog_entry(template_recommendation)
    selected_version = image_fact.version if image_fact else _selected_version(profile)
    selected_image = image_fact.ref if image_fact and image_fact.available else ""
    selected_download_url = _selected_download_url(
        profile=profile,
        catalog_entry=catalog_entry,
        build_path=build_path,
    )
    selected_package_repo = _selected_package_repo(profile, catalog_entry, build_path)
    selected_package_name = _selected_package_name(profile, catalog_entry, build_path)
    selected_build_style = build_style.strip() or _build_style(catalog_entry)

    return BuildPlan(
        build_path=build_path,
        selected_version=selected_version,
        selected_image=selected_image,
        selected_download_url=selected_download_url,
        selected_package_repo=selected_package_repo,
        selected_package_name=selected_package_name,
        build_style=selected_build_style,
    )


def _requires_source_build(profile: EnvironmentProfile) -> bool:
    return profile.construction_constraints.requires_source_build


def _needs_extended_image(
    profile: EnvironmentProfile,
    template_recommendation: dict[str, Any],
) -> bool:
    if _catalog_path(template_recommendation) == "official_image_extended":
        return True
    if profile.construction_constraints.setup_requirements:
        return True
    if any(
        condition.required and condition.category.strip().lower() == "config"
        for condition in profile.vulnerability_conditions
    ):
        return True
    return any(
        artifact.kind != "container_image"
        for artifact in profile.artifact_requirements
    )


def _next_catalog_raw_path(
    *,
    profile: EnvironmentProfile,
    template_recommendation: dict[str, Any],
    image_available: bool,
    prebuilt_binary_available: bool,
) -> str:
    entry = _catalog_entry(template_recommendation)
    ordered_paths = [
        str(entry.get("recommended_path", "")).strip(),
        *[str(item).strip() for item in entry.get("fallback_order", [])],
    ]
    for raw_path in ordered_paths:
        build_path = _normalize_catalog_path(raw_path, profile)
        if not build_path:
            continue
        if build_path.startswith("official_image") and not image_available:
            continue
        if build_path == "prebuilt_binary" and not prebuilt_binary_available:
            continue
        if build_path == "source_compile":
            return "source_build"
        if build_path in {"system_package_repo", "custom_package_repo"}:
            return "package_repo"
        return build_path
    return "source_build"


def _select_package_repo_path(
    profile: EnvironmentProfile,
    template_recommendation: dict[str, Any],
) -> str:
    entry = _catalog_entry(template_recommendation)
    explicit_path = _normalize_catalog_path(str(entry.get("recommended_path", "")), profile)
    if explicit_path in {"language_package_repo", "system_package_repo", "custom_package_repo"}:
        return explicit_path
    if profile.asset.package_ecosystem in LANGUAGE_PACKAGE_ECOSYSTEMS and profile.asset.package_name:
        return "language_package_repo"
    if str(entry.get("custom_repo", "") or "").strip():
        return "custom_package_repo"
    if profile.asset.package_ecosystem in PACKAGE_ECOSYSTEMS and profile.asset.package_name:
        return "system_package_repo"
    return ""


def _normalize_catalog_path(raw_path: str, profile: EnvironmentProfile) -> str:
    if raw_path == "source_build":
        return "source_compile"
    if raw_path == "package_repo":
        if profile.asset.package_ecosystem in LANGUAGE_PACKAGE_ECOSYSTEMS and profile.asset.package_name:
            return "language_package_repo"
        if profile.asset.package_ecosystem in PACKAGE_ECOSYSTEMS and profile.asset.package_name:
            return "system_package_repo"
        return "custom_package_repo"
    if raw_path in {
        "official_image_direct",
        "official_image_extended",
        "custom_package_repo",
        "language_package_repo",
        "system_package_repo",
        "prebuilt_binary",
        "source_compile",
    }:
        return raw_path
    return ""


def _source_build_style(
    _profile: EnvironmentProfile,
    template_recommendation: dict[str, Any],
) -> str:
    build_style = str(_catalog_entry(template_recommendation).get("build_style", "")).strip()
    if build_style in {"multi_stage_server", "single_stage_embedded"}:
        return build_style
    return "multi_stage_server"


def _selected_version(profile: EnvironmentProfile) -> str:
    if profile.version.final_version:
        return profile.version.final_version
    versions = _candidate_versions(profile)
    if versions:
        return versions[0]
    return ""


def _selected_version_candidate(profile: EnvironmentProfile):
    selected_version = _selected_version(profile)
    for item in profile.version.candidate_versions:
        if item.version == selected_version:
            return item
    if profile.version.candidate_versions:
        return profile.version.candidate_versions[0]
    return None


def _candidate_versions(profile: EnvironmentProfile) -> list[str]:
    return [
        item.version
        for item in profile.version.candidate_versions
        if item.version
    ]


def _first_available_fact(
    facts: list[ArtifactFact],
    fact_type: str,
) -> ArtifactFact | None:
    for fact in facts:
        if fact.fact_type == fact_type and fact.available:
            return fact
    return None


def _selected_package_repo(
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
    build_path: str,
) -> str:
    if build_path == "custom_package_repo":
        return str(catalog_entry.get("custom_repo", "") or "").strip()
    if build_path == "language_package_repo":
        return str(catalog_entry.get("language_package_repo", "") or "").strip() or profile.asset.package_ecosystem
    return ""


def _selected_package_name(
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
    build_path: str,
) -> str:
    if build_path not in {"language_package_repo", "system_package_repo", "custom_package_repo"}:
        return ""
    return profile.asset.package_name or str(catalog_entry.get("db_type", "")) or profile.target.db_type


def _resolve_source_artifact(
    *,
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
    build_plan: BuildPlan,
) -> tuple[BuildPlan, list[ArtifactFact]]:
    facts: list[ArtifactFact] = []
    for version, url in _source_url_candidates(profile, catalog_entry):
        result = check_download_url(url)
        fact = ArtifactFact(
            fact_type="source_download_url",
            source="planner",
            identifier=profile.asset.component_name or profile.target.db_type,
            version=version,
            ref=url,
            available=bool(result.get("available")),
            notes=[
                *[str(item) for item in result.get("notes", [])],
                f"status_code={result.get('status_code', 0)}",
            ],
        )
        facts.append(fact)
        if fact.available:
            return (
                BuildPlan(
                    build_path=build_plan.build_path,
                    selected_version=version,
                    selected_image=build_plan.selected_image,
                    selected_download_url=url,
                    selected_package_repo=build_plan.selected_package_repo,
                    selected_package_name=build_plan.selected_package_name,
                    build_style=build_plan.build_style,
                ),
                facts,
            )
    if not facts:
        facts.append(
            ArtifactFact(
                fact_type="source_download_url",
                source="planner",
                identifier=profile.asset.component_name or profile.target.db_type,
                version=build_plan.selected_version,
                ref="",
                available=False,
                notes=["No source URL candidates were available to probe."],
            )
        )
    return (
        BuildPlan(
            build_path=build_plan.build_path,
            selected_version=build_plan.selected_version,
            selected_image=build_plan.selected_image,
            selected_download_url="",
            selected_package_repo=build_plan.selected_package_repo,
            selected_package_name=build_plan.selected_package_name,
            build_style=build_plan.build_style,
        ),
        facts,
    )


def _probe_required_affected_component_artifacts(
    profile: EnvironmentProfile,
) -> list[ArtifactFact]:
    facts: list[ArtifactFact] = []
    for artifact in profile.artifact_requirements:
        if artifact.purpose != "affected_component":
            continue
        if artifact.kind not in PROBEABLE_COMPONENT_ARTIFACT_KINDS:
            facts.append(
                ArtifactFact(
                    fact_type="affected_component_artifact",
                    source="planner",
                    identifier=artifact.identifier,
                    version=artifact.version_constraint,
                    ref="",
                    available=False,
                    notes=[
                        f"affected_component kind '{artifact.kind}' is not probeable by URL."
                    ],
                )
            )
            continue
        candidates = _artifact_probe_url_candidates(artifact)
        if not candidates:
            facts.append(
                ArtifactFact(
                    fact_type="affected_component_artifact",
                    source="planner",
                    identifier=artifact.identifier,
                    version=artifact.version_constraint,
                    ref="",
                    available=False,
                    notes=["No affected component URL candidates were available to probe."],
                )
            )
            continue
        for version, url in candidates[:MAX_PROBE_REQUESTS]:
            result = check_download_url(url)
            fact = ArtifactFact(
                fact_type=_affected_component_fact_type(artifact.kind),
                source="planner",
                identifier=artifact.identifier,
                version=version,
                ref=url,
                available=bool(result.get("available")),
                notes=[
                    "purpose=affected_component",
                    *[str(item) for item in result.get("notes", [])],
                    f"status_code={result.get('status_code', 0)}",
                ],
            )
            facts.append(fact)
            if fact.available:
                break
    return facts


def _artifact_probe_url_candidates(artifact) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    versions = _artifact_version_candidates(artifact)
    for template in _artifact_probe_url_templates(artifact, versions):
        if _source_url_has_version_placeholder(template):
            for version in versions:
                url = _render_source_url(template, version)
                if url:
                    candidates.append((version, url))
        else:
            candidates.append((_version_for_direct_source_url(template, versions), template))
    return list(dict.fromkeys(candidates))


def _artifact_probe_url_templates(artifact, versions: list[str]) -> list[str]:
    templates: list[str] = []
    identifier = artifact.identifier.strip()
    if artifact.kind == "git_repo":
        templates.extend(_github_archive_templates(identifier, versions))
    else:
        if _first_url([identifier]):
            templates.append(_first_url([identifier]))
    for note in artifact.notes:
        url = _first_url([note])
        if url:
            templates.append(url)
    return list(dict.fromkeys(templates))


def _affected_component_fact_type(kind: str) -> str:
    if kind == "binary_archive":
        return "affected_component_binary_url"
    if kind in SOURCE_ARTIFACT_KINDS:
        return "affected_component_source_url"
    return "affected_component_artifact"


def _source_url_candidates(
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    versions = _source_version_candidates(profile)
    for template in _source_url_templates(profile, catalog_entry):
        if _source_url_has_version_placeholder(template):
            for version in versions:
                url = _render_source_url(template, version)
                if url:
                    candidates.append((version, url))
        else:
            version = _version_for_direct_source_url(template, versions)
            candidates.append((version, template))
    return list(dict.fromkeys(candidates))


def _source_url_templates(
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
) -> list[str]:
    component_templates = _artifact_source_templates(
        profile,
        purpose="affected_component",
    )
    artifact_templates = _artifact_source_templates(profile)
    if _component_version_belongs_to_subartifact(profile):
        return list(dict.fromkeys([*component_templates, *artifact_templates]))

    templates = []
    catalog_url = str(catalog_entry.get("source_url", "") or "").strip()
    if catalog_url:
        templates.append(catalog_url)
    fallback_urls = catalog_entry.get("source_url_fallbacks")
    if isinstance(fallback_urls, list):
        templates.extend(
            str(item).strip()
            for item in fallback_urls
            if str(item).strip()
        )
    templates.extend(artifact_templates)
    return list(dict.fromkeys(templates))


def _artifact_source_templates(
    profile: EnvironmentProfile,
    purpose: str = "",
) -> list[str]:
    templates: list[str] = []
    for artifact in profile.artifact_requirements:
        if artifact.kind not in SOURCE_ARTIFACT_KINDS:
            continue
        if purpose and artifact.purpose != purpose:
            continue
        versions = _artifact_version_candidates(artifact)
        identifier = artifact.identifier.strip()
        if artifact.kind == "git_repo":
            templates.extend(_github_archive_templates(identifier, versions))
            continue
        for value in [identifier, *artifact.notes]:
            url = _first_url([value])
            if url:
                templates.append(url)
    return list(dict.fromkeys(templates))


def _artifact_version_candidates(artifact) -> list[str]:
    candidates: list[str] = []
    raw_versions = _version_tokens_from_constraint(artifact.version_constraint)
    if not raw_versions and artifact.version_constraint.strip():
        raw_versions = [artifact.version_constraint.strip()]
    for raw_version in raw_versions:
        for version in _version_spelling_variants(raw_version):
            candidates.extend(_version_tag_variants(version))
    return [item for item in dict.fromkeys(candidates) if item]


def _version_tokens_from_constraint(version_constraint: str) -> list[str]:
    return re.findall(
        r"\bv?\d+(?:\.\d+)+(?:[-._]?[A-Za-z]+[-._]?\d+)?\b",
        version_constraint.strip(),
    )


def _version_tag_variants(version: str) -> list[str]:
    normalized = version.strip()
    if not normalized:
        return []
    variants = [normalized]
    if normalized.startswith(("v", "V")) and len(normalized) > 1:
        variants.append(normalized[1:])
    else:
        variants.append(f"v{normalized}")
    return list(dict.fromkeys(variants))


def _github_archive_templates(repo_url: str, versions: list[str]) -> list[str]:
    match = re.match(
        r"https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
        repo_url.strip(),
        re.IGNORECASE,
    )
    if not match:
        return []
    owner, repo = match.groups()
    return [
        f"https://github.com/{owner}/{repo}/archive/refs/tags/{version}{suffix}"
        for version in versions
        for suffix in (".tar.gz", ".zip")
    ]


def _component_version_belongs_to_subartifact(profile: EnvironmentProfile) -> bool:
    relevance_type = profile.asset.relevance_type
    if relevance_type not in {"official_extension", "official_tool"}:
        return False
    component_name = _normalize_key(profile.asset.component_name)
    db_type = _normalize_key(profile.target.db_type)
    return bool(component_name and db_type and component_name != db_type)


def _source_version_candidates(profile: EnvironmentProfile) -> list[str]:
    versions = [
        profile.version.final_version or "",
        profile.version.requested_version or "",
        _selected_version(profile),
    ]
    for item in profile.version.candidate_versions:
        versions.extend(
            [
                item.version,
                item.upstream_version or "",
                item.package_version or "",
            ]
        )
    for artifact in profile.artifact_requirements:
        versions.append(artifact.version_constraint)
    candidates = []
    for version in versions:
        candidates.extend(_version_spelling_variants(version))
    return [item for item in dict.fromkeys(candidates) if item]


def _version_spelling_variants(version: str) -> list[str]:
    normalized = version.strip()
    if not normalized:
        return []
    variants = [normalized]
    match = re.fullmatch(r"(.+?)([-._]?)([A-Za-z]+)([-._]?)([0-9]+)", normalized)
    if match:
        base, _left_separator, marker, _right_separator, number = match.groups()
        for separator in ("", "-", ".", "_"):
            variants.append(f"{base}{separator}{marker}{number}")
    return list(dict.fromkeys(variants))


def _render_source_url(template: str, version: str) -> str:
    url = template.strip()
    if not url:
        return ""
    if "$VERSION" in url:
        return url.replace("$VERSION", version)
    if "{version}" in url:
        return url.replace("{version}", version)
    return url


def _source_url_has_version_placeholder(url: str) -> bool:
    return "$VERSION" in url or "{version}" in url


def _version_for_direct_source_url(url: str, versions: list[str]) -> str:
    lower_url = url.lower()
    for version in versions:
        if version.lower() in lower_url:
            return version
    return versions[0] if versions else ""


def _selected_download_url(
    *,
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
    build_path: str,
) -> str:
    if build_path == "prebuilt_binary":
        return _catalog_or_profile_url(profile, catalog_entry, "binary_url")
    if build_path == "source_compile":
        return _catalog_or_profile_url(profile, catalog_entry, "source_url")
    return ""


def _catalog_or_profile_url(
    profile: EnvironmentProfile,
    catalog_entry: dict[str, Any],
    catalog_key: str,
) -> str:
    catalog_url = str(catalog_entry.get(catalog_key, "") or "").strip()
    if catalog_url:
        return catalog_url
    for artifact in profile.artifact_requirements:
        url = _first_url([artifact.identifier, *artifact.notes])
        if url:
            return url
    return ""


def _first_url(values: list[str]) -> str:
    for value in values:
        match = re.search(r"https?://[^\s)>\]]+", value)
        if match:
            return match.group(0).rstrip(".,")
    return ""


def _artifact_identifier(profile: EnvironmentProfile, kind: str) -> str:
    for artifact in profile.artifact_requirements:
        if artifact.kind == kind:
            return artifact.identifier
    return profile.target.db_type


def _build_style(catalog_entry: dict[str, Any]) -> str:
    build_style = str(catalog_entry.get("build_style", "") or "").strip()
    if build_style in {"multi_stage_server", "single_stage_embedded"}:
        return build_style
    return ""


def _catalog_entry(template_recommendation: dict[str, Any]) -> dict[str, Any]:
    entry = template_recommendation.get("entry")
    return entry if isinstance(entry, dict) else {}


def _catalog_path(template_recommendation: dict[str, Any]) -> str:
    return str(_catalog_entry(template_recommendation).get("recommended_path", "")).strip()


def _verified_artifacts(facts: list[ArtifactFact]) -> list[ArtifactFact]:
    return [fact for fact in facts if fact.available]


def _generation_requirements(
    *,
    profile: EnvironmentProfile,
    build_plan: BuildPlan,
    template_recommendation: dict[str, Any],
    artifact_facts: list[ArtifactFact] | None = None,
) -> dict[str, Any]:
    """Condense the profiler profile into generation requirements directly executable by the generator."""
    catalog_entry = _catalog_entry(template_recommendation)
    template_requirements = {
        key: catalog_entry.get(key)
        for key in [
            "source_url",
            "binary_url",
            "custom_repo",
            "build_style",
            "notes",
        ]
        if catalog_entry.get(key)
    }

    manual_notes = [
        *profile.notes,
        *profile.warnings,
    ]
    unresolved_artifacts = _unresolved_affected_component_artifacts(
        profile=profile,
        build_plan=build_plan,
        artifact_facts=artifact_facts or [],
    )
    for artifact in unresolved_artifacts:
        manual_notes.append(
            "Required affected component artifact is not verified: "
            f"{artifact['identifier']} ({artifact['version_constraint']})."
        )
    if build_plan.build_path == "source_compile" and not build_plan.selected_download_url:
        manual_notes.append(
            "No reachable source archive URL was found. Provide SOURCE_URL before building."
        )
    return {
        "project_name": profile.target.project_name,
        "cve_id": profile.target.cve_id,
        "db_type": profile.target.db_type,
        "component": {
            "relevance_type": profile.asset.relevance_type,
            "name": profile.asset.component_name,
            "type": profile.asset.component_type,
            "package_ecosystem": profile.asset.package_ecosystem,
            "package_name": profile.asset.package_name or "",
        },
        "runtime": profile.runtime.to_dict(),
        "artifact_requirements": [
            _artifact_requirement_without_kind(artifact)
            for artifact in profile.artifact_requirements
        ],
        "vulnerability_conditions": [
            condition.to_dict() for condition in profile.vulnerability_conditions
        ],
        "construction_constraints": profile.construction_constraints.to_dict(),
        "template_requirements": template_requirements,
        "artifact_probe_results": [
            fact.to_dict() for fact in (artifact_facts or [])
        ],
        "unresolved_required_artifacts": unresolved_artifacts,
        "manual_notes": manual_notes,
    }


def _artifact_requirement_without_kind(artifact) -> dict[str, Any]:
    return {
        "identifier": artifact.identifier,
        "version_constraint": artifact.version_constraint,
        "purpose": artifact.purpose,
        "notes": list(artifact.notes),
    }


def _unresolved_affected_component_artifacts(
    *,
    profile: EnvironmentProfile,
    build_plan: BuildPlan,
    artifact_facts: list[ArtifactFact],
) -> list[dict[str, str]]:
    unresolved: list[dict[str, str]] = []
    for artifact in profile.artifact_requirements:
        if artifact.purpose != "affected_component":
            continue
        if _artifact_requirement_is_verified(
            artifact=artifact,
            build_plan=build_plan,
            artifact_facts=artifact_facts,
        ):
            continue
        unresolved.append(
            {
                "identifier": artifact.identifier,
                "version_constraint": artifact.version_constraint,
                "purpose": artifact.purpose,
            }
        )
    return unresolved


def _artifact_requirement_is_verified(
    *,
    artifact,
    build_plan: BuildPlan,
    artifact_facts: list[ArtifactFact],
) -> bool:
    if artifact.kind == "other":
        return False
    if artifact.kind in PROBEABLE_COMPONENT_ARTIFACT_KINDS:
        if build_plan.selected_download_url:
            return any(
                url == build_plan.selected_download_url
                for _version, url in _artifact_probe_url_candidates(artifact)
            )
        return any(
            fact.available
            and fact.identifier == artifact.identifier
            and fact.fact_type
            in {
                "affected_component_source_url",
                "affected_component_binary_url",
                "source_download_url",
            }
            for fact in artifact_facts
        )
    if artifact.kind == "container_image":
        return any(
            fact.available
            and fact.fact_type == "dockerhub_tag"
            and (
                fact.ref == _artifact_image_ref(
                    artifact.identifier,
                    artifact.version_constraint,
                )
                or fact.identifier == artifact.identifier
            )
            for fact in artifact_facts
        )
    return False


def _upsert_fact(facts: list[ArtifactFact], fact: ArtifactFact) -> None:
    """Deduplicate by fact type, identifier, and version."""
    for index, item in enumerate(facts):
        if (
            item.fact_type == fact.fact_type
            and item.identifier == fact.identifier
            and item.version == fact.version
        ):
            facts[index] = fact
            return
    facts.append(fact)


def _read_json_catalog_objects(catalog_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a catalog in JSONL, JSON array, or consecutive JSON object format."""
    text = catalog_path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    entries: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            item, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            parse_errors.append(f"offset {exc.pos}: {exc.msg}")
            break
        if isinstance(item, dict):
            entries.append(item)
        elif isinstance(item, list):
            entries.extend(entry for entry in item if isinstance(entry, dict))
    return entries, parse_errors


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
