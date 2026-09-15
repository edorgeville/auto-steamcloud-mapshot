"""One render pass: pull, check, install, sync mods, render, publish."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

from . import install as installs
from . import mods, render
from .config import Settings
from .lock import Busy, render_lock
from .log import banner, log
from .puller import PullError, SavePuller, get_puller
from .releases import resolve_version
from .state import State

CHANNELS = {"stable": "stable", "latest": "experimental"}


class PipelineError(Exception):
    """A failure the operator can act on. Reported as one line, not a traceback."""


def run_once(settings: Settings, puller: SavePuller | None = None) -> bool:
    """Run a full pass. Returns True when a new render was published."""
    try:
        with render_lock():
            return _pass(settings, puller or get_puller())
    except Busy:
        log.warning("a render is already running, skipping this wake-up")
        return False


def _pass(settings: Settings, puller: SavePuller) -> bool:
    banner("checking for a new save")

    try:
        puller.pull()
    except PullError as exc:
        raise PipelineError(f"steam pull failed: {exc}") from exc

    save = _choose_save(puller, settings)
    digest = _sha256(save)
    state = State.load()

    if (
        digest == state.save_sha256
        and save.name == state.save_name
        and render.has_render_for(save)
    ):
        if render.ensure_current(save):
            log.info("the existing render was not being served; repointed it")
        log.info("no change, skipping (%s, sha256 %s)", save.name, digest[:12])
        return False

    banner(f"rendering {save.name}")
    log.info("save %s (%.1f MiB, sha256 %s)", save, save.stat().st_size / (1 << 20), digest[:12])

    version = _target_version(settings, state)
    install = installs.ensure(version, settings)

    try:
        shot = _attempt(install, save, settings)
    except render.VersionMismatch as exc:
        install = _handle_mismatch(exc, settings)
        version = install.version
        try:
            shot = _attempt(install, save, settings)
        except render.VersionMismatch as retry_exc:
            raise PipelineError(
                f"{retry_exc.mismatch.describe()} even after installing "
                f"{version}. Pin FACTORIO_VERSION to the version the save "
                "was made with."
            ) from retry_exc

    published = render.publish(shot, save)
    installs.prune(settings.factorio_keep_versions, in_use=version)

    State(
        save_name=save.name,
        save_sha256=digest,
        factorio_version=version,
        output_path=str(published),
        rendered_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    ).save()
    banner("render published")
    return True


def _attempt(install: installs.Install, save: Path, settings: Settings) -> Path:
    from . import versions
    from .proc import Timeout

    try:
        output = mods.sync(install, save, timeout=settings.render_timeout)
        mismatch = versions.find(output)
        if mismatch:
            raise render.VersionMismatch(mismatch)
        return render.render(install, save, settings)
    except Timeout as exc:
        raise PipelineError(
            f"render failed: {exc}. Nothing was written to the output. Raise "
            "RENDER_TIMEOUT if this map legitimately needs longer."
        ) from exc


def _handle_mismatch(exc: render.VersionMismatch, settings: Settings) -> installs.Install:
    if not settings.auto_version:
        raise PipelineError(
            f"version mismatch: {exc.mismatch.describe()}. FACTORIO_VERSION is "
            f"pinned to {settings.factorio_version}, so no other version will "
            f"be fetched. Set FACTORIO_VERSION=auto, or pin it to "
            f"{exc.mismatch.save_version}."
        ) from exc
    log.warning(
        "version mismatch, re-fetching Factorio %s (%s)",
        exc.mismatch.save_version,
        exc.mismatch.describe(),
    )
    return installs.ensure(exc.mismatch.save_version, settings)


def _choose_save(puller: SavePuller, settings: Settings) -> Path:
    saves = puller.saves()
    if not saves:
        raise PipelineError(
            "no Factorio save found in Steam Cloud. Saves upload when the game "
            "exits, so play and quit once, then wait for Steam to sync."
        )
    if not settings.save_name:
        chosen = saves[0]
        log.info("using the most recent cloud save: %s", chosen.name)
        return chosen

    wanted = settings.save_name
    for candidate in saves:
        if candidate.name in (wanted, f"{wanted}.zip"):
            return candidate
    available = ", ".join(sorted(s.name for s in saves))
    raise PipelineError(
        f"SAVE_NAME is {wanted!r} but Steam Cloud only has: {available}"
    )


def _target_version(settings: Settings, state: State) -> str:
    pinned = settings.factorio_version
    if pinned in CHANNELS:
        return resolve_version(CHANNELS[pinned], settings.factorio_build)
    if not settings.auto_version:
        log.info("FACTORIO_VERSION is pinned to %s", pinned)
        return pinned
    if state.factorio_version and installs.install_for(state.factorio_version).exists:
        log.info("starting from the last known good version %s", state.factorio_version)
        return state.factorio_version
    return resolve_version("stable", settings.factorio_build)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
