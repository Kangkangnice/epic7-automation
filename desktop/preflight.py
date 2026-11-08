"""Read-only checks performed before the desktop UI enables a live run."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import platform
from typing import Callable

import numpy as np

from auto_game_unified.core.elevation import privilege_warning_for
from auto_game_unified.core.pc_window import Epic7PcWindow
from auto_game_unified.core.window import Epic7Window
from auto_game_unified.games.epic7.modes import get_mode
from auto_game_unified.games.epic7.template_paths import (
    TemplateDir,
    resolve_template_dir,
)


class PreflightStatus(str, Enum):
    PASS = "通过"
    BLOCK = "阻止"


@dataclass(frozen=True)
class PreflightReport:
    status: PreflightStatus
    message: str
    screen_size: tuple[int, int] | None = None
    #: 「能跑，但大概率点不动」的提示（目前只有一种：模拟器权限比本程序高，
    #: 点击会被 UIPI 拦掉）。**它不影响 ``can_start``** —— 检测是通过的，
    #: 只是需要用户以管理员身份重启一次。空字符串与 None 都表示没有提示。
    warning: str | None = None

    @property
    def can_start(self) -> bool:
        return self.status is PreflightStatus.PASS


def template_root_for_backend(
    template_root: Path, window_backend: str
) -> Path | TemplateDir:
    """开始前复检必须使用与**实跑完全相同**的模板根。

    ``main.py`` 实跑时是 ``resolve_template_dir(ROOT/templates, window_backend)``：
    PC 后端下 ``root / "achievement" / "claim_all.png"`` 会自动优先取
    ``achievement/pc/claim_all.png``。复检若直接传普通 ``Path``，``is_pc()``
    恒为假，只会去找共享层的 ``achievement/claim_all.png`` —— 成就领取是第一条
    **只有 PC 素材**的路线，于是被误报「缺图」（文件其实就在 pc/ 下）。

    模拟器后端保持原样传 ``Path``：普通 Path 本来就是模拟器口径，也不会改动
    现有桌面测试里对 template_root 的断言。
    """
    if window_backend == "pc":
        return resolve_template_dir(template_root, window_backend)
    return template_root


def _probe_templates(mode: str, template_root: Path) -> None:
    spec = get_mode(mode)
    spec.build_machine(template_root, spec.default_state)


def validate_route_templates(
    mode: str,
    template_root: Path,
    *,
    template_probe: Callable[[str, Path], None] = _probe_templates,
) -> None:
    template_probe(mode, template_root)


def _probe_pc(window: Epic7PcWindow) -> PreflightReport:
    """检查 PC 客户端：窗口尺寸校准、权限一致性、兼容画布和画面有效性。"""

    try:
        calibration = window.ensure_render_size()
    except Exception as error:
        return PreflightReport(PreflightStatus.BLOCK, f"PC 客户端检查未通过：{error}")

    try:
        screen = window.capture()
    except Exception as error:
        return PreflightReport(PreflightStatus.BLOCK, f"PC 截图失败：{error}")

    height, width = screen.shape[:2]
    if (width, height) != (1982, 1132):
        return PreflightReport(
            PreflightStatus.BLOCK,
            f"PC 画布尺寸异常：{width}x{height}，预期 1982x1132",
        )
    if float(np.asarray(screen).std()) < 1.0:
        return PreflightReport(PreflightStatus.BLOCK, "游戏截图为黑屏或纯色画面")

    return PreflightReport(
        PreflightStatus.PASS,
        f"PC 客户端检查通过：客户区 {calibration.after.width}x{calibration.after.height}",
        (width, height),
    )


def run_preflight(
    *,
    window_backend: str = "emulator",
    window_factory: Callable[[], Epic7Window] = Epic7Window,
    pc_window_factory: Callable[[], Epic7PcWindow] = Epic7PcWindow,
    platform_name: str | None = None,
) -> PreflightReport:
    if (platform_name or platform.system()) != "Windows":
        return PreflightReport(PreflightStatus.BLOCK, "首版仅支持 64 位 Windows")

    if window_backend == "pc":
        return _probe_pc(pc_window_factory())

    # PC 后端不查提权：它只用于采集模板与开发验证，而且 PC 客户端本身要求以管理员
    # 身份运行助手（见 app.STARTUP_HINTS），提示「请以管理员重启」是废话。
    probe: Epic7Window | None = None
    try:
        probe = window_factory()
        screen = probe.capture()
        height, width = screen.shape[:2]
        if (width, height) != (1982, 1132):
            raise RuntimeError(
                f"画布尺寸异常：{width}x{height}，预期 1982x1132"
            )
        if float(np.asarray(screen).std()) < 1.0:
            raise RuntimeError("游戏截图为黑屏或纯色画面")
    except Exception as error:
        return PreflightReport(PreflightStatus.BLOCK, str(error))

    # 截图能过、点击未必能过：模拟器若以管理员启动，输入会被 UIPI 静默拦掉。
    # 这一步只提示、不阻断 —— 检测本身是成功的，见 PreflightReport.warning。
    warning = privilege_warning_for(probe) if probe is not None else None
    return PreflightReport(
        PreflightStatus.PASS,
        "雷电模拟器和截图检查通过",
        (width, height),
        warning=warning,
    )
