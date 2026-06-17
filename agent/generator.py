"""LLM-driven Docker project generator.

The generator creates complete project files and calls file tools inside the agent to write them to disk.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from agent.llm import JsonChatClient
from agent.models import EnvironmentPlan, ProjectArtifacts
from agent.prompt_loader import load_prompt
from tools.project_tools import create_run_directory, write_project
from tools.package_tools import check_package_dependencies, check_package_version
from tools.registry_tools import check_image_ref
from tools.url_probe_tools import check_download_url


DIRECT_GENERATION_BUILD_PATHS = {"official_image_direct"}
MAX_BASE_IMAGE_TOOL_CALLS = 10
GENERATOR_TEMPERATURE = 0.1
StatusCallback = Callable[[str], None]


def _update_status(status_callback: StatusCallback | None, operation: str) -> None:
    """Publish one generator operation when terminal progress is enabled."""
    if status_callback is not None:
        status_callback(operation)


def _project_name_with_identifiers(
    *,
    base_name: str,
    db_type: str,
    cve_id: str,
    version: str,
) -> str:
    """Rebuild the project name into a stable subject-version_cve shape."""
    subject = _clean_project_subject(
        base_name=base_name,
        db_type=db_type,
        cve_id=cve_id,
        version=version,
    )
    normalized_version = version.strip()
    normalized_cve_id = cve_id.strip().upper()
    name = f"{subject}-{normalized_version}" if normalized_version else subject
    if normalized_cve_id:
        name = f"{name}_{normalized_cve_id}"
    return name


def _clean_project_subject(
    *,
    base_name: str,
    db_type: str,
    cve_id: str,
    version: str,
) -> str:
    """Remove previously appended CVE/version fragments from a base project name."""
    subject = base_name.strip() or db_type.strip() or "db-env-project"
    for token in _project_name_tokens_to_remove(cve_id=cve_id, version=version):
        subject = subject.replace(token, "")
        subject = subject.replace(token.lower(), "")
        subject = subject.replace(token.upper(), "")
    subject = subject.strip("-_ .")
    return subject or db_type.strip() or "db-env-project"


def _project_name_tokens_to_remove(*, cve_id: str, version: str) -> list[str]:
    tokens: list[str] = []
    normalized_cve_id = cve_id.strip()
    normalized_version = version.strip()
    if normalized_cve_id:
        tokens.extend(
            [
                normalized_cve_id,
                normalized_cve_id.replace("-", "_"),
            ]
        )
    if normalized_version:
        tokens.extend(
            [
                normalized_version,
                normalized_version.replace(".", "-"),
                normalized_version.replace(".", "_"),
            ]
        )
    return [token for token in tokens if token]


def generate_project(
    blueprint: EnvironmentPlan,
    output_directory: Path,
    client: JsonChatClient,
    status_callback: StatusCallback | None = None,
) -> tuple[ProjectArtifacts, Path, list[str]]:
    """Generate complete project files and write them into the current run directory."""
    _update_status(status_callback, "Preparing EnvironmentPlan prompt")
    uses_react = _needs_react_tools(blueprint)
    system_prompt = _generator_system_prompt(
        include_react=uses_react,
    )
    request_instruction = (
        "Choose exactly one next ReAct action from the EnvironmentPlan and observations. "
        "Return only one JSON object matching a schema defined in react.md."
        if uses_react
        else "Generate the final ProjectArtifacts JSON from the EnvironmentPlan."
    )
    user_prompt = (
        f"{request_instruction}\n\n"
        "Build blueprint:\n"
        f"{json.dumps(blueprint.to_dict(), ensure_ascii=False, indent=2)}"
    )
    response = (
        _generate_project_with_react_tools(
            blueprint=blueprint,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            client=client,
            status_callback=status_callback,
        )
        if uses_react
        else _generate_project_directly(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            client=client,
            status_callback=status_callback,
        )
    )
    _update_status(status_callback, "Parsing ProjectArtifacts output")
    artifacts = ProjectArtifacts.from_dict(response)
    project_name = str(
        blueprint.generation_requirements.get("project_name") or artifacts.project_name
    ).strip()
    cve_id = str(blueprint.generation_requirements.get("cve_id") or artifacts.cve_id).strip()
    db_type = str(blueprint.generation_requirements.get("db_type") or "").strip()
    version_requirement = blueprint.generation_requirements.get("version")
    if isinstance(version_requirement, dict):
        fallback_version = (
            version_requirement.get("final")
            or version_requirement.get("requested")
            or ""
        )
    else:
        fallback_version = version_requirement or ""
    version = str(blueprint.build_plan.selected_version or fallback_version).strip()
    artifacts.project_name = _project_name_with_identifiers(
        base_name=project_name,
        db_type=db_type,
        cve_id=cve_id,
        version=version,
    )
    if cve_id:
        artifacts.cve_id = cve_id
    _update_status(status_callback, "Creating timestamped project directory")
    run_dir = create_run_directory(output_directory, artifacts.project_name)
    _update_status(status_callback, "Writing Docker project artifacts")
    written_files = write_project(run_dir, artifacts.files)
    _update_status(status_callback, "Finalizing Generator Module output")
    return artifacts, run_dir, written_files


def _needs_react_tools(blueprint: EnvironmentPlan) -> bool:
    return blueprint.build_plan.build_path not in DIRECT_GENERATION_BUILD_PATHS


def _generate_project_directly(
    *,
    system_prompt: str,
    user_prompt: str,
    client: JsonChatClient,
    status_callback: StatusCallback | None,
) -> dict:
    """Generate an official-image project in one model call."""
    _update_status(status_callback, "Generating direct official-image project")
    return client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=GENERATOR_TEMPERATURE,
        model=client.settings.generator_model,
        timeout_seconds=300,
    )


def _generate_project_with_react_tools(
    *,
    blueprint: EnvironmentPlan,
    system_prompt: str,
    user_prompt: str,
    client: JsonChatClient,
    status_callback: StatusCallback | None,
) -> dict:
    tool_history: list[dict] = []
    last_project: dict | None = None
    last_validation: dict | None = None
    for round_index in range(1, MAX_BASE_IMAGE_TOOL_CALLS + 1):
        _update_status(
            status_callback,
            f"ReAct round {round_index}/{MAX_BASE_IMAGE_TOOL_CALLS}: requesting next action",
        )
        response = client.chat_json(
            system_prompt=system_prompt,
            user_prompt=_react_user_prompt(
                user_prompt,
                tool_history,
                blueprint,
                round_index=round_index,
            ),
            temperature=GENERATOR_TEMPERATURE,
            model=client.settings.generator_model,
            timeout_seconds=300,
        )
        action_fingerprint = _action_fingerprint(response)
        if _has_failed_action_fingerprint(tool_history, action_fingerprint):
            tool_history.append(
                _tool_observation(
                    tool="runtime_feedback",
                    request={"action": response.get("action", "")},
                    result={
                        "available": False,
                        "error": "duplicate_failed_action",
                        "duplicate_action_fingerprint": action_fingerprint,
                    },
                )
            )
            continue
        if response.get("action") == "check_image_ref":
            image_ref = str(response.get("image_ref", "")).strip()
            _update_status(status_callback, f"Verifying Docker image: {image_ref}")
            tool_history.append(
                _tool_observation(
                    tool="check_image_ref",
                    request={"image_ref": image_ref},
                    result=check_image_ref(image_ref),
                    action_fingerprint=action_fingerprint,
                )
            )
            continue
        if response.get("action") == "check_package_version":
            image_ref = str(response.get("image_ref", "")).strip()
            package_name = str(response.get("package_name", "")).strip()
            version = str(response.get("version", "")).strip()
            _update_status(
                status_callback,
                f"Verifying package version: {package_name} {version}".strip(),
            )
            tool_history.append(
                _tool_observation(
                    tool="check_package_version",
                    request={
                        "image_ref": image_ref,
                        "package_name": package_name,
                        "version": version,
                    },
                    result=check_package_version(
                        image_ref=image_ref,
                        package_name=package_name,
                        version=version,
                    ),
                    action_fingerprint=action_fingerprint,
                )
            )
            continue
        if response.get("action") == "check_package_dependencies":
            image_ref = str(response.get("image_ref", "")).strip()
            dependencies = response.get("dependencies")
            if not isinstance(dependencies, list):
                dependencies = []
            _update_status(
                status_callback,
                f"Loading repository indexes and matching {len(dependencies)} dependencies",
            )
            tool_history.append(
                _tool_observation(
                    tool="check_package_dependencies",
                    request={
                        "image_ref": image_ref,
                        "dependencies": dependencies,
                    },
                    result=check_package_dependencies(
                        image_ref=image_ref,
                        dependencies=dependencies,
                    ),
                    action_fingerprint=action_fingerprint,
                )
            )
            continue
        if response.get("action") == "check_download_url":
            url = str(response.get("url", "")).strip()
            _update_status(status_callback, "Verifying remote build artifact URL")
            tool_history.append(
                _tool_observation(
                    tool="check_download_url",
                    request={"url": url},
                    result=check_download_url(url),
                    action_fingerprint=action_fingerprint,
                )
            )
            continue
        if response.get("action") == "final" and isinstance(response.get("project"), dict):
            _update_status(status_callback, "Validating Dockerfile images and build URLs")
            project = response["project"]
            last_project = project
            validation = _validate_final_project(
                project=project,
                tool_history=tool_history,
                blueprint=blueprint,
            )
            if validation["available"]:
                return project
            last_validation = validation
            tool_history.append(
                _tool_observation(
                    tool="final_validation",
                    request={
                        "from_images": validation.get("from_images", []),
                        "build_urls": validation.get("build_urls", []),
                    },
                    result=validation,
                    action_fingerprint=action_fingerprint,
                )
            )
            continue
        tool_history.append(
            _tool_observation(
                tool="runtime_feedback",
                request={"action": response.get("action", "")},
                result={
                    "available": False,
                    "error": "invalid_action_response",
                },
                action_fingerprint=action_fingerprint,
            )
        )
    _update_status(status_callback, "Generating marked incomplete fallback project")
    return _generate_incomplete_project(
        blueprint=blueprint,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        client=client,
        tool_history=tool_history,
        last_project=last_project,
        last_validation=last_validation,
    )


def _generate_incomplete_project(
    *,
    blueprint: EnvironmentPlan,
    system_prompt: str,
    user_prompt: str,
    client: JsonChatClient,
    tool_history: list[dict],
    last_project: dict | None,
    last_validation: dict | None,
) -> dict:
    """Generate an incomplete best-effort project when ReAct cannot finish."""
    fallback_prompt = _incomplete_project_prompt(
        user_prompt=user_prompt,
        tool_history=tool_history,
        last_project=last_project,
        last_validation=last_validation,
    )
    try:
        response = client.chat_json(
            system_prompt=system_prompt,
            user_prompt=fallback_prompt,
            temperature=GENERATOR_TEMPERATURE,
            model=client.settings.generator_model,
            timeout_seconds=300,
        )
        project = response.get("project") if response.get("action") == "final" else response
        if not _is_project_dict(project):
            project = _deterministic_incomplete_project(blueprint)
    except Exception:
        project = _deterministic_incomplete_project(blueprint)
    return _attach_generation_status_file(
        project=project,
        blueprint=blueprint,
        tool_history=tool_history,
        last_validation=last_validation,
    )


def _incomplete_project_prompt(
    *,
    user_prompt: str,
    tool_history: list[dict],
    last_project: dict | None,
    last_validation: dict | None,
) -> str:
    return (
        f"{user_prompt}\n\n"
        "ReAct tool mode reached its maximum number of calls before producing a fully validated final project.\n"
        "Return a JSON project for an INCOMPLETE best-effort Docker environment.\n"
        "Rules:\n"
        "- Keep only verified or blueprint-authorized parts as active Dockerfile steps.\n"
        "- Remove, comment out, or replace unavailable/unverified remote build artifacts with clear placeholders.\n"
        "- Do not keep a known unavailable or unverified build-time URL as an active download command.\n"
        "- Do not claim the environment is complete, fully reproducible, verified, or ready when validation issues remain.\n"
        "- README must contain an 'Incomplete Generation' section listing unresolved images, URLs, packages, and conditions.\n"
        "- Include normal project files where possible plus a GENERATION_STATUS.md file is allowed, but the runtime will also append one.\n"
        "- Output JSON only in the same ProjectArtifacts shape.\n\n"
        "Last attempted project:\n"
        f"{json.dumps(last_project or {}, ensure_ascii=False, indent=2)}\n\n"
        "Last validation:\n"
        f"{json.dumps(last_validation or {}, ensure_ascii=False, indent=2)}\n\n"
        "Tool history summary:\n"
        f"{json.dumps(_compact_tool_history(tool_history), ensure_ascii=False, indent=2)}"
    )


def _is_project_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    files = value.get("files")
    return isinstance(files, list) and isinstance(value.get("project_name"), str)


def _deterministic_incomplete_project(blueprint: EnvironmentPlan) -> dict:
    project_name = str(
        blueprint.generation_requirements.get("project_name")
        or blueprint.generation_requirements.get("db_type")
        or "db-env-project"
    ).strip()
    cve_id = str(blueprint.generation_requirements.get("cve_id") or "").strip()
    selected_version = str(blueprint.build_plan.selected_version or "").strip()
    subject = _project_name_with_identifiers(
        base_name=project_name,
        db_type=str(blueprint.generation_requirements.get("db_type") or "").strip(),
        cve_id=cve_id,
        version=selected_version,
    )
    readme = (
        f"# {subject}\n\n"
        "## Incomplete Generation\n"
        "The generator reached its ReAct tool-call limit before producing a fully validated Docker environment.\n"
        "This directory is a best-effort scaffold for manual completion, not a verified runnable reproduction.\n\n"
        "## Selected Plan\n"
        f"- Build path: `{blueprint.build_plan.build_path}`\n"
        f"- Selected version: `{selected_version or 'unknown'}`\n"
        f"- Selected image: `{blueprint.build_plan.selected_image or 'not selected'}`\n"
        f"- Selected download URL: `{blueprint.build_plan.selected_download_url or 'not selected'}`\n\n"
        "Review `GENERATION_STATUS.md` for the failed tool checks and unresolved validation issues.\n"
    )
    return {
        "project_name": subject,
        "cve_id": cve_id,
        "files": [
            {
                "path": "README.md",
                "purpose": "incomplete generation documentation",
                "content": readme,
            },
            {
                "path": "shared/.gitkeep",
                "purpose": "placeholder for shared volume",
                "content": "",
            },
        ],
        "run_instructions": [],
        "summary": "Incomplete best-effort project generated after ReAct tool-call limit.",
    }


def _attach_generation_status_file(
    *,
    project: dict,
    blueprint: EnvironmentPlan,
    tool_history: list[dict],
    last_validation: dict | None,
) -> dict:
    files = project.get("files")
    if not isinstance(files, list):
        files = []
        project["files"] = files
    files = _sanitize_generated_files(files)
    files.append(
        {
            "path": "GENERATION_STATUS.md",
            "purpose": "incomplete generation diagnostics",
            "content": _generation_status_content(
                blueprint=blueprint,
                tool_history=tool_history,
                last_validation=last_validation,
            ),
        }
    )
    project["files"] = files
    project["summary"] = _incomplete_summary(project.get("summary"))
    if not isinstance(project.get("run_instructions"), list):
        project["run_instructions"] = []
    project["run_instructions"] = [str(item) for item in project["run_instructions"]]
    project["cve_id"] = str(
        project.get("cve_id") or blueprint.generation_requirements.get("cve_id") or ""
    )
    project["project_name"] = str(
        project.get("project_name")
        or blueprint.generation_requirements.get("project_name")
        or "db-env-project"
    )
    return project


def _sanitize_generated_files(files: list) -> list[dict]:
    sanitized: list[dict] = []
    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path == "GENERATION_STATUS.md":
            continue
        sanitized.append(
            {
                "path": path,
                "purpose": str(item.get("purpose") or f"incomplete generated file {index}"),
                "content": str(item.get("content") or ""),
            }
        )
    return sanitized


def _incomplete_summary(summary: object) -> str:
    text = str(summary or "").strip()
    prefix = "INCOMPLETE best-effort project: "
    if text.startswith(prefix):
        return text
    return f"{prefix}{text or 'ReAct tool-call limit reached before full validation.'}"


def _generation_status_content(
    *,
    blueprint: EnvironmentPlan,
    tool_history: list[dict],
    last_validation: dict | None,
) -> str:
    diagnostics = {
        "status": "incomplete",
        "reason": "generator_react_tool_call_limit_reached",
        "max_tool_calls": MAX_BASE_IMAGE_TOOL_CALLS,
        "build_plan": blueprint.build_plan.to_dict(),
        "last_validation": last_validation or {},
        "tool_history_summary": _compact_tool_history(tool_history),
    }
    return (
        "# Generation Status\n\n"
        "Status: INCOMPLETE\n\n"
        "The generator reached the ReAct tool-call limit before producing a fully validated final project. "
        "Generated files are a best-effort scaffold and may require manual completion.\n\n"
        "Do not treat this output as a verified runnable reproduction until the unresolved validation issues below are fixed.\n\n"
        "```json\n"
        f"{json.dumps(diagnostics, ensure_ascii=False, indent=2)}\n"
        "```\n"
    )


def _compact_tool_history(tool_history: list[dict]) -> list[dict]:
    """Keep observations concise enough to reuse in each ReAct round."""
    compact: list[dict] = []
    for round_number, item in enumerate(tool_history, start=1):
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        summary = {
            "round": round_number,
            "tool": item.get("tool"),
            "request": _compact_tool_request(item.get("tool"), request),
        }
        if result:
            result_summary = {
                key: result.get(key)
                for key in [
                    "available",
                    "availability",
                    "image_ref",
                    "distribution",
                    "release",
                    "normalized_release",
                    "package_name",
                    "version",
                    "source_status",
                    "package_version_verified",
                    "requires_snapshot_source",
                    "install_package_name",
                    "install_version",
                    "snapshot_source_list",
                    "replacement_source_list",
                    "apt_update_options",
                    "replacement_source_hint",
                    "missing_required_packages",
                    "unchecked_required_packages",
                    "dependency_check_skipped",
                    "verification_skipped",
                    "url",
                    "status_code",
                    "build_urls",
                    "authorized_build_urls",
                    "verified_build_urls",
                    "tool_authorized_build_urls",
                    "unverified_build_urls",
                    "from_images",
                    "verified_images",
                    "unverified_from_images",
                    "error",
                    "violations",
                ]
                if key in result
            }
            notes = result.get("notes")
            if isinstance(notes, list):
                result_summary["notes"] = [str(note)[:240] for note in notes[:3]]
            summary["result"] = result_summary
        compact.append(summary)
    return compact


def _compact_tool_request(tool: object, request: dict) -> dict:
    """Retain decision-relevant request facts without repeating large payloads."""
    if tool == "check_package_dependencies":
        dependencies = request.get("dependencies")
        package_names = []
        if isinstance(dependencies, list):
            package_names = [
                str(item.get("package_name", "")).strip()
                for item in dependencies
                if isinstance(item, dict) and str(item.get("package_name", "")).strip()
            ]
        return {
            "image_ref": str(request.get("image_ref", "")).strip(),
            "package_names": package_names,
        }
    return request


def _tool_observation(
    *,
    tool: str,
    request: dict,
    result: dict,
    action_fingerprint: str = "",
) -> dict:
    observation = {
        "tool": tool,
        "request": request,
        "result": result,
    }
    if action_fingerprint:
        observation["action_fingerprint"] = action_fingerprint
    return observation


def _action_fingerprint(response: dict) -> str:
    """Create a stable identity for an action while ignoring explanatory prose."""
    normalized = {
        key: value
        for key, value in response.items()
        if key != "reason"
    }
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _has_failed_action_fingerprint(
    tool_history: list[dict],
    action_fingerprint: str,
) -> bool:
    if not action_fingerprint:
        return False
    for item in reversed(tool_history):
        result = item.get("result")
        if (
            item.get("tool") == "runtime_feedback"
            and isinstance(result, dict)
            and result.get("error") == "duplicate_failed_action"
        ):
            continue
        return bool(
            item.get("action_fingerprint") == action_fingerprint
            and isinstance(result, dict)
            and result.get("available") is False
        )
    return False


def _validate_final_project(
    *,
    project: dict,
    tool_history: list[dict],
    blueprint: EnvironmentPlan,
) -> dict:
    """Reject final projects with unverified FROM images or generator-added URLs."""
    image_validation = _validate_final_from_images(project, tool_history)
    url_validation = _validate_final_build_urls(
        project=project,
        tool_history=tool_history,
        blueprint=blueprint,
    )
    return {
        **image_validation,
        **url_validation,
        "available": image_validation["available"] and url_validation["available"],
        "violations": [
            *image_validation["violations"],
            *url_validation["violations"],
        ],
        "notes": [
            *image_validation["notes"],
            *url_validation["notes"],
        ],
    }


def _validate_final_from_images(project: dict, tool_history: list[dict]) -> dict:
    """Reject final projects whose Dockerfile FROM images were not tool-verified."""
    from_images = _dockerfile_from_images(project)
    verified_images = _verified_image_refs(tool_history)
    unverified = [
        image
        for image in from_images
        if image != "scratch" and not _image_ref_verified(image, verified_images)
    ]
    return {
        "available": not unverified,
        "from_images": from_images,
        "verified_images": sorted(verified_images),
        "unverified_from_images": unverified,
        "violations": [
            {"type": "unverified_from_image", "value": image}
            for image in unverified
        ],
        "notes": (
            ["All Dockerfile FROM images were verified by check_image_ref."]
            if not unverified
            else [
                "At least one Dockerfile FROM image was not present in successful image-check observations.",
            ]
        ),
    }


def _validate_final_build_urls(
    *,
    project: dict,
    tool_history: list[dict],
    blueprint: EnvironmentPlan,
) -> dict:
    """Reject generator-introduced build-time URLs that were not probed."""
    build_urls = _dockerfile_build_urls(project)
    authorized_urls = _authorized_build_urls(blueprint)
    checked_urls = _verified_download_urls(tool_history)
    tool_authorized_urls = _tool_authorized_urls(tool_history)
    unverified = [
        url
        for url in build_urls
        if not _url_ref_verified(url, authorized_urls | checked_urls | tool_authorized_urls)
    ]
    notes = (
        ["All generator-introduced build-time URLs were authorized or verified."]
        if not unverified
        else [
            "At least one Dockerfile build-time URL was absent from blueprint-authorized or successful URL observations.",
        ]
    )
    return {
        "available": not unverified,
        "build_urls": build_urls,
        "authorized_build_urls": sorted(authorized_urls),
        "verified_build_urls": sorted(checked_urls),
        "tool_authorized_build_urls": sorted(tool_authorized_urls),
        "unverified_build_urls": unverified,
        "violations": [
            {"type": "unverified_build_url", "value": url}
            for url in unverified
        ],
        "notes": notes,
    }


def _dockerfile_from_images(project: dict) -> list[str]:
    """Extract all FROM image references from generated Dockerfile contents."""
    files = project.get("files")
    if not isinstance(files, list):
        return []
    images: list[str] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        path = str(file.get("path", "")).strip()
        if not _is_dockerfile_path(path):
            continue
        content = str(file.get("content", ""))
        images.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"(?im)^\s*FROM\s+(?:--platform=\S+\s+)?([^\s]+)",
                content,
            )
        )
    return list(dict.fromkeys(images))


def _dockerfile_build_urls(project: dict) -> list[str]:
    """Extract URLs only from Dockerfile instructions that affect the build."""
    files = project.get("files")
    if not isinstance(files, list):
        return []
    urls: list[str] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        path = str(file.get("path", "")).strip()
        if not _is_dockerfile_path(path):
            continue
        content = str(file.get("content", ""))
        for instruction in _dockerfile_build_instructions(content):
            urls.extend(_explicit_urls(instruction))
    return list(dict.fromkeys(urls))


def _dockerfile_build_instructions(content: str) -> list[str]:
    """Return logical RUN/ADD instructions while ignoring comments and metadata."""
    instructions: list[str] = []
    current = ""
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        current = f"{current}\n{raw_line}" if current else raw_line
        if _dockerfile_line_continues(raw_line):
            continue
        if re.match(r"(?is)^\s*(?:RUN|ADD)\s+", current):
            instructions.append(current)
        current = ""
    if current and re.match(r"(?is)^\s*(?:RUN|ADD)\s+", current):
        instructions.append(current)
    return instructions


def _dockerfile_line_continues(line: str) -> bool:
    """Detect a Dockerfile line continuation after trimming trailing whitespace."""
    return line.rstrip().endswith("\\")


def _explicit_urls(content: str) -> list[str]:
    return [
        match.group(0).rstrip(".,;)'\"\\")
        for match in re.finditer(r"https?://[^\s<>'\"]+", content)
    ]


def _authorized_build_urls(blueprint: EnvironmentPlan) -> set[str]:
    refs: set[str] = set()
    refs.update(_url_ref_keys(blueprint.build_plan.selected_download_url))
    refs.update(
        _url_ref_keys(
            _repository_url(blueprint.build_plan.selected_package_repo)
        )
    )
    for artifact in blueprint.verified_artifacts:
        refs.update(_url_ref_keys(artifact.ref))
    return refs


def _repository_url(source_line: str) -> str:
    """Extract the repository URL from a package-manager source line."""
    match = re.search(r"https?://[^\s]+", source_line.strip())
    return match.group(0).rstrip(".,;)'\"\\") if match else ""


def _verified_download_urls(tool_history: list[dict]) -> set[str]:
    refs: set[str] = set()
    for item in tool_history:
        if item.get("tool") != "check_download_url":
            continue
        result = item.get("result")
        if not isinstance(result, dict) or not result.get("available"):
            continue
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        refs.update(_url_ref_keys(str(request.get("url", "")).strip()))
        refs.update(_url_ref_keys(str(result.get("url", "")).strip()))
    return refs


def _tool_authorized_urls(tool_history: list[dict]) -> set[str]:
    refs: set[str] = set()
    for item in tool_history:
        if item.get("tool") not in {"check_package_version", "check_package_dependencies"}:
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("available"):
            refs.update(_urls_from_object(result))
            continue
        for key in ("replacement_source_list", "snapshot_source_list"):
            refs.update(_urls_from_object(result.get(key)))
    return refs


def _urls_from_object(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        for url in _explicit_urls(value):
            refs.update(_url_ref_keys(url))
    elif isinstance(value, dict):
        for item in value.values():
            refs.update(_urls_from_object(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_urls_from_object(item))
    return refs


def _url_ref_verified(url: str, verified_urls: set[str]) -> bool:
    return bool(_url_ref_keys(url) & verified_urls)


def _url_ref_keys(url: str) -> set[str]:
    normalized = _normalize_url_ref(url)
    return {normalized} if normalized else set()


def _normalize_url_ref(url: str) -> str:
    normalized = url.strip().rstrip(".,;)'\"\\/")
    if not normalized:
        return ""
    normalized = re.sub(r"\$\{?VERSION\}?", "$VERSION", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\{version\}", "$VERSION", normalized, flags=re.IGNORECASE)
    return normalized


def _is_dockerfile_path(path: str) -> bool:
    filename = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return filename == "dockerfile" or filename.startswith("dockerfile.")


def _verified_image_refs(tool_history: list[dict]) -> set[str]:
    refs: set[str] = set()
    for item in tool_history:
        if item.get("tool") != "check_image_ref":
            continue
        result = item.get("result")
        if not isinstance(result, dict) or not result.get("available"):
            continue
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        for image_ref in [
            str(request.get("image_ref", "")).strip(),
            str(result.get("image_ref", "")).strip(),
        ]:
            refs.update(_image_ref_keys(image_ref))
    return refs


def _image_ref_verified(image_ref: str, verified_images: set[str]) -> bool:
    return bool(_image_ref_keys(image_ref) & verified_images)


def _image_ref_keys(image_ref: str) -> set[str]:
    raw = image_ref.strip().split("@", 1)[0]
    if not raw:
        return set()
    refs = {raw}
    if ":" not in raw.rsplit("/", 1)[-1]:
        refs.add(f"{raw}:latest")
    keys: set[str] = set()
    for ref in refs:
        normalized = ref
        if normalized.startswith("docker.io/library/"):
            normalized = normalized.removeprefix("docker.io/library/")
        elif normalized.startswith("docker.io/"):
            normalized = normalized.removeprefix("docker.io/")
        keys.add(normalized)
        if normalized.startswith("library/"):
            keys.add(normalized.removeprefix("library/"))
    return keys


def _react_user_prompt(
    user_prompt: str,
    tool_history: list[dict],
    blueprint: EnvironmentPlan,
    *,
    round_index: int,
) -> str:
    return (
        f"{user_prompt}\n\n"
        "Observation history summary:\n"
        f"{json.dumps(_compact_tool_history(tool_history), ensure_ascii=False, indent=2)}\n\n"
        "Current generator facts:\n"
        f"{json.dumps(_generator_state_summary(blueprint, tool_history, round_index=round_index), ensure_ascii=False, indent=2)}"
    )


def _generator_system_prompt(
    *,
    include_react: bool,
) -> str:
    """Compose the shared generator rules and build-path policy."""
    sections = [load_prompt("generator/core.md")]
    if include_react:
        sections.append(load_prompt("generator/react.md"))
    else:
        sections.append(load_prompt("generator/direct.md"))
    sections.append(load_prompt("generator/build_paths.md"))
    return "\n\n---\n\n".join(section.strip() for section in sections if section.strip())


def _generator_state_summary(
    blueprint: EnvironmentPlan,
    tool_history: list[dict],
    *,
    round_index: int,
) -> dict:
    """Expose only established facts, without selecting the model's next action."""
    compact_history = _compact_tool_history(tool_history)
    return {
        "build_path": blueprint.build_plan.build_path,
        "selected_image": _latest_successful_request_value(
            tool_history,
            tool="check_image_ref",
            key="image_ref",
        ),
        "selected_package_name": blueprint.build_plan.selected_package_name,
        "selected_version": blueprint.build_plan.selected_version,
        "selected_package_repo": blueprint.build_plan.selected_package_repo,
        "selected_download_url": blueprint.build_plan.selected_download_url,
        "verified_images": sorted(_verified_image_refs(tool_history)),
        "completed_tool_calls": [
            str(item.get("tool", ""))
            for item in tool_history
            if str(item.get("tool", "")).strip()
        ],
        "failed_observations": [
            item
            for item in compact_history
            if isinstance(item.get("result"), dict)
            and item["result"].get("available") is False
        ],
        "remaining_rounds": max(0, MAX_BASE_IMAGE_TOOL_CALLS - round_index + 1),
    }


def _latest_successful_request_value(
    tool_history: list[dict],
    *,
    tool: str,
    key: str,
) -> str:
    for item in reversed(tool_history):
        result = item.get("result")
        request = item.get("request")
        if (
            item.get("tool") == tool
            and isinstance(result, dict)
            and result.get("available")
            and isinstance(request, dict)
        ):
            return str(request.get(key, "")).strip()
    return ""
