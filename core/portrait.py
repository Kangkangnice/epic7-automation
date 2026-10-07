"""竖屏通道：游戏内 H5（骑士团/社区那类网页）会把模拟器整块切成竖屏。

## 为什么必须有它（2026-10-06 实测）

进「游戏社区」后模拟器变成竖屏，安卓侧 ``dumpsys display`` 显示
``mOverrideDisplayInfo ... real 1080 x 1920, rotation 3``，窗口客户区也从
1920x1080 变成 1103x1899。此时横屏那套 ``Epic7Window.capture()`` **直接抛错**：

    RuntimeError: LDPlayer render size changed: 1023x1820; expected 1920x1080

也就是说整个「PrintWindow 取图 → 1982x1132 画布 → 模板匹配 → 画布坐标点击」
的链路在竖屏下**一步都走不了**。所以竖屏段另开一条通道，与横屏彻底隔离。

## 这条通道怎么工作

- **取图**：走模拟器自己的截图 ``shell screencap -p`` + ``pull``，拿到的是
  **安卓原始画面**（竖屏时就是 1080x1920），既没有雷电顶栏/右侧工具栏，
  也不需要缩放 —— 它**就是**点击坐标所在的坐标系，两边天然对齐。
- **点击**：``shell input tap x y``，坐标直接用标准画布坐标，不做任何换算。
- **方向判定**：只看窗口客户区宽高比（宽 < 高 ⇒ 竖屏）。比问 ``dumpsys`` 便宜得多
  （那要 1~2 秒），而我们只需要「转过去了没有」这一个比特。

## 与横屏的分工（重要）

本模块**不替换**横屏任何东西：横屏段照旧走 ``Epic7Window`` + ``Runtime``。
它只在「社区网页打开着」这段时间里被路线拿来取图/点击，社区关掉就交还横屏。
"""

from __future__ import annotations

import ctypes
import subprocess
import tempfile
from ctypes import wintypes
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.window import Epic7Window

# 竖屏标准画布 = 安卓逻辑分辨率（rotation=3 时的 logicalFrame）。
# 取到的截图必须是这个尺寸；不是就说明「模拟器还没转过去」或「转回去了」，
# 一律当场报错 —— 把错帧喂给状态机会判出莫名其妙的结果，比停下来难查得多。
PORTRAIT_CANVAS = (1080, 1920)

# 设备内的截图落点（每帧覆写，不留垃圾）。
_DEVICE_SHOT = "/sdcard/_auto_game_portrait.png"

# 方向切换后的**有界等待**：旋转是带动画的，点完「游戏社区」后窗口要一两秒才竖过来。
# 每次轮询 0.25 秒；默认最多等 20 秒（实测切换在 3 秒内完成，留足余量）。
_POLL_SECONDS = 0.25
_DEFAULT_ORIENTATION_TIMEOUT = 20.0

# 「窗口已转竖屏、但安卓侧画面还没切成 1080x1920」这一小段的**有界等待**。
#
# ⚠️ 2026-10-07 加：转屏是**两步**（先转窗口、再由安卓 rotation 生效），
# 中间那一瞬方向已对、画幅还没跟上。旧代码直接报错，上层兜底「退回横屏」——
# 而那一刻窗口**已经是竖屏**了，于是拿竖屏图撞横屏模板，主循环 3 秒后
# 进失败收尾，**把刚打开的社区又关掉**（实跑日志 12:45:02 → 12:45:05）。
#
# 4 次 × 0.75 秒 ≈ 3 秒，够覆盖实测那次的中断；超了才当异常，往上抛。
_CANVAS_SETTLE_ATTEMPTS = 4
_CANVAS_SETTLE_SECONDS = 0.75


class OrientationError(RuntimeError):
    """窗口方向与预期不符（多半是旋转动画还没走完，或者根本没转）。

    单独一个类型是为了让上层能区分「方向不对」和「截图命令本身失败」——
    前者等一等就好，后者等多久都没用。
    """


class PortraitChannel:
    """竖屏取图 / 点击通道。

    ``window`` 传进来是为了复用「找到唯一那个雷电窗口 + 实例序号 + 窗口句柄」
    这套发现逻辑（见 ``Epic7Window.instance_channel``）；传 ``None`` 就自己建一个。
    """

    def __init__(
        self,
        window: Optional[Epic7Window] = None,
        *,
        sleep: Callable[[float], None] = default_sleep,
        adb_timeout: float = 20.0,
        orientation_timeout: float = _DEFAULT_ORIENTATION_TIMEOUT,
        shot_path: Optional[Path] = None,
    ) -> None:
        self._window = window if window is not None else Epic7Window()
        self._sleep = sleep
        self._adb_timeout = adb_timeout
        self._orientation_timeout = orientation_timeout
        # 拉回的本地文件。给测试留一个可注入的口子（免得真去写系统临时目录）。
        self._shot_path = shot_path or (
            Path(tempfile.gettempdir()) / "auto_game_portrait_shot.png"
        )
        self._event_sink: Optional[Callable[[str], None]] = None

    # ── 日志出口（与 Epic7Window 同形：装在 runtime.log 上） ────────────────

    def set_event_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        self._event_sink = sink

    def _emit(self, message: str) -> None:
        if self._event_sink is not None:
            self._event_sink(message)

    # ── 方向 ────────────────────────────────────────────────────────────────

    def client_size(self) -> tuple[int, int]:
        """窗口**客户区**尺寸（不是窗口外框）。

        ⚠️ 客户区包含雷电自己的顶栏与右侧工具栏，所以竖屏时它是 1103x1899 而不是
        1080x1920 —— 但这不影响判定：我们只问「宽高哪个大」。
        """
        _, _, handle = self._window.instance_channel()
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(handle, ctypes.byref(rect)):
            raise OrientationError(f"读不到模拟器客户区尺寸（窗口句柄 {handle}）")
        return rect.right - rect.left, rect.bottom - rect.top

    def is_portrait(self) -> bool:
        width, height = self.client_size()
        return width < height

    def wait_for_portrait(self, timeout: Optional[float] = None) -> None:
        """等模拟器转成竖屏；超时抛 ``OrientationError``（带当前实际尺寸）。"""
        self._wait_for(portrait=True, timeout=timeout)

    def wait_for_landscape(self, timeout: Optional[float] = None) -> None:
        """等模拟器转回横屏；超时抛 ``OrientationError``。"""
        self._wait_for(portrait=False, timeout=timeout)

    def _wait_for(self, *, portrait: bool, timeout: Optional[float]) -> None:
        budget = self._orientation_timeout if timeout is None else timeout
        expected = "竖屏" if portrait else "横屏"
        size = self.client_size()
        if (size[0] < size[1]) is portrait:
            return
        self._emit(
            f"竖屏通道 方向=等待切换为{expected} 当前客户区={size[0]}x{size[1]} "
            f"最长等待={budget:.0f}秒"
        )
        elapsed = 0.0
        while elapsed < budget:
            self._sleep(_POLL_SECONDS)
            elapsed += _POLL_SECONDS
            size = self.client_size()
            if (size[0] < size[1]) is portrait:
                self._emit(
                    f"竖屏通道 方向=已切换为{expected} 客户区={size[0]}x{size[1]} "
                    f"等待={elapsed:.1f}秒"
                )
                return
        raise OrientationError(
            f"等待模拟器切成{expected}超时（已等 {elapsed:.1f} 秒）；"
            f"当前客户区={size[0]}x{size[1]}"
        )

    # ── 取图 ────────────────────────────────────────────────────────────────

    def capture(self) -> np.ndarray:
        """抓一帧竖屏画面，返回 RGB 的 ``1080x1920``（= 点击坐标系）。

        要求窗口此刻确实是竖屏；不是就先等一会儿（旋转动画常见一两秒），
        等不到再报错 —— 绝不把横屏帧当竖屏帧交出去。

        ## ⚠️⚠️ 为什么「方向对但画幅不对」要**继续等**，而不是报错（2026-10-07 修）

        转屏是**分两步**的：先转**窗口**（客户区宽高比翻转），再由安卓侧
        ``rotation`` 生效、``screencap`` 吐出新尺寸的图。这两步**不是同时**的 ——
        中间那一瞬，窗口已经是竖屏、截图却还是旧的横屏尺寸。

        旧代码在这里直接抛 ``OrientationError``，上层的兜底是
        「退回横屏重试入口点击」⇒ **在窗口已经转成竖屏的时刻退回横屏**，
        拿竖屏画面去撞横屏模板 ⇒ `画面宽高比与模板基准不一致`；
        而主循环接着判不出页面、3 秒后进失败收尾，**把刚打开的社区又关掉了**。
        实跑日志 12:45:02 点入口 → 12:45:05 就「收尾=人还在社区竖屏页面里」。

        ⇒ 所以这里改成：**方向已经对了、只是画幅还没跟上 ⇒ 继续等**
        （上限 ``_CANVAS_SETTLE_ATTEMPTS`` 次），只有「等完还是不对」才抛。
        """
        self.wait_for_portrait()
        last = ""
        for attempt in range(1, _CANVAS_SETTLE_ATTEMPTS + 1):
            image = self._screencap()
            height, width = image.shape[:2]
            if (width, height) == PORTRAIT_CANVAS:
                return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            last = f"{width}x{height}"
            self._emit(
                f"竖屏通道 取图=画幅还没跟上 期望={PORTRAIT_CANVAS[0]}x"
                f"{PORTRAIT_CANVAS[1]} 实际={last} 尝试={attempt}/"
                f"{_CANVAS_SETTLE_ATTEMPTS} 处理=继续等"
            )
            if attempt < _CANVAS_SETTLE_ATTEMPTS:
                self._sleep(_CANVAS_SETTLE_SECONDS)
        # ⚠️ **必须抛 ``OrientationError``，不能抛裸 ``RuntimeError``**（2026-10-07 修）。
        # 上层 ``attach_dual_channel.capture`` 靠 ``except OrientationError``
        # 判「等不到转屏 ⇒ 退回横屏重试入口点击」。抛裸 RuntimeError 会被漏过，
        # 一路冒到主循环 ⇒ 整条路线崩掉（10:51 实跑：点完 2 秒就崩，日志里
        # 紧跟着「收尾=人还在社区竖屏页面里」—— 方向明明已经变了，代码却
        # 以为自己还在等，于是走了失败收尾）。
        raise OrientationError(
            f"竖屏截图尺寸不对：{last}，应为 "
            f"{PORTRAIT_CANVAS[0]}x{PORTRAIT_CANVAS[1]}（已等 "
            f"{_CANVAS_SETTLE_ATTEMPTS} 次）；"
            "方向已转成竖屏但安卓侧画面还没切成 1080x1920，"
            "或社区页已关掉、方向又转回去了"
        )

    def _screencap(self) -> np.ndarray:
        """抓一张安卓原始截图（BGR，未校验尺寸）。"""
        self._run_adb(f"shell screencap -p {_DEVICE_SHOT}")
        self._run_adb(f"pull {_DEVICE_SHOT} {self._shot_path}")
        image = cv2.imread(str(self._shot_path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"竖屏截图读不出来：{self._shot_path}")
        return image

    # ── 输入 ────────────────────────────────────────────────────────────────

    def click(self, point: tuple[int, int]) -> None:
        """按标准画布坐标点击（与 ``capture`` 同一坐标系，无需换算）。"""
        width, height = PORTRAIT_CANVAS
        if not (0 <= point[0] < width and 0 <= point[1] < height):
            raise RuntimeError(f"拒绝在竖屏画布外点击：{point}")
        self._run_adb(f"shell input tap {point[0]} {point[1]}")

    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        if duration_ms <= 0:
            raise ValueError("滑动时长必须大于 0")
        self._run_adb(
            f"shell input swipe {start[0]} {start[1]} {end[0]} {end[1]} {duration_ms}"
        )

    def back(self) -> None:
        """安卓返回键。

        ⚠️ 实测（2026-10-06）社区那几页对返回键的响应**不一致**：帖子详情/兑换中心
        能退，「我的任务」页按了没反应。所以路线里优先点界面上的「X」，
        返回键只当兜底。
        """
        self._run_adb("shell input keyevent 4")

    # ── adb 底座 ────────────────────────────────────────────────────────────

    def _run_adb(self, command: str) -> bytes:
        console_path, instance_index, _ = self._window.instance_channel()
        result = subprocess.run(
            [str(console_path), "adb", "--index", instance_index, "--command", command],
            check=True,
            capture_output=True,
            timeout=self._adb_timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = b"".join(
            bytes(stream)
            for stream in (result.stdout, result.stderr)
            if isinstance(stream, (bytes, bytearray))
        )
        # ⚠️ 雷电控制台**所有**出错情况都返回退出码 0，只把错误写进输出
        # （2026-09-24 实测四条，见 Epic7Window._INPUT_FAILURE_MARKERS 的注释）
        # ⇒ ``check=True`` 对它无效，必须显式看内容。标记表直接复用横屏那一份：
        # 同一件事不要有两份判据。
        lowered = output.lower()
        if any(
            marker in lowered for marker in Epic7Window._INPUT_FAILURE_MARKERS
        ):
            raise RuntimeError(
                f"竖屏通道指令未送达（{command}）："
                + output.decode("utf-8", "replace").strip()
            )
        return output
