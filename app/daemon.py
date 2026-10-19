"""Default mode: serve continuously, render on a schedule."""

from __future__ import annotations

import contextlib
import datetime as dt
import threading
import time
from pathlib import Path

from . import pipeline, schedule, serve
from .config import Settings
from .log import log
from .proc import Terminated, shutdown

# Epoch seconds of the pass the loop is running or waiting for. The healthcheck
# treats a loop that is far past it as wedged.
HEARTBEAT_FILE = Path("/tmp/mapshot-cloud-heartbeat")  # noqa: S108 - container-local marker


def run(settings: Settings) -> int:
    # Built before anything else so a bad RENDER_CRON fails at startup rather
    # than hours later.
    plan = schedule.build(settings)

    server = threading.Thread(
        target=serve.serve_forever, args=(settings,), name="serve", daemon=True
    )
    server.start()

    # A pass runs at startup whatever the schedule says: with a daily cron and
    # an empty /output, waiting until 4am would mean serving nothing all day.
    # An unchanged save makes it a cheap no-op anyway.
    log.info("render loop started, running %s", plan.description)
    while not shutdown.is_set():
        _beat(time.time())
        try:
            pipeline.run_once(settings)
        except Terminated:
            break
        except pipeline.PipelineError as exc:
            log.error("render failed: %s", exc)
            log.info("keeping the previous render online")
        except Exception:  # the loop must survive anything, or the site goes stale
            log.exception("render failed with an unexpected error")
            log.info("keeping the previous render online")

        if _wait(plan):
            break

    log.info("render loop stopped")
    return 0


def _wait(plan: schedule.Schedule) -> bool:
    """Sleep until the next run. True if we were told to shut down instead."""
    now = dt.datetime.now().astimezone()
    try:
        upcoming = plan.next_run(now)
    except Exception:
        log.exception("could not work out the next run time; stopping the loop")
        return True

    delay = max(0.0, (upcoming - now).total_seconds())
    _beat(upcoming.timestamp())
    log.info(
        "next check at %s (in %s)",
        upcoming.strftime("%Y-%m-%d %H:%M:%S %Z"),
        schedule.describe_delay(delay),
    )
    return shutdown.wait(delay)


def _beat(when: float) -> None:
    with contextlib.suppress(OSError):
        HEARTBEAT_FILE.write_text(f"{when:.0f}")


def stale(settings: Settings, now: float | None = None) -> bool:
    """True when the loop is far past the pass it last announced."""
    try:
        due = float(HEARTBEAT_FILE.read_text())
    except (OSError, ValueError):
        return False
    # A pass is bounded by its pull and render deadlines; well past both, the
    # loop is stuck on something without a timeout.
    grace = settings.pull_timeout + 2 * settings.render_timeout
    return (now or time.time()) > due + grace
