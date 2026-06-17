"""URL probing helpers for planner artifact resolution."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check_download_url(url: str) -> dict:
    """Check whether a source or binary artifact URL is reachable without downloading it."""
    normalized_url = url.strip()
    if not normalized_url:
        return {
            "url": normalized_url,
            "available": False,
            "status_code": 0,
            "notes": ["URL is empty."],
        }
    head_result = _request_url(normalized_url, method="HEAD")
    if head_result["available"] or head_result["status_code"] == 404:
        return head_result
    return _request_url(normalized_url, method="GET", headers={"Range": "bytes=0-0"})


def _request_url(url: str, *, method: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(
        url,
        method=method,
        headers={
            "User-Agent": "db-env-gc/1.0",
            **(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            status_code = int(getattr(response, "status", 200))
            return {
                "url": url,
                "available": 200 <= status_code < 400,
                "status_code": status_code,
                "notes": [f"HTTP {method} returned {status_code}."],
            }
    except HTTPError as exc:
        return {
            "url": url,
            "available": False,
            "status_code": exc.code,
            "notes": [f"HTTP {method} returned {exc.code}."],
        }
    except (URLError, TimeoutError) as exc:
        return {
            "url": url,
            "available": False,
            "status_code": 0,
            "notes": [f"HTTP {method} failed: {exc}"],
        }
