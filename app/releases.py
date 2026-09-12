"""factorio.com release lookup and authenticated client download."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

from .log import log

LATEST_RELEASES = "https://factorio.com/api/latest-releases"
DOWNLOAD = "https://factorio.com/get-download/{version}/{build}/{distro}"
DISTRO = "linux64"
USER_AGENT = "factorio-mapshot-cloud"


class DownloadError(Exception):
    """The Factorio client could not be fetched."""


def latest_releases(timeout: int = 30) -> dict[str, dict[str, str]]:
    request = urllib.request.Request(LATEST_RELEASES, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise DownloadError(f"could not read {LATEST_RELEASES}: {exc}") from exc


def resolve_version(channel: str, build: str) -> str:
    """Turn 'stable' or 'experimental' into a concrete version string."""
    releases = latest_releases()
    try:
        version = releases[channel][build]
    except KeyError as exc:
        raise DownloadError(
            f"factorio.com has no {channel} release for build {build!r}"
        ) from exc
    log.info("factorio.com %s %s is %s", channel, build, version)
    return version


def _url(version: str, build: str) -> str:
    return DOWNLOAD.format(version=version, build=build, distro=DISTRO)


@contextmanager
def open_download(
    version: str,
    build: str,
    username: str,
    token: str,
    timeout: int = 120,
) -> Iterator[tuple[IO[bytes], int]]:
    """Open the client tarball for streaming. Yields (stream, content length).

    Credentials go in the query string, so the URL is never logged verbatim.
    """
    query = urllib.parse.urlencode({"username": username, "token": token})
    request = urllib.request.Request(  # noqa: S310 - https URL built from a constant
        f"{_url(version, build)}?{query}", headers={"User-Agent": USER_AGENT}
    )
    log.info("requesting %s?username=...&token=...", _url(version, build))
    try:
        response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as exc:
        raise DownloadError(_explain_http(exc, version, build)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DownloadError(f"download of Factorio {version} failed: {exc}") from exc

    with response:
        total = int(response.headers.get("Content-Length") or 0)
        yield response, total


def _explain_http(exc: urllib.error.HTTPError, version: str, build: str) -> str:
    if exc.code in (401, 403):
        return (
            f"factorio.com refused the download of {version} ({build}): "
            "FACTORIO_USERNAME / FACTORIO_TOKEN are wrong, or the account does "
            "not own this build. A Steam purchase needs the Steam account "
            "linked at https://factorio.com/profile once before the DRM-free "
            "downloads appear."
        )
    if exc.code == 404:
        return (
            f"factorio.com has no {build} build for version {version}. Check "
            "FACTORIO_VERSION against https://factorio.com/api/latest-releases."
        )
    return f"factorio.com returned HTTP {exc.code} for version {version} ({build})"
