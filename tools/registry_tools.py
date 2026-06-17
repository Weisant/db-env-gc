"""Docker Hub image resolution tools."""

from __future__ import annotations

import json
import subprocess
from urllib import error, parse, request

from agent.models import ImageResolution


DOCKER_HUB_API_BASE = "https://hub.docker.com/v2"
DOCKER_REGISTRY_API_BASE = "https://registry-1.docker.io/v2"
DOCKER_AUTH_TOKEN_URL = "https://auth.docker.io/token"
REQUEST_TIMEOUT_SECONDS = 15
LEGACY_MANIFEST_TYPES = {
    "application/vnd.docker.distribution.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v1+prettyjws",
}
MODERN_MANIFEST_TYPES = {
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.oci.image.index.v1+json",
}
MANIFEST_ACCEPT = ", ".join([*MODERN_MANIFEST_TYPES, *LEGACY_MANIFEST_TYPES])


def check_image_ref(image_ref: str) -> dict:
    """Check whether one DockerHub image reference exists."""
    namespace, repository, tag = _parse_image_ref(image_ref)
    checked_ref = _build_image_ref(namespace, repository, tag) if repository and tag else image_ref.strip()
    if not repository or not tag:
        return {
            "image_ref": checked_ref,
            "namespace": namespace,
            "repository": repository,
            "tag": tag,
            "available": False,
            "availability": "invalid_ref",
            "notes": ["Image reference must include a repository and tag."],
    }
    try:
        if _tag_exists(namespace, repository, tag):
            manifest = _manifest_status(namespace, repository, tag)
            if not manifest["usable"]:
                return {
                    "image_ref": checked_ref,
                    "namespace": namespace,
                    "repository": repository,
                    "tag": tag,
                    "available": False,
                    "availability": manifest["availability"],
                    "manifest_media_type": manifest["media_type"],
                    "notes": [
                        f"DockerHub image tag exists: {checked_ref}",
                        *manifest["notes"],
                    ],
                }
            return {
                "image_ref": checked_ref,
                "namespace": namespace,
                "repository": repository,
                "tag": tag,
                "available": True,
                "availability": "tag_found",
                "manifest_media_type": manifest["media_type"],
                "notes": [f"DockerHub image tag exists: {checked_ref}"],
            }
        if _repository_exists(namespace, repository):
            return {
                "image_ref": checked_ref,
                "namespace": namespace,
                "repository": repository,
                "tag": tag,
                "available": False,
                "availability": "tag_missing",
                "notes": ["Repository exists, but tag was not found."],
            }
        return {
            "image_ref": checked_ref,
            "namespace": namespace,
            "repository": repository,
            "tag": tag,
            "available": False,
            "availability": "repo_missing",
            "notes": ["Repository was not found on DockerHub."],
        }
    except RuntimeError as exc:
        return {
            "image_ref": checked_ref,
            "namespace": namespace,
            "repository": repository,
            "tag": tag,
            "available": False,
            "availability": "lookup_failed",
            "notes": [f"DockerHub query failed: {exc}"],
        }


def resolve_image_source_for_candidates(
    *,
    db_type: str,
    version: str,
    image_candidates: list[str],
) -> ImageResolution:
    """Query the DockerHub image candidate selected by the planner without database alias inference."""
    requested_version = version.strip()
    candidates = [
        parsed
        for image in image_candidates
        if (parsed := _parse_image_candidate(image)) is not None
    ]
    checked_candidates: list[str] = []

    if not requested_version:
        return ImageResolution(
            db_type=db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="lookup_failed",
            checked_candidates=[],
            notes=["Version is empty; cannot safely evaluate the DockerHub image tag."],
        )
    if not candidates:
        return ImageResolution(
            db_type=db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="lookup_skipped",
            checked_candidates=[],
            notes=["The planner did not select a DockerHub image candidate to query."],
        )

    first_repo_found: ImageResolution | None = None
    try:
        for namespace, repository in candidates:
            checked_candidates.append(f"{namespace}/{repository}:{requested_version}")
            if _tag_exists(namespace, repository, requested_version):
                manifest = _manifest_status(namespace, repository, requested_version)
                image_ref = _build_image_ref(namespace, repository, requested_version)
                if manifest["usable"]:
                    return ImageResolution(
                        db_type=db_type,
                        requested_version=requested_version,
                        namespace=namespace,
                        repository=repository,
                        matched_tag=requested_version,
                        image_ref=image_ref,
                        strategy="official_image",
                        availability="tag_found",
                        checked_candidates=checked_candidates,
                        notes=[
                            f"The image tag selected by the planner exists on DockerHub: {image_ref}",
                            *manifest["notes"],
                        ],
                    )
                if first_repo_found is None:
                    first_repo_found = ImageResolution(
                        db_type=db_type,
                        requested_version=requested_version,
                        namespace=namespace,
                        repository=repository,
                        matched_tag="",
                        image_ref="",
                        strategy="custom_dockerfile",
                        availability=manifest["availability"],
                        checked_candidates=checked_candidates.copy(),
                        notes=[
                            f"The image tag exists on DockerHub but is not treated as usable: {image_ref}",
                            *manifest["notes"],
                        ],
                    )
                continue

            if not _repository_exists(namespace, repository):
                continue

            related_tags = _list_related_tags(namespace, repository, requested_version)
            notes = [
                (
                    f"Confirmed that the repository selected by the planner exists: {namespace}/{repository}; "
                    f"exact tag {requested_version} was not found."
                )
            ]
            if related_tags:
                notes.append("Related tag references: " + ", ".join(related_tags[:10]))
            if first_repo_found is None:
                first_repo_found = ImageResolution(
                    db_type=db_type,
                    requested_version=requested_version,
                    namespace=namespace,
                    repository=repository,
                    matched_tag="",
                    image_ref="",
                    strategy="custom_dockerfile",
                    availability="repo_found_tag_missing",
                    checked_candidates=checked_candidates.copy(),
                    notes=notes,
                )

        if first_repo_found is not None:
            first_repo_found.checked_candidates = checked_candidates
            return first_repo_found

        return ImageResolution(
            db_type=db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="repo_missing",
            checked_candidates=checked_candidates,
            notes=["Could not confirm the DockerHub repository or exact tag selected by the planner."],
        )
    except RuntimeError as exc:
        return ImageResolution(
            db_type=db_type,
            requested_version=requested_version,
            namespace="",
            repository="",
            matched_tag="",
            image_ref="",
            strategy="custom_dockerfile",
            availability="lookup_failed",
            checked_candidates=checked_candidates,
            notes=[f"DockerHub query failed; conservatively falling back to Dockerfile: {exc}"],
        )


def _build_image_ref(namespace: str, repository: str, tag: str) -> str:
    repository_ref = repository if namespace == "library" else f"{namespace}/{repository}"
    return f"{repository_ref}:{tag}"


def _normalize_dockerhub_ref(image: str) -> str:
    image = image.strip()
    if image.startswith("docker.io/library/"):
        return image.removeprefix("docker.io/library/")
    if image.startswith("docker.io/"):
        return image.removeprefix("docker.io/")
    return image


def _parse_image_candidate(image: str) -> tuple[str, str] | None:
    image = _normalize_dockerhub_ref(image)
    if not image or image.upper() == "NONE":
        return None
    image_without_tag = image.split(":", 1)[0]
    if "/" in image_without_tag:
        namespace, repository = image_without_tag.split("/", 1)
        namespace = namespace.strip()
        repository = repository.strip()
    else:
        namespace = "library"
        repository = image_without_tag.strip()
    if not namespace or not repository:
        return None
    return namespace, repository


def _parse_image_ref(image_ref: str) -> tuple[str, str, str]:
    image_ref = _normalize_dockerhub_ref(image_ref)
    if not image_ref:
        return "", "", ""
    image_without_digest = image_ref.split("@", 1)[0]
    if ":" not in image_without_digest.rsplit("/", 1)[-1]:
        return "", image_without_digest, ""
    image_without_tag, tag = image_without_digest.rsplit(":", 1)
    parsed = _parse_image_candidate(image_without_tag)
    if parsed is None:
        return "", "", tag.strip()
    namespace, repository = parsed
    return namespace, repository, tag.strip()


def _repository_exists(namespace: str, repository: str) -> bool:
    url = (
        f"{DOCKER_HUB_API_BASE}/namespaces/"
        f"{parse.quote(namespace)}/repositories/{parse.quote(repository)}"
    )
    status_code, _payload = _fetch_json(url, treat_404_as_none=True)
    return status_code == 200


def _tag_exists(namespace: str, repository: str, tag: str) -> bool:
    url = (
        f"{DOCKER_HUB_API_BASE}/namespaces/{parse.quote(namespace)}"
        f"/repositories/{parse.quote(repository)}/tags/{parse.quote(tag)}"
    )
    status_code, _payload = _fetch_json(url, treat_404_as_none=True)
    return status_code == 200


def _list_related_tags(namespace: str, repository: str, requested_version: str) -> list[str]:
    query = parse.urlencode(
        {
            "page_size": 10,
            "name": requested_version,
        }
    )
    url = (
        f"{DOCKER_HUB_API_BASE}/namespaces/{parse.quote(namespace)}"
        f"/repositories/{parse.quote(repository)}/tags?{query}"
    )
    status_code, payload = _fetch_json(url, treat_404_as_none=True)
    if status_code != 200 or not isinstance(payload, dict):
        return []

    results = payload.get("results")
    if not isinstance(results, list):
        return []

    related_tags: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            related_tags.append(name.strip())
    return related_tags


def _manifest_status(namespace: str, repository: str, tag: str) -> dict:
    repo_path = f"{namespace}/{repository}"
    try:
        token = _registry_token(repo_path)
        media_type = _registry_manifest_media_type(repo_path, tag, token)
    except RuntimeError as exc:
        return {
            "usable": False,
            "availability": "manifest_lookup_failed",
            "media_type": "",
            "notes": [f"Docker registry manifest lookup failed: {exc}"],
        }
    if media_type in LEGACY_MANIFEST_TYPES:
        return {
            "usable": False,
            "availability": "legacy_manifest",
            "media_type": media_type,
            "notes": [
                f"Registry manifest media type is legacy schema v1: {media_type}.",
                "Legacy schema v1 images are treated as unavailable by default.",
            ],
        }
    if media_type in MODERN_MANIFEST_TYPES:
        return {
            "usable": True,
            "availability": "tag_found",
            "media_type": media_type,
            "notes": [f"Registry manifest media type is modern: {media_type}."],
        }
    return {
        "usable": False,
        "availability": "unknown_manifest",
        "media_type": media_type,
        "notes": [
            f"Registry manifest media type is not recognized as modern: {media_type}."
        ],
    }


def _registry_token(repo_path: str) -> str:
    query = parse.urlencode(
        {
            "service": "registry.docker.io",
            "scope": f"repository:{repo_path}:pull",
        }
    )
    status_code, payload = _fetch_json(f"{DOCKER_AUTH_TOKEN_URL}?{query}")
    if status_code != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"token request returned HTTP {status_code}")
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("token response did not contain a token")
    return token


def _registry_manifest_media_type(repo_path: str, tag: str, token: str) -> str:
    url = (
        f"{DOCKER_REGISTRY_API_BASE}/{parse.quote(repo_path, safe='/')}"
        f"/manifests/{parse.quote(tag)}"
    )
    req = request.Request(
        url,
        headers={
            "Accept": MANIFEST_ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": "db-env-gc/0.1",
        },
        method="HEAD",
    )
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"manifest HEAD HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _fetch_json(url: str, *, treat_404_as_none: bool = False) -> tuple[int, dict | None]:
    try:
        return _fetch_json_with_urllib(url, treat_404_as_none=treat_404_as_none)
    except RuntimeError as exc:
        return _fetch_json_with_curl(
            url,
            treat_404_as_none=treat_404_as_none,
            fallback_reason=str(exc),
        )


def _fetch_json_with_urllib(
    url: str,
    *,
    treat_404_as_none: bool = False,
) -> tuple[int, dict | None]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "db-env-gc/0.1",
            "Connection": "close",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict):
                return response.status, payload
            return response.status, {"raw": payload}
    except error.HTTPError as exc:
        if treat_404_as_none and exc.code == 404:
            return 404, None
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _fetch_json_with_curl(
    url: str,
    *,
    treat_404_as_none: bool = False,
    fallback_reason: str,
) -> tuple[int, dict | None]:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--header",
        "Accept: application/json",
        "--header",
        "User-Agent: db-env-gc/0.1",
        "--write-out",
        "\n%{http_code}",
        url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{fallback_reason}; curl fallback failed: {exc}") from exc

    output = completed.stdout
    if "\n" not in output:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback returned malformed response: {completed.stderr.strip()}"
        )

    body, status_text = output.rsplit("\n", 1)
    try:
        status_code = int(status_text.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback returned invalid status code: {status_text}"
        ) from exc

    if treat_404_as_none and status_code == 404:
        return 404, None
    if status_code >= 400:
        raise RuntimeError(
            f"{fallback_reason}; curl fallback HTTP {status_code}: {completed.stderr.strip() or body}"
        )

    payload = json.loads(body) if body else {}
    if isinstance(payload, dict):
        return status_code, payload
    return status_code, {"raw": payload}
