"""Render state, persisted so restarts do not re-render an unchanged save."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import STATE_FILE
from .log import log


@dataclass
class State:
    save_name: str = ""
    save_sha256: str = ""
    factorio_version: str = ""
    output_path: str = ""
    rendered_at: str = ""

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> State:
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("state file %s unreadable (%s), starting fresh", path, exc)
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path = STATE_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(asdict(self), handle, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
