"""接力契约的门槛测试 —— 三条卡点各守一条。

**转场契约**管「跑起来之后每个动作有没有出口验收」（`runner_base._require_transition_contract`）；
**接力契约**管「开局时人停在半路能不能接上」。两者互相独立，规矩见
`docs/TRANSITION_CONTRACTS.md`「接力契约」。

| 卡点 | 守在哪 |
|---|---|
| ① 表上必须表态 | 本文件（`RESUME_EXEMPT` 与 `resume_probe` 必须二选一）+ `modes.py` 的加载期自查 |
| ② 接线必须真通 | `main.py::_enter_mode` 校验 `_ResumeWatch.asked > 0`（本文件用替身 navigator 钉住「吃掉探针必须报错」） |
| ③ 判据必须真认得准（且命中后状态机真被拨对） | 本文件拿每条路线**自己的夹具**跑**注册好的探针**（`spec.resume_probe`） |

⚠️ 跨路线负例扫描（全库夹具取最高分）**不进门槛**：227 张要跑约半分钟，跟实跑抢内存。
它留在 `runtime_logs/_audit_*_cross_route.py`，结论写进 `docs/RESUME_COVERAGE.md`。
"""

from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from auto_game_unified import main as main_module
from auto_game_unified.games.epic7.modes import (
    MODE_SPECS,
    PC_ONLY_ROUTES,
    RESUME_EXEMPT,
    get_mode,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
COVERAGE_DOC = ROOT / "docs" / "RESUME_COVERAGE.md"

REFERENCE_WIDTH, REFERENCE_HEIGHT = 1982, 1132

NAVIGATED_MODES = tuple(
    sorted(name for name, spec in MODE_SPECS.items() if spec.needs_navigation)
)
PROBE_MODES = tuple(
    sorted(name for name, spec in MODE_SPECS.items() if spec.resume_probe is not None)
)


# ---- ① 表上必须表态 ----


@pytest.mark.parametrize("name", NAVIGATED_MODES)
def test_every_navigated_route_declares_its_resume_stance(name: str):
    """有导航的路线，要么挂探针，要么在豁免名单里写明理由 —— 不许「一个字不提」。"""

    spec = MODE_SPECS[name]

    assert spec.resume_probe is not None or name in RESUME_EXEMPT, (
        f"路线 {name} 既没挂接力探针，也没在 RESUME_EXEMPT 里写明理由"
    )
    assert not (spec.resume_probe is not None and name in RESUME_EXEMPT), (
        f"路线 {name} 两边都写了：挂了探针就该从豁免名单里划掉"
    )


def test_the_exemption_list_has_no_stale_names_and_no_empty_reasons():
    for name, reason in RESUME_EXEMPT.items():
        assert name in MODE_SPECS, f"豁免名单里的 {name} 不是一条路线（改名了吧？）"
        assert reason.strip(), f"{name} 的豁免理由不能空着"


def test_routes_without_navigation_are_exempt_automatically():
    """起点本来就是人工推进到活动内部：连「回大厅」这条路径都没有，谈不上接力。

    它们**不该**出现在豁免名单里 —— 那会把「没有这条路」和「有路但没做」混成一种。
    """

    without_navigation = [
        name for name, spec in MODE_SPECS.items() if not spec.needs_navigation
    ]

    assert without_navigation, "一条 needs_navigation=False 的路线都没有，这张测试该删了"
    for name in without_navigation:
        assert MODE_SPECS[name].resume_probe is None
        assert name not in RESUME_EXEMPT


def test_at_least_one_route_actually_resumes():
    """反向护栏：别把「全都豁免」当成通过。"""

    assert PROBE_MODES, "一条挂接力探针的路线都没有 —— 接力契约被架空了"


# ---- ② 接线必须真通 ----

BLANK_FRAME = np.zeros((REFERENCE_HEIGHT, REFERENCE_WIDTH, 3), dtype=np.uint8)


def _story_machine():
    spec = get_mode("story")
    return spec, spec.build_machine(TEMPLATE_ROOT, spec.default_state)


def _legacy_home_return(navigator):
    """造一个「照旧转发给导航器」的回大厅对象。

    ``story`` 不在 ``HOME_RETURN_V2_MODES`` 里，所以 ``HomeReturn`` 走 legacy 分支、
    原样把调用转给 ``navigator.return_home`` —— 正是这两条契约想测的东西
    （它们只关心「探针有没有被传下去」，不关心回家本身怎么走）。
    """
    return main_module.HomeReturn(navigator, MagicMock(), mode="story")


def test_enter_mode_refuses_a_navigator_that_swallows_the_resume_probe():
    """探针被吃掉了就不许当没事发生。

    真 ``return_home`` 的两条正常返回路径（命中接力点 / 回到大厅）**都在问过探针之后**，
    其余路径全是 raise —— 所以「返回了却一次没问过」只可能是接线断了，
    比如 ``_enter_mode`` 忘了传 ``stop_probe``。那时候日志里一片祥和，
    人停在半路照样退回大厅重走，谁也不会发现探针白写了。
    """

    spec, machine = _story_machine()
    navigator = MagicMock()
    navigator.return_home.return_value = BLANK_FRAME

    with pytest.raises(RuntimeError, match="一次都没问过"):
        main_module._enter_mode(
            spec, machine, navigator, MagicMock(), _legacy_home_return(navigator)
        )


def test_enter_mode_falls_back_to_the_old_route_when_the_probe_misses():
    """问过了、但认不出 ⇒ 照旧「回大厅 → 按路线导航」，与接力挂上之前完全一致。"""

    spec, machine = _story_machine()
    navigator = MagicMock()

    def return_home(**kwargs):
        kwargs["stop_probe"](BLANK_FRAME)
        return BLANK_FRAME

    navigator.return_home.side_effect = return_home

    main_module._enter_mode(
        spec, machine, navigator, MagicMock(), _legacy_home_return(navigator)
    )

    navigator.navigate.assert_called_once_with("story", lobby_screen=BLANK_FRAME)


# ---- 登记表护栏 ----


def test_every_route_is_registered_in_the_coverage_doc():
    """新增路线必须去 ``docs/RESUME_COVERAGE.md`` 表态。

    这是**弱**护栏（只查名字出现过，不查写得对不对），但比什么都不查强：
    没有它，新路线的接力状况永远不会被写下来。
    """

    text = COVERAGE_DOC.read_text(encoding="utf-8")

    missing = [name for name in MODE_SPECS if name not in text]

    assert not missing, f"这些路线没在 {COVERAGE_DOC.name} 里登记：{missing}"


# ---- ③ 判据必须真认得准 ----


def _reference_frames(mode: str) -> list:
    """这条路线自己的夹具，裁到基准尺寸。比基准小的跳过（匹配层会按宽高比拒绝）。"""
    # ⚠️ 只有 PC 素材的路线（``modes.PC_ONLY_ROUTES``）夹具放在 ``*_pc`` 目录下，
    # 与 ``tests/fixtures`` 的既有约定一致（PC 帧不混进模拟器基线目录）。
    suffix = "_pc" if mode in PC_ONLY_ROUTES else ""
    group = FIXTURES / f"epic7_{mode}{suffix}"
    frames = []
    for path in sorted(group.glob("*.png")):
        raw = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if raw is None:
            continue
        height, width = raw.shape[:2]
        if height < REFERENCE_HEIGHT or width < REFERENCE_WIDTH:
            continue
        frames.append(
            cv2.cvtColor(
                raw[:REFERENCE_HEIGHT, :REFERENCE_WIDTH], cv2.COLOR_BGR2RGB
            )
        )
    return frames


@pytest.mark.parametrize("name", PROBE_MODES)
def test_the_probe_recognises_at_least_one_of_its_own_fixtures(name: str):
    """「挂上了」不等于「认得出」。

    判据写错、锚点写反、阈值抄错、名字拼错 —— 全都表现为**永远返回 None**，
    而单看代码看不出来。拿这条路线自己的夹具跑一遍真的探针是唯一能现形的办法。

    这里只要求「至少认出一页」（守住「探针不是死的」）；哪几页必须认得出，
    由各路线自己的 ``tests/test_<路线>_resume.py`` 精确钉住。
    """

    spec = MODE_SPECS[name]
    # 「真实模板根」对只有 PC 素材的路线是 pc 视图，不是模拟器视图 —— 拿模拟器根
    # 去构建它们必然缺图，那是在要求「一条还没做模拟器素材的路线凭空可用」。
    root = TemplateDir(TEMPLATE_ROOT, "pc") if name in PC_ONLY_ROUTES else TEMPLATE_ROOT
    machine = spec.build_machine(root, spec.default_state)
    frames = _reference_frames(name)

    assert frames, f"{name} 没有可用夹具，这条测试等于没跑"
    recognised = []
    for frame in frames:
        point = spec.resume_probe(machine, frame, None)
        if point is None:
            continue
        recognised.append(point)
        assert point.page, f"{name} 的探针返回了空页面名，日志会看不出落在哪"
        # ⚠️ 兜底断言（2026-09-27 批次 4 的 D2）：探针报「该拨到 X」时，状态机必须
        # **真的已经是 X**。漏掉 ``machine.resume_from(found.state)`` 时接力看起来是
        # 命中的（日志照打「开局=接力」），但状态机没拨过去，Runner 会原地干等到超时。
        # 现在 ``modes._resume_probe`` 工厂把这一步写死了，这条断言是第二道 —— 万一
        # 将来某条路线绕开工厂自带一套拨法，它会立刻现形。
        #
        # ⚠️ 必须**紧跟在那一次探针调用后面**断言：探针会改状态机，攒完再统一断言
        # 比的是「最后一帧之后的状态」与「每一帧报的落点」，会误报。
        if point.state is not None:
            assert machine.state.value == point.state, (
                f"{name} 的探针报了落点状态 {point.state}，但状态机还停在 "
                f"{machine.state.value} —— resume_from 没接上。"
            )

    assert recognised, (
        f"{name} 的探针在自己的 {len(frames)} 张夹具上一帧都认不出 —— "
        "接线在、判据不在。"
    )
