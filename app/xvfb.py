"""Virtual X server wrapper.

Factorio needs a real X server to render; there is no headless rendering path.
`-a` picks a free display number so a leftover lock file cannot wedge us, and
the screen is forced to 24-bit because some defaults are 8-bit, which breaks GL.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

SCREEN = os.environ.get("XVFB_SCREEN", "1280x1024x24")


def wrap(cmd: Sequence[str | Path]) -> list[str]:
    return [
        "xvfb-run",
        "-a",
        "--server-args",
        f"-screen 0 {SCREEN} -nolisten tcp",
        *(str(part) for part in cmd),
    ]


def env() -> dict[str, str]:
    """Environment for a software-rendered Factorio.

    Measured on this image (Debian trixie, Mesa 25.0.7): llvmpipe is selected
    on its own and reports GL 4.5 core with direct rendering, so neither of
    these is strictly required. They are set anyway to pin the choice if a GPU
    device ever shows up in the container. MESA_LOADER_DRIVER_OVERRIDE is
    deliberately not set: Mesa 25 ships one libdril_dri.so behind per-driver
    symlinks, and naming a driver that has no matching file breaks the loader.
    """
    merged = dict(os.environ)
    merged.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    merged.setdefault("GALLIUM_DRIVER", "llvmpipe")
    return merged
