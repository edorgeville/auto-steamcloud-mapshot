"""Version-keyed Factorio installs under /data/factorio/<version>.

The Linux tarball is self-contained (config-path.cfg sets
use-system-read-write-data-directories=false), so the install directory is also
Factorio's write-data directory: mods/, saves/, script-output/,
player-data.json and factorio-current.log all live inside it. Mods are shared
across versions through a symlink so a game update does not cost a full mod
re-download.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import INSTALLS_DIR, MODS_DIR, PLAYER_DATA, STAGING_DIR, Settings
from .log import log
from .proc import Terminated, shutdown
from .releases import DownloadError, open_download


@dataclass(frozen=True)
class Install:
    version: str
    root: Path

    @property
    def binary(self) -> Path:
        return self.root / "bin" / "x64" / "factorio"

    @property
    def datadir(self) -> Path:
        return self.root

    @property
    def mods_dir(self) -> Path:
        return self.root / "mods"

    @property
    def log_file(self) -> Path:
        return self.root / "factorio-current.log"

    @property
    def exists(self) -> bool:
        return self.binary.is_file()


def install_for(version: str) -> Install:
    return Install(version=version, root=INSTALLS_DIR / version)


def installed_versions() -> list[str]:
    if not INSTALLS_DIR.is_dir():
        return []
    return sorted(
        child.name
        for child in INSTALLS_DIR.iterdir()
        if child.is_dir() and not child.name.startswith(".") and install_for(child.name).exists
    )


def ensure(version: str, settings: Settings) -> Install:
    """Return a ready-to-use install, downloading the client if needed."""
    install = install_for(version)
    if install.exists:
        log.info("Factorio %s already installed at %s", version, install.root)
    else:
        settings.require_factorio_credentials()
        _fetch(version, settings)
    _prepare(install, settings)
    os.utime(install.root, None)
    return install


def _fetch(version: str, settings: Settings) -> None:
    incoming = INSTALLS_DIR / f".incoming-{version}"
    shutil.rmtree(incoming, ignore_errors=True)
    incoming.mkdir(parents=True)

    log.warning(
        "Factorio %s (%s) is not installed yet. The full client with assets is "
        "several gigabytes; this download happens once per version.",
        version,
        settings.factorio_build,
    )

    try:
        with open_download(
            version,
            settings.factorio_build,
            settings.factorio_username,
            settings.factorio_token,
        ) as (stream, total):
            _extract(stream, total, incoming)
    except BaseException:
        shutil.rmtree(incoming, ignore_errors=True)
        raise

    target = INSTALLS_DIR / version
    shutil.rmtree(target, ignore_errors=True)
    incoming.replace(target)
    log.info("Factorio %s installed at %s", version, target)


def _extract(stream, total: int, dest: Path) -> None:
    """Pipe the tarball straight into tar, so the archive never hits disk."""
    tar = subprocess.Popen(  # noqa: S603 - fixed argv, never a shell string
        ["tar", "-xJ", "-C", str(dest), "--strip-components=1"],  # noqa: S607 - from the image
        stdin=subprocess.PIPE,
        start_new_session=True,
    )
    stdin = tar.stdin
    if stdin is None:  # pragma: no cover - stdin=PIPE guarantees a pipe
        raise DownloadError("could not open a pipe to tar")
    done = 0
    last_report = time.monotonic()
    try:
        while True:
            if shutdown.is_set():
                raise Terminated("download interrupted by shutdown")
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            stdin.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if now - last_report >= 15:
                _log_progress(done, total)
                last_report = now
        stdin.close()
    except BaseException:
        tar.kill()
        tar.wait()
        raise

    _log_progress(done, total)
    if tar.wait() != 0:
        raise DownloadError(
            f"extracting the Factorio tarball failed (tar exit {tar.returncode})"
        )


def _log_progress(done: int, total: int) -> None:
    mib = done / (1 << 20)
    if total:
        log.info(
            "  downloaded and extracted %.0f MiB of %.0f MiB (%.0f%%)",
            mib,
            total / (1 << 20),
            100 * done / total,
        )
    else:
        log.info("  downloaded and extracted %.0f MiB", mib)


def _prepare(install: Install, settings: Settings) -> None:
    (install.root / "saves").mkdir(exist_ok=True)
    _link_script_output(install)
    _link_mods(install)
    _write_player_data(install, settings)


def _link_script_output(install: Install) -> None:
    """Point the install's script-output at the shared staging directory.

    Factorio has no --script-output flag: it always writes below its own
    write-data directory, and mapshot's --factorio_scriptoutput only tells
    mapshot where to *look*. Passing mapshot a path Factorio does not write to
    makes it wait forever for a done-marker that never arrives. A symlink is
    the only way to keep both pointing at the same place.
    """
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    _relink(install.root / "script-output", STAGING_DIR)


def _link_mods(install: Install) -> None:
    MODS_DIR.mkdir(parents=True, exist_ok=True)
    mod_list = MODS_DIR / "mod-list.json"
    if not mod_list.exists():
        # mapshot's CopyMods refuses to run without this file.
        mod_list.write_text(json.dumps({"mods": [{"name": "base", "enabled": True}]}) + "\n")

    _relink(install.mods_dir, MODS_DIR)


def _relink(link: Path, target: Path) -> None:
    """Replace link with a symlink to target, whatever was there before."""
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        link.unlink()
    elif link.is_dir():
        shutil.rmtree(link)
    elif link.exists():
        link.unlink()
    link.symlink_to(target, target_is_directory=True)
    log.debug("linked %s -> %s", link, target)


def _write_player_data(install: Install, settings: Settings) -> None:
    """Seed player-data.json so --sync-mods can authenticate to the mod portal."""
    data: dict[str, object] = {}
    if PLAYER_DATA.is_file():
        try:
            data = json.loads(PLAYER_DATA.read_text())
        except json.JSONDecodeError:
            log.warning("%s is not valid JSON, rewriting it", PLAYER_DATA)
            data = {}

    if settings.factorio_username:
        data["service-username"] = settings.factorio_username
    if settings.factorio_token:
        data["service-token"] = settings.factorio_token

    PLAYER_DATA.parent.mkdir(parents=True, exist_ok=True)
    PLAYER_DATA.write_text(json.dumps(data, indent=2) + "\n")
    (install.root / "player-data.json").write_text(json.dumps(data, indent=2) + "\n")


def prune(keep: int, in_use: str) -> None:
    """Drop least-recently-used installs, never the one in use."""
    versions = [v for v in installed_versions() if v != in_use]
    if len(versions) + 1 <= keep:
        return
    versions.sort(key=lambda v: install_for(v).root.stat().st_mtime, reverse=True)
    for version in versions[max(0, keep - 1) :]:
        root = install_for(version).root
        log.info("pruning Factorio %s from %s", version, root)
        shutil.rmtree(root, ignore_errors=True)
