"""支线刷新倒计时：**只读巡检**那一支（2026-11-12 用户要求）。

需求原话：「在所有的路线跑完的最后，额外跑一次这个支线路线，进入到这个页面看一下
它还有多长时间，把它记下来」。

两条铁律钉在这个文件里，改代码的人先读这两条再动手：

1. **只读**。``countdown_only=True`` 之后，状态机只许点两下 —— 支线故事页的
   「支线故事」标签、支线列表里普通条目的「入场」。地图 / 队伍 / 场景 / 战斗页上
   **一个动作都不许产出**：那上面任何一次点击都是「开始打图」，与"只是看一眼"相反。
   反向验证放在 ``test_countdown_mode_never_produces_a_click_on_any_other_page``，
   它**遍历整个夹具目录**，别改成只测一两张。
2. **读不到不猜**。Episode 详情页上 OCR 没读出「剩余 N 天 N 小时」就返回
   ``(True, None)``（这一页归我管、但不动手），靠状态超时收场 —— 绝不用上一帧、
   上一个页面或任何默认值顶替。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_game_unified.games.epic7 import side_story as side_story_module
from auto_game_unified.games.epic7.side_story import (
    SideStoryCountdownRead,
    build_side_story_machine,
    read_period_countdown,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_side_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "side_story"

_CACHE: dict[str, np.ndarray] = {}


def _load(path: Path) -> np.ndarray:
    key = str(path)
    if key not in _CACHE:
        raw = cv2.imread(key, cv2.IMREAD_COLOR)
        assert raw is not None, f"缺夹具 {path}"
        _CACHE[key] = cv2.cvtColor(raw[:1132, :1982], cv2.COLOR_BGR2RGB)
    return _CACHE[key]


def list_page() -> np.ndarray:
    """「可进入的支线故事」列表（2026-11-12 真机）。

    两条活动条目左下角有绿色「剩余 N 天」，最上面那条普通支线只有右下角「入场」
    ⇒ `enter_normal_sub_story` 应当挑中它（1842,767 一带）。
    """

    return _load(FIXTURES / "sub_story_list_live_20261112.png")


def episode_page() -> np.ndarray:
    """Episode 详情页（2026-11-12 真机）：左下角「剩余 13天 12小时」。"""

    return _load(FIXTURES / "episode_countdown_live_20261112.png")


def story_hub_page() -> np.ndarray:
    """支线故事页（旧的 `side_story.png`）：有「快速入场」+ 右上「支线故事」标签。"""

    return _load(FIXTURES / "side_story.png")


# 只读巡检**允许**动手的三页（各自的断言在下面单独写）。
_CHAIN_FIXTURES = frozenset(
    {
        "side_story.png",
        "sub_story_list_live_20261112.png",
        "episode_countdown_live_20261112.png",
    }
)


def _machine():
    return build_side_story_machine(TEMPLATES, countdown_only=True)


def _pc_machine():
    """PC 模板根（`templates/side_story/pc/` 里才有期次主页那两颗判据图）。

    模拟器侧它们必须是空元组 ⇒ 本函数只在「PC 专属中间页」那一条用例里用。
    """

    from auto_game_unified.games.epic7.template_paths import resolve_template_dir

    root = ROOT / "games" / "epic7" / "templates"
    return build_side_story_machine(
        resolve_template_dir(root, "pc") / "side_story", countdown_only=True
    )


class _StubOCR:
    """把 `read_period_countdown` 换成固定读数（不依赖可选依赖、也不烧 1.1 秒）。

    用上下文管理器而不是裸 monkeypatch：这些用例要在同一个用例里**多次**开关它
    （尤其遍历夹具那条），进出必须成对。
    """

    def __init__(self, payload):
        self.payload = payload
        self._original = None

    def __enter__(self):
        self._original = side_story_module.read_period_countdown
        side_story_module.read_period_countdown = lambda screen: self.payload
        return self

    def __exit__(self, *exc_info):
        side_story_module.read_period_countdown = self._original
        return False


# --------------------------------------------------------------------------
# ① 只读：不许在「会开始打图」的页面上产出动作
# --------------------------------------------------------------------------


def test_countdown_mode_goes_for_the_list_then_the_episode():
    """正路：支线故事页 → 点标签进列表 → 点普通支线的入场 → 到 Episode 详情。"""

    action = _machine().next_action(story_hub_page())
    assert action is not None
    assert action.name == "open_sub_story_list", (
        "只读巡检也必须走「标签 → 列表」这条新入口，"
        "不能退回「快速入场」（有活动时会被顶掉）"
    )
    assert action.source_page == "支线故事"

    action = _machine().next_action(list_page())
    assert action is not None
    assert action.name == "enter_normal_sub_story"
    assert action.source_page == "支线列表"


def test_countdown_page_raises_with_the_payload_and_stashes_it():
    """Episode 详情页读到了 ⇒ 抛 ``SideStoryCountdownRead`` 并留在账本上。

    为什么要「先记账再抛」：抛出去之后基类主循环只打一行日志就收工，没人能再把
    栈上的对象捞回来 —— 落盘靠调用方在 ``run()`` 返回后读 ``machine.countdown_read``。
    """

    payload = {"days": 13, "hours": 12, "raw": "剩余 13天 12小时"}
    machine = _machine()
    with _StubOCR(payload):
        with pytest.raises(SideStoryCountdownRead) as caught:
            machine.next_action(episode_page())

    assert caught.value.payload == payload
    assert "13" in str(caught.value) and "12" in str(caught.value)
    assert machine.countdown_read == payload


def test_countdown_page_without_readable_text_does_not_click():
    """读不到字 ⇒ 这一页归我管但不动手（不猜、不乱点）。"""

    machine = _machine()
    with _StubOCR(None):
        action = machine.next_action(episode_page())

    assert action is None
    assert machine.countdown_read is None


def test_countdown_mode_walks_the_pc_event_home_instead_of_getting_stuck():
    """PC 上点完「入场」先落「期次主页」，点「故事」才到 Episode 详情。

    不接这一步的话巡检在 PC 上永远停在期次主页等到超时 —— 而 ``side_story`` 是
    在 ``PC_READY_ROUTES`` 里的，那就是一条死代码。模拟器侧这两颗模板是空元组，
    本用例用 PC 模板根单独验。
    """

    action = _pc_machine().next_action(_load(FIXTURES / "event_home.png"))
    assert action is not None
    assert action.name == "enter_event_story"
    assert action.source_page == "期次主页"

    # 反证：模拟器口径下这一帧不归巡检管（也不归普通模式管），不会点任何东西。
    with _StubOCR(None):
        assert _machine().next_action(_load(FIXTURES / "event_home.png")) is None


def test_countdown_mode_never_produces_a_click_on_any_other_page():
    """**反向验证**：除那三页之外，夹具目录里的每一帧都不许产出动作。

    这是「只读」这条铁律唯一的机器守卫。地图帧上普通模式会给 ``pick_stage``、
    队伍页给 ``start_mission``、场景页给 ``advance_stage`` —— 只读巡检一个都不能给。
    """

    machine = _machine()
    checked = 0
    with _StubOCR(None):
        for path in sorted(FIXTURES.glob("*.png")):
            if path.name in _CHAIN_FIXTURES:
                continue
            action = machine.next_action(_load(path))
            assert action is None, (
                f"{path.name} 上产出了动作 {getattr(action, 'name', action)!r}；"
                "只读巡检不许在任何会开始打图的页面上点东西"
            )
            checked += 1

    assert checked >= 20, "夹具目录没扫全，这条反向验证等于没跑"


# --------------------------------------------------------------------------
# ② OCR：真跑一次（缺可选依赖就跳过，不让它变成假绿灯）
# --------------------------------------------------------------------------

_NEEDS_OCR = pytest.mark.skipif(
    importlib.util.find_spec("rapidocr_onnxruntime") is None,
    reason="没装可选的 OCR 依赖（rapidocr-onnxruntime）",
)


@_NEEDS_OCR
def test_real_ocr_reads_the_live_frame():
    """真机帧上确实能读出「剩余 13天 12小时」（这一行字只有约 24px 高）。"""

    payload = read_period_countdown(episode_page())
    assert payload is not None, "这一帧读不出倒计时 —— 换过模板 / 改过裁切区域？"
    assert payload["days"] == 13
    assert payload["hours"] == 12
    assert "13" in payload["raw"]


@_NEEDS_OCR
def test_ocr_returns_none_on_a_page_without_the_line():
    """列表页没有那行字 ⇒ 必须返回 None（判据不能"什么都能读出个东西"）。"""

    assert read_period_countdown(list_page()) is None


# --------------------------------------------------------------------------
# ③ 账本：同一帧只跑一次 OCR，换帧必须重读
# --------------------------------------------------------------------------


def test_same_frame_only_runs_ocr_once():
    """主循环对一帧会问两遍（preview 一遍、next_action 一遍），OCR 单次约 1.1 秒。

    不缓存就白烧一倍时间；缓存到**下一帧**又会把上一页的读数当成这一页的。
    """

    machine = _machine()
    calls: list[int] = []

    def counting(screen):
        calls.append(1)
        return {"days": 3, "hours": 4, "raw": "剩余 3天 4小时"}

    original = side_story_module.read_period_countdown
    side_story_module.read_period_countdown = counting
    try:
        frame = episode_page()
        # preview 也会抛（它跑的就是同一个 next_action），结论门槛靠的是它的重复次数。
        with pytest.raises(SideStoryCountdownRead):
            machine.preview(frame)
        with pytest.raises(SideStoryCountdownRead):
            machine.next_action(frame)
        assert len(calls) == 1, "同一帧被 OCR 了两遍"

        # 换一帧（即便像素一模一样，也是另一个对象）必须重新读。
        with pytest.raises(SideStoryCountdownRead):
            machine.next_action(episode_page().copy())
    finally:
        side_story_module.read_period_countdown = original

    assert len(calls) == 2


def test_normal_mode_is_untouched_by_the_countdown_branch():
    """不打开开关时行为一个字节都不变（Episode 详情页照旧点「冒险」）。"""

    action = build_side_story_machine(TEMPLATES).next_action(episode_page())
    assert action is not None
    assert action.name == "enter_adventure"
