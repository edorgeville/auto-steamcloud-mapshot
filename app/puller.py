"""The Steam Cloud puller interface.

Kept deliberately thin: automated Steam Cloud access is not sanctioned by Valve
and the working approach may change, so the rest of the app talks only to this
protocol and never to a specific tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PullError(Exception):
    """The pull failed. The message is aimed at the operator."""


class SavePuller(Protocol):
    name: str

    def login(self, username: str) -> int:
        """Run the interactive login. Returns a process exit code."""

    def pull(self) -> None:
        """Download anything new. Raises PullError on failure."""

    def saves(self) -> list[Path]:
        """Every Factorio save currently on disk, newest first."""


def get_puller() -> SavePuller:
    from .puller_scsd import ScsdPuller

    return ScsdPuller()
