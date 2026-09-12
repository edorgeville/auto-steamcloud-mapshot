"""Detection of save/client version mismatches.

The brief rules out parsing version bytes out of the save archive, so the
version is learned from what Factorio says when it refuses to load the save.
Factorio's wording is:

    Map version 2.0.77-0 cannot be loaded because it is higher than the game
    version (2.0.60-1)

That text reaches us either on the merged stdout/stderr (mapshot is run with
--factorio_verbose) or in factorio-current.log inside the install directory.
Both are checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .log import log

# The precise phrasing, plus a looser fallback in case it is reworded.
PATTERNS = (
    re.compile(
        r"Map version (?P<save>\d+\.\d+\.\d+)-\d+ cannot be loaded because it is "
        r"higher than the game version \((?P<game>\d+\.\d+\.\d+)-\d+\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"Map version (?P<save>\d+\.\d+\.\d+)(?:-\d+)? cannot be loaded",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class Mismatch:
    save_version: str
    game_version: str | None

    def describe(self) -> str:
        if self.game_version:
            return (
                f"the save was made with Factorio {self.save_version} but the "
                f"installed client is {self.game_version}"
            )
        return f"the save was made with Factorio {self.save_version}"


def find(*texts: str) -> Mismatch | None:
    for text in texts:
        if not text:
            continue
        for pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                groups = match.groupdict()
                return Mismatch(
                    save_version=groups["save"],
                    game_version=groups.get("game"),
                )
    return None


def read_log(path: Path, limit: int = 256_000) -> str:
    """Tail factorio-current.log; it is the record that survives a crash."""
    try:
        size = path.stat().st_size
        with path.open("r", errors="replace") as handle:
            if size > limit:
                handle.seek(size - limit)
            return handle.read()
    except OSError as exc:
        log.debug("could not read %s: %s", path, exc)
        return ""
