"""Running mapshot and publishing the result.

mapshot's mod writes mapshot.json *before* it generates a single tile
(mod/control.lua), so a directory can look like a finished render while it is
still half empty. An interrupted render written straight into /output would
therefore replace a good map with a broken one. So renders go to a staging
directory on /data and are published into /output only once mapshot has
reported success.

Publishing also repoints /output/current, the symlink the HTTP root serves.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import versions, xvfb
from .config import (
    MAPSHOT_BIN,
    MAPSHOT_PREFIX,
    OUTPUT_CURRENT,
    OUTPUT_DIR,
    STAGING_DIR,
    WORK_DIR,
    Settings,
)
from .install import Install
from .log import log
from .proc import run
from .versions import Mismatch

OUTPUT_LINE = re.compile(r"^Output:\s*(?P<path>.+)$", re.MULTILINE)
SHOT_DIR = "d-*"


class RenderError(Exception):
    """The render failed."""


class VersionMismatch(Exception):
    """The save needs a different Factorio version."""

    def __init__(self, mismatch: Mismatch) -> None:
        super().__init__(mismatch.describe())
        self.mismatch = mismatch


def save_display_name(save: Path) -> str:
    """The directory name mapshot derives from a save path."""
    return save.name[: -len(save.suffix)] if save.suffix else save.name


def render(install: Install, save: Path, settings: Settings) -> Path:
    """Render into staging and return the produced shot directory."""
    _reset(STAGING_DIR)
    _reset(WORK_DIR)

    cmd = [
        MAPSHOT_BIN,
        "render",
        "--factorio_binary",
        install.binary,
        "--factorio_datadir",
        install.datadir,
        "--factorio_scriptoutput",
        STAGING_DIR,
        "--work_dir",
        WORK_DIR,
        "--prefix",
        MAPSHOT_PREFIX,
        *settings.mapshot.flags(),
        "--factorio_verbose",
        "--logtostderr",
    ]
    if settings.factorio_extra_args:
        cmd += ["--factorio_extra_args", settings.factorio_extra_args]
    cmd.append(save)

    log.info(
        "rendering %s; this takes a long while and Factorio looks frozen "
        "while it works",
        save.name,
    )
    result = run(xvfb.wrap(cmd), env=xvfb.env(), timeout=settings.render_timeout)
    output = result.output + "\n" + versions.read_log(install.log_file)

    mismatch = versions.find(output)
    if mismatch:
        raise VersionMismatch(mismatch)
    if not result.ok:
        raise RenderError(f"mapshot render failed with exit {result.returncode}")

    shot = _locate_shot(result.output, save)
    log.info("render complete: %s", shot)
    return shot


def _reset(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def _locate_shot(output: str, save: Path) -> Path:
    match = OUTPUT_LINE.search(output)
    if match:
        candidate = Path(match.group("path").strip())
        if candidate.is_dir():
            return candidate

    # Staging was emptied before the render, so there is exactly one shot.
    base = STAGING_DIR / MAPSHOT_PREFIX.strip("/") / save_display_name(save)
    shots = sorted(base.glob(SHOT_DIR)) if base.is_dir() else []
    if len(shots) != 1:
        raise RenderError(
            f"expected exactly one render below {base}, found {len(shots)}"
        )
    return shots[0]


def publish(shot: Path, save: Path) -> Path:
    """Move a finished render into /output, replacing the previous one."""
    name = save_display_name(save)
    staged_save_dir = shot.parent
    dest_save_dir = OUTPUT_DIR / MAPSHOT_PREFIX.strip("/") / name
    dest_save_dir.mkdir(parents=True, exist_ok=True)

    # /data and /output are usually different mounts, so move across devices
    # under a temporary name first, then rename within the destination. The
    # rename is atomic, so nothing incomplete is ever visible to the server.
    incoming = dest_save_dir / f".incoming-{shot.name}"
    shutil.rmtree(incoming, ignore_errors=True)
    shutil.move(str(shot), str(incoming))

    final = dest_save_dir / shot.name
    shutil.rmtree(final, ignore_errors=True)
    incoming.rename(final)

    # The viewer html and js sit next to the shot directories and point at the
    # newest one, so they are refreshed after it is in place.
    for item in staged_save_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, dest_save_dir / item.name)

    _drop_older(dest_save_dir, keep=final.name)
    _point_current(dest_save_dir)
    _drop_other_saves(keep=dest_save_dir)
    log.info("published to %s", final)
    return final


def _point_current(save_dir: Path) -> None:
    """Repoint the HTTP root at the map just published.

    The swap is a rename over the old symlink, so a request either sees the
    previous map or the new one, never neither. The target is relative so the
    link keeps working wherever /output is mounted.
    """
    link = OUTPUT_CURRENT
    staged = link.with_name(f".{link.name}-new")
    if staged.is_symlink() or staged.exists():
        staged.unlink()
    staged.symlink_to(save_dir.relative_to(OUTPUT_DIR), target_is_directory=True)

    if link.is_dir() and not link.is_symlink():
        # Only possible if something else created it; a rename would fail.
        shutil.rmtree(link)
    staged.replace(link)
    log.info("serving %s at the http root", save_dir.name)


def _drop_other_saves(keep: Path) -> None:
    """Remove maps for saves we no longer render.

    Only one save is rendered at a time, so when the newest cloud save changes
    name its predecessor becomes unreachable dead weight - roughly a gigabyte
    of it.
    """
    root = OUTPUT_DIR / MAPSHOT_PREFIX.strip("/")
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir() and child != keep:
            log.info("removing the map for %s, which is no longer rendered", child.name)
            shutil.rmtree(child, ignore_errors=True)


def _drop_older(save_dir: Path, keep: str) -> None:
    """Keep only the newest render; snapshot history is an explicit non-goal."""
    for child in save_dir.glob(SHOT_DIR):
        if child.name != keep and child.is_dir():
            log.info("removing superseded render %s", child)
            shutil.rmtree(child, ignore_errors=True)
    for stale in save_dir.glob(".incoming-*"):
        shutil.rmtree(stale, ignore_errors=True)


def has_render_for(save: Path) -> bool:
    """True when /output already holds a finished render of this save."""
    save_dir = OUTPUT_DIR / MAPSHOT_PREFIX.strip("/") / save_display_name(save)
    return any((shot / "mapshot.json").is_file() for shot in save_dir.glob(SHOT_DIR))
