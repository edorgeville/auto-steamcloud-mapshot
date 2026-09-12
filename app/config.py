"""Environment parsing and path constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

FACTORIO_APPID = 427520

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))

# scsd keeps its session, its database and every pulled save in one directory.
# The default is under /config so `login-steam` works with only /config
# mounted, but Steam hands over every Factorio cloud file, not just the one
# being rendered, so this can run to a gigabyte. Point it at /data to move the
# bulk off the config volume.
STEAM_DIR = Path(os.environ.get("STEAM_DIR", str(CONFIG_DIR / "steam")))
SCSD_CONF = STEAM_DIR / "scsd.conf"
STATE_FILE = CONFIG_DIR / "state.json"
LOCK_FILE = CONFIG_DIR / "render.lock"
PLAYER_DATA = CONFIG_DIR / "player-data.json"

INSTALLS_DIR = DATA_DIR / "factorio"
MODS_DIR = DATA_DIR / "mods"
STAGING_DIR = DATA_DIR / "staging"
WORK_DIR = DATA_DIR / "work"

MAPSHOT_BIN = Path(os.environ.get("MAPSHOT_BIN", "/usr/local/bin/mapshot"))
SCSD_BIN = Path(os.environ.get("SCSD_BIN", "/opt/venv/bin/scsd"))

# mapshot writes below <script-output>/<prefix>; keep it fixed so publishing is
# deterministic.
MAPSHOT_PREFIX = "mapshot/"

# Steam is scraped, not API-driven, and the puller self-throttles. Refuse to
# poll more often than this regardless of configuration.
MIN_RENDER_INTERVAL = 900


class ConfigError(Exception):
    """Raised for a misconfiguration the operator has to fix."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _opt_int(name: str) -> int | None:
    raw = _env(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class MapshotSettings:
    """Passthrough render parameters. None means 'use the mapshot default'."""

    area: str = "player"
    tilemin: int | None = None
    tilemax: int | None = None
    resolution: int | None = None
    jpgquality: int | None = None
    minjpgquality: int | None = None
    surface: str = "_all_"

    @classmethod
    def from_env(cls) -> MapshotSettings:
        area = _env("MAPSHOT_AREA", "player")
        if area not in ("player", "entities", "all"):
            raise ConfigError(
                f"MAPSHOT_AREA must be one of player, entities, all; got {area!r}"
            )
        return cls(
            area=area,
            tilemin=_opt_int("MAPSHOT_TILEMIN"),
            tilemax=_opt_int("MAPSHOT_TILEMAX"),
            resolution=_opt_int("MAPSHOT_RESOLUTION"),
            jpgquality=_opt_int("MAPSHOT_JPGQUALITY"),
            minjpgquality=_opt_int("MAPSHOT_MINJPGQUALITY"),
            surface=_env("MAPSHOT_SURFACE", "_all_"),
        )

    def flags(self) -> list[str]:
        """Build mapshot render flags.

        mapshot 0.0.28 gates minjpgquality on jpgquality in
        RenderFlags.genOverrides, so only pass a value when we have one and
        never rely on the -1 sentinel.
        """
        flags = ["--area", self.area, "--surface", self.surface]
        for name, value in (
            ("tilemin", self.tilemin),
            ("tilemax", self.tilemax),
            ("resolution", self.resolution),
            ("jpgquality", self.jpgquality),
            ("minjpgquality", self.minjpgquality),
        ):
            if value is not None:
                flags += [f"--{name}", str(value)]
        return flags


@dataclass(frozen=True)
class Settings:
    factorio_username: str
    factorio_token: str
    factorio_build: str
    factorio_version: str
    factorio_extra_args: str
    factorio_keep_versions: int
    steam_username: str
    steam_2fa: str
    scsd_rotation: int
    save_name: str
    render_interval: int
    render_timeout: int
    serve_port: int
    mapshot: MapshotSettings = field(default_factory=MapshotSettings)

    @property
    def auto_version(self) -> bool:
        return self.factorio_version == "auto"

    def require_factorio_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("FACTORIO_USERNAME", self.factorio_username),
                ("FACTORIO_TOKEN", self.factorio_token),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"{' and '.join(missing)} must be set. Get a service token at "
                "https://factorio.com/profile, or copy service-username and "
                "service-token out of an existing player-data.json."
            )

    @classmethod
    def from_env(cls) -> Settings:
        build = _env("FACTORIO_BUILD", "expansion")
        if build not in ("expansion", "alpha"):
            raise ConfigError(
                f"FACTORIO_BUILD must be expansion or alpha; got {build!r}. "
                "The headless build cannot render and is not accepted."
            )

        two_fa = _env("STEAM_2FA", "mobile")
        if two_fa not in ("mobile", "mail"):
            raise ConfigError(f"STEAM_2FA must be mobile or mail; got {two_fa!r}")

        interval = _env_int("RENDER_INTERVAL", 3600)

        return cls(
            factorio_username=_env("FACTORIO_USERNAME"),
            factorio_token=_env("FACTORIO_TOKEN"),
            factorio_build=build,
            factorio_version=_env("FACTORIO_VERSION", "auto"),
            factorio_extra_args=_env("FACTORIO_EXTRA_ARGS"),
            factorio_keep_versions=max(1, _env_int("FACTORIO_KEEP_VERSIONS", 2)),
            steam_username=_env("STEAM_USERNAME"),
            steam_2fa=two_fa,
            # Only the newest save is ever rendered, so keeping older copies of
            # each cloud file just costs disk.
            scsd_rotation=max(1, _env_int("SCSD_ROTATION", 1)),
            save_name=_env("SAVE_NAME"),
            render_interval=interval,
            # A backstop, not a budget. Renders are legitimately slow, but a
            # Factorio that never signals completion must not wedge the loop.
            render_timeout=_env_int("RENDER_TIMEOUT", 14400),
            serve_port=_env_int("SERVE_PORT", 8080),
            mapshot=MapshotSettings.from_env(),
        )

    def effective_interval(self) -> tuple[int, bool]:
        """Return the interval to use and whether it had to be clamped."""
        if self.render_interval < MIN_RENDER_INTERVAL:
            return MIN_RENDER_INTERVAL, True
        return self.render_interval, False
