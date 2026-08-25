"""Read-only checks performed before the desktop UI enables a live run."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import platform
from typing import Callable

import numpy as np

from auto_game_unified.core.window import Epic7Window
from auto_game_unified.games.epic7.modes import get_mode


class PreflightStatus(str, Enum):
    PASS = "通过"
    BLOCK = "阻止"


@dataclass(frozen=True)
class PreflightReport:
    status: PreflightStatus
    message: str
    screen_size: tuple[int, int] | None = None

    @property
    def can_start(self) -> bool:
        return self.status is PreflightStatus.PASS


def _probe_templates(mode: str, template_root: Path) -> None:
    spec = get_mode(mode)
    spec.build_machine(template_root, spec.default_state)


def run_preflight(
    *,
    mode: str,
    template_root: Path,
    window_factory: Callable[[], Epic7Window] = Epic7Window,
    template_probe: Callable[[str, Path], None] = _probe_templates,
    platform_name: str | None = None,
) -> PreflightReport:
    if (platform_name or platform.system()) != "Windows":
        return PreflightReport(PreflightStatus.BLOCK, "首版仅支持 64 位 Windows")

    try:
        template_probe(mode, template_root)
        screen = window_factory().capture()
        height, width = screen.shape[:2]
        if (width, height) != (1982, 1132):
            raise RuntimeError(
                f"画布尺寸异常：{width}x{height}，预期 1982x1132"
            )
        if float(np.asarray(screen).std()) < 1.0:
            raise RuntimeError("游戏截图为黑屏或纯色画面")
    except Exception as error:
        return PreflightReport(PreflightStatus.BLOCK, str(error))

    return PreflightReport(
        PreflightStatus.PASS,
        "雷电模拟器、截图和路线模板检查通过",
        (width, height),
    )
