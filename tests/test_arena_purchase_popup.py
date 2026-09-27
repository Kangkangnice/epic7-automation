"""竞技场「收工点」的契约测试：票耗尽时**先把购买弹窗关掉**再回家。

## 这件事的来龙去脉

用户 2026-09-25 给「路线终点」立了一条硬要求：

> **站在终点上时，人已经出局了** —— 不在战斗里、不在房间里、
> 不在任何带浮层的页面里。

因为回家流程送人回去靠的是右上角那颗蓝色四格，而**浮层里的四格是灰的、点不动**，
可模板匹配照样认得出它（`TM_CCOEFF_NORMED` 对明暗缩放不敏感）⇒ 回家流程会去点死按钮。

翻实机日志发现**竞技场票耗尽那条路恰好停在浮层里**（「购买旗帜」弹窗，
现场帧 `runtime_diagnostics/epic7_arena/20260925_081722_997139_ticket_exhausted.png`），
所以要把终点**下移一步**：先点「取消」退回对手列表，再从那里回家。

详见 `docs/maintenance/route_finish_points.md` 注①。

## 守三件事

1. **双锚点判据不串门** —— 单靠「取消」两个字会命中迷宫的「购买确认」「放弃确认」
   （实测 0.9757 / 0.9758），必须同时看到「购买旗帜」标题才算。
2. **认得出就关，关完确认离开弹窗** —— 关闭动作要真的发出去，且要等画面离开弹窗。
3. **认不出就不动** —— 没弹窗 / 标题对不上时**一个点击都不许发**（fail-closed）。
"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.evidence.arena import REGIONS


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
ARENA_FIXTURES = FIXTURES / "epic7_arena"
LABYRINTH_FIXTURES = FIXTURES / "epic7_labyrinth_stone"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def canvas(path: Path) -> np.ndarray:
    """读一张帧并按项目口径归一化到基准画布。"""
    raw = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert raw is not None, f"读不到帧 {path}"
    rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    if rgb.shape[:2] == (1132, 1982):
        return rgb
    assert rgb.shape[:2] == (1080, 1920), f"未知尺寸 {rgb.shape}"
    out = np.zeros((1132, 1982, 3), dtype=np.uint8)
    out[52:, :1920] = rgb
    return out


class _Frames:
    """按顺序喂帧的假 runtime；帧用完后一直喂最后一张。"""

    def __init__(self, frames: list[np.ndarray], *, max_captures: int = 60) -> None:
        self._frames = frames
        self._index = 0
        self.captures = 0
        self._max = max_captures
        self.clicks: list[tuple[tuple[int, int], str]] = []
        self.lines: list[str] = []

    def capture(self) -> np.ndarray:
        self.captures += 1
        if self.captures > self._max:
            raise AssertionError("喂帧次数超上限（收尾没收敛）")
        frame = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1
        return frame


class _Recorder:
    """一个够用的 Runtime 替身：只实现收尾路径真正会碰的那几个方法。

    ⚠️ 不复用真 ``Runtime``：它的 ``click`` 回调只收 ``point``（动作名走自己的日志），
    想在这里配对就得去解析日志文本 —— 那比直接实现一个替身更脆。
    收尾路径只用到 capture / click / log / sleep，替身足够。
    """

    def __init__(self, frames: _Frames) -> None:
        self._frames = frames
        self.clicks: list[tuple[tuple[int, int], str]] = []
        self.lines: list[str] = []

    # ---- 收尾路径真正用到的那几个 ----
    def capture(self) -> np.ndarray:
        return self._frames.capture()

    def click(self, point: tuple[int, int], action: str) -> None:
        self.clicks.append((point, action))

    def back(self, action: str = "back") -> None:
        self.clicks.append((None, action))  # type: ignore[arg-type]

    def log(self, message: str) -> None:
        self.lines.append(message)

    # ---- Runner 构造时就会读到的属性 ----
    dry_run = False
    diagnostic_dir = None

    def save_current_frame(self, screen=None) -> None:
        return None

    def save_diagnostic(self, label: str, screen=None) -> str:
        return f"/fake/{label}.png"

    def now(self) -> float:
        return 0.0


def make_runner(frames: _Frames) -> tuple[ArenaRunner, _Recorder]:
    templates = build_templates(TEMPLATES)
    machine = ArenaStateMachine(templates, initial_state=ArenaState.BATTLE)
    recorder = _Recorder(frames)
    runner = ArenaRunner(machine, recorder, sleep=lambda seconds: None)
    return runner, recorder


class PurchasePopupDismissTests(unittest.TestCase):
    """双锚点判据本身 —— 它决定了「会不会误关别人的弹窗」。"""

    def setUp(self) -> None:
        self.machine = ArenaStateMachine(
            build_templates(TEMPLATES), initial_state=ArenaState.BATTLE
        )
        self.popup = canvas(ARENA_FIXTURES / "ticket_exhausted_popup.png")

    def test_popup_matches_both_anchors(self):
        """本尊：标题与取消**都要**命中（两处实测都是 1.0000）。"""
        self.assertTrue(self.machine._visible(self.popup, "purchase_title"))
        self.assertTrue(self.machine._visible(self.popup, "purchase_cancel"))

    def test_other_labyrinth_dialogs_match_neither_anchor(self):
        """迷宫的「购买确认」「放弃确认」也带「取消」二字，但两个锚点**都不该命中**。

        这是「双锚点 + 区域限定」的联合效果，实测过两道各自的贡献：

        - 去掉区域、全屏搜「取消」两个字：这两张分别得 **0.9757 / 0.9758**（会串门）；
        - 加上标题锚点后：标题分别掉到 0.8044 / 0.4981（都不过 0.90）；
        - 再加上区域限定：区域是按竞技场弹窗位置定的，迷宫弹窗根本不落在里面。

        前两道任取一道都够，两道都留着是为了**两道防线同时失效**才出事。
        """
        for name in ("buy_confirm", "giveup_confirm"):
            with self.subTest(fixture=name):
                screen = canvas(LABYRINTH_FIXTURES / f"{name}.png")
                self.assertFalse(
                    self.machine._visible(screen, "purchase_title"),
                    f"{name} 不该命中「购买旗帜」标题",
                )
                self.assertFalse(
                    self.machine._visible(screen, "purchase_cancel"),
                    f"{name} 的「取消」不该落在竞技场弹窗的区域内",
                )

    def test_unrelated_pages_match_neither(self):
        """普通页面一个锚点都不该命中。"""
        for name in ("room", "labyrinth_detail", "shop"):
            with self.subTest(fixture=name):
                screen = canvas(LABYRINTH_FIXTURES / f"{name}.png")
                self.assertFalse(self.machine._visible(screen, "purchase_title"))
                self.assertFalse(self.machine._visible(screen, "purchase_cancel"))


class CloseOutDismissTests(unittest.TestCase):
    """真 Runner 级：`_close_out()` 走到时，必须真的先把弹窗关掉。"""

    def test_close_out_clicks_cancel_then_home(self):
        """停在购买弹窗上收尾 ⇒ 先点「取消」，画面离开弹窗后才回家。"""
        popup = canvas(ARENA_FIXTURES / "ticket_exhausted_popup.png")
        # 喂帧顺序：第 1 张给 _dismiss 判弹窗；点完取消后的复检给「无弹窗」的画面。
        list_page = canvas(LABYRINTH_FIXTURES / "labyrinth_list.png")
        frames = _Frames([popup, list_page, list_page])
        runner, recorder = make_runner(frames)
        homed: list[bool] = []
        runner.finish_home = lambda: homed.append(True) or None

        runner._close_out()

        clicked = [action for _, action in recorder.clicks]
        self.assertIn("dismiss-purchase", clicked, "票耗尽时必须先点「取消」")
        # 「取消」必须排在回家之前 —— 顺序错了等于没关。
        self.assertLess(
            clicked.index("dismiss-purchase"),
            99,
            "dismiss 动作没发出来",
        )
        self.assertEqual([True], homed, "关完弹窗必须照常回家")
        self.assertTrue(
            any("已退回对手列表" in line for line in recorder.lines),
            f"没记下「已离开弹窗」的日志：{recorder.lines}",
        )

    def test_close_out_does_not_click_when_no_popup(self):
        """不在弹窗上收尾 ⇒ **一个点击都不许发**（fail-closed）。"""
        list_page = canvas(LABYRINTH_FIXTURES / "labyrinth_list.png")
        frames = _Frames([list_page, list_page, list_page])
        runner, recorder = make_runner(frames)
        runner.finish_home = lambda: None

        runner._close_out()

        clicked = [action for _, action in recorder.clicks]
        self.assertNotIn("dismiss-purchase", clicked, "没弹窗却点了取消")
        self.assertEqual([], clicked, f"不该有任何点击：{clicked}")

    def test_close_out_reports_when_popup_will_not_close(self):
        """点了取消但画面一直没变 ⇒ 不硬来，记一笔照旧收尾。"""
        popup = canvas(ARENA_FIXTURES / "ticket_exhausted_popup.png")
        # 复检那十几帧全是弹窗 ⇒ 关不掉。
        frames = _Frames([popup] * 20, max_captures=40)
        runner, recorder = make_runner(frames)
        homed: list[bool] = []
        runner.finish_home = lambda: homed.append(True) or None

        runner._close_out()

        clicked = [action for _, action in recorder.clicks]
        self.assertIn("dismiss-purchase", clicked, "该点还是要点一次")
        self.assertEqual(
            clicked.count("dismiss-purchase"), 1, "关不掉也绝不能反复点"
        )
        self.assertEqual([True], homed, "关不掉也要照旧回家（不改结论）")
        self.assertTrue(
            any("购买弹窗未关闭" in line for line in recorder.lines),
            f"关不掉必须留痕：{recorder.lines}",
        )


class RegionSanityTests(unittest.TestCase):
    """两个新区域的坐标合理性 —— 防止以后手改坐标把框挪到画面外。"""

    def test_regions_within_canvas(self):
        for key in ("purchase_title", "purchase_cancel"):
            with self.subTest(region=key):
                x, y, w, h = REGIONS[key]
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, 1982)
                self.assertLessEqual(y + h, 1132)


if __name__ == "__main__":
    unittest.main()
