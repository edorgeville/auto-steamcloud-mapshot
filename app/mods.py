"""Mod syncing.

mapshot renders with whatever mod list is active in the container rather than
the one the save was made with (mapshot issue #20). `factorio --sync-mods`
before every render downloads and enables exactly the save's mod set, using the
service credentials in player-data.json.
"""

from __future__ import annotations

from pathlib import Path

from . import versions, xvfb
from .install import Install
from .log import log
from .proc import run


class ModSyncError(Exception):
    """Syncing mods failed for a reason that is not a version mismatch."""


def sync(install: Install, save: Path, timeout: float | None = None) -> str:
    """Sync mods to the save's mod list. Returns the merged command output."""
    log.info("syncing mods to the save's mod list")
    result = run(
        xvfb.wrap([install.binary, "--sync-mods", save]),
        env=xvfb.env(),
        timeout=timeout,
    )
    output = result.output + "\n" + versions.read_log(install.log_file)

    if result.ok:
        log.info("mods in sync")
        return output

    # A version mismatch surfaces here too when Factorio reads the save header,
    # which is far cheaper than discovering it part-way through a render. The
    # caller inspects the output and decides.
    if versions.find(output):
        return output

    raise ModSyncError(
        f"factorio --sync-mods failed with exit {result.returncode}. The mod "
        "portal needs valid FACTORIO_USERNAME / FACTORIO_TOKEN; see the output "
        "above."
    )
