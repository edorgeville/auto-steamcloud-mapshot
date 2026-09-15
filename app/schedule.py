"""When the next render pass should run.

Two shapes: a fixed interval, or a cron expression for "once a day at 4am"
style schedules. Both honour the minimum gap that keeps us off Steam's back.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from .config import MIN_RENDER_INTERVAL, ConfigError, Settings
from .log import log


class Schedule(Protocol):
    description: str

    def next_run(self, after: dt.datetime) -> dt.datetime:
        """The next moment to run, strictly after `after`."""


class Interval:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self.description = f"every {seconds}s"

    def next_run(self, after: dt.datetime) -> dt.datetime:
        return after + dt.timedelta(seconds=self.seconds)


class Cron:
    """A standard five-field cron expression, in the container's local time.

    Set TZ to control which local time that is; the image carries tzdata, so
    `TZ=Europe/Paris` makes `0 4 * * *` mean 4am Paris, daylight saving
    included.
    """

    def __init__(self, expression: str) -> None:
        from cronsim import CronSim, CronSimError

        try:
            CronSim(expression, _now())
        except CronSimError as exc:
            raise ConfigError(
                f"RENDER_CRON is not a valid cron expression: {expression!r} "
                f"({exc}). It takes five fields, so 4am daily is '0 4 * * *'."
            ) from exc

        self.expression = expression
        self.description = f"on cron schedule {expression!r}"

    def next_run(self, after: dt.datetime) -> dt.datetime:
        from cronsim import CronSim

        cursor = CronSim(self.expression, after)
        # Measured from the end of the last pass, so a schedule that fires
        # more often than the floor is thinned rather than obeyed.
        floor = after + dt.timedelta(seconds=MIN_RENDER_INTERVAL)
        try:
            upcoming = next(cursor)
            while upcoming < floor:
                upcoming = next(cursor)
        except StopIteration as exc:
            raise ConfigError(
                f"RENDER_CRON {self.expression!r} never comes round again; "
                "check the day and month fields."
            ) from exc
        return upcoming


def build(settings: Settings) -> Schedule:
    if settings.render_cron:
        schedule = Cron(settings.render_cron)
        log.info("using RENDER_CRON; RENDER_INTERVAL is ignored")
        return schedule

    interval, clamped = settings.effective_interval()
    if clamped:
        log.warning(
            "RENDER_INTERVAL=%ds is below the %ds floor and has been raised. "
            "Steam Cloud pulling is not sanctioned by Valve; polling harder "
            "than this risks the account.",
            settings.render_interval,
            MIN_RENDER_INTERVAL,
        )
    return Interval(interval)


def _now() -> dt.datetime:
    """Local wall-clock time, timezone-aware so cron survives DST."""
    return dt.datetime.now().astimezone()


def describe_delay(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"
