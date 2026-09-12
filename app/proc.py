"""Subprocess helpers with group-wide shutdown.

mapshot runs Factorio as a grandchild and installs no signal handler of its own
(mapshot.go uses context.Background()), so killing the direct child is not
enough. Every child is started in its own session and signalled by process
group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .log import log

TERM_GRACE_SECONDS = 20

shutdown = threading.Event()

_registry_lock = threading.Lock()
_running: set[int] = set()


class Terminated(Exception):
    """A child was killed because the container is shutting down."""


class Timeout(Exception):
    """A child overran its deadline and was killed."""


@dataclass
class Result:
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _register(pgid: int) -> None:
    with _registry_lock:
        _running.add(pgid)


def _unregister(pgid: int) -> None:
    with _registry_lock:
        _running.discard(pgid)


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        log.warning("not permitted to signal process group %d", pgid)


def kill_all() -> None:
    """SIGTERM every running child group, then SIGKILL what survives."""
    with _registry_lock:
        groups = list(_running)
    if not groups:
        return
    log.info("shutdown: terminating %d child process group(s)", len(groups))
    for pgid in groups:
        _signal_group(pgid, signal.SIGTERM)

    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        with _registry_lock:
            if not _running:
                return
        time.sleep(0.2)

    with _registry_lock:
        groups = list(_running)
    for pgid in groups:
        log.warning("shutdown: process group %d ignored SIGTERM, killing", pgid)
        _signal_group(pgid, signal.SIGKILL)


def install_signal_handlers() -> None:
    def handler(signum: int, _frame: object) -> None:
        if shutdown.is_set():
            return
        log.info("received %s, shutting down", signal.Signals(signum).name)
        shutdown.set()
        kill_all()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handler)


def run(
    cmd: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    echo: bool = True,
    on_line: Callable[[str], None] | None = None,
    capture_limit: int = 512_000,
    timeout: float | None = None,
) -> Result:
    """Run a command, streaming its merged output, and return the result.

    Raises Terminated if the command was cut short by a shutdown signal, or
    Timeout if it overran `timeout` seconds and had to be killed.
    """
    argv = [str(part) for part in cmd]
    log.debug("exec: %s", " ".join(argv))

    proc = subprocess.Popen(  # noqa: S603 - argv is built internally, never a shell string
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    pgid = proc.pid
    _register(pgid)

    timed_out = threading.Event()
    watchdog: threading.Timer | None = None
    if timeout is not None:
        def expire() -> None:
            timed_out.set()
            log.error("%s exceeded its %.0fs deadline, killing it", argv[0], timeout)
            _signal_group(pgid, signal.SIGTERM)
            time.sleep(TERM_GRACE_SECONDS)
            _signal_group(pgid, signal.SIGKILL)

        watchdog = threading.Timer(timeout, expire)
        watchdog.daemon = True
        watchdog.start()

    chunks: list[str] = []
    size = 0
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]  # stdout=PIPE above
            line = raw.rstrip("\n")
            if size < capture_limit:
                chunks.append(line)
                size += len(line) + 1
            if echo:
                log.info("  | %s", line)
            if on_line:
                on_line(line)
        returncode = proc.wait()
    finally:
        if watchdog is not None:
            watchdog.cancel()
        _unregister(pgid)

    if shutdown.is_set():
        raise Terminated(f"{argv[0]} was terminated during shutdown")
    if timed_out.is_set():
        raise Timeout(f"{argv[0]} exceeded its {timeout:.0f}s deadline")

    return Result(returncode=returncode, output="\n".join(chunks))


def run_interactive(cmd: Sequence[str | Path]) -> int:
    """Run a command attached to the terminal, for the Steam Guard prompt."""
    argv = [str(part) for part in cmd]
    log.debug("exec (interactive): %s", " ".join(argv))
    return subprocess.call(argv)  # noqa: S603 - argv is built internally
