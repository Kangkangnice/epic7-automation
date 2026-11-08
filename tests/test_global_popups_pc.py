"""「解锁缘分」弹窗：PC 专属全局弹窗扩展（模拟器零改动）的回归测试。

2026-11-07 13:11 主线真机：Episode 5 第 3 关通关后弹出这层通知窗，整页盖住
关卡入口 ⇒ ``页面无进展：主线画面[跳过确认]未识别`` ⇒ 主线 ✗、安全停止回家。

⚠️ 本文件最重要的两条不是「认得出」，而是：
  * 模拟器口径下两张 PC 图都加载不到 ⇒ 判据恒 None；
  * ``install_pc_only_popups`` 在模拟器口径下是**完全 no-op**。
用户 2026-11-07 定死：移植项目所有改动只能在 PC 里，模拟器完全不动。
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auto_game_unified.core.matcher import find_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7 import global_popups as popups_module
from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    find_pet_gift_badge,
    load_network_reconnect_templates,
    load_pet_gift_templates,
)
from auto_game_unified.games.epic7.global_popups_pc import (
    _OK_REGION,
    _OK_THRESHOLD,
    _TITLE_REGION,
    _TITLE_THRESHOLD,
    find_relationship_unlock_ok,
    install_pc_only_popups,
    load_relationship_unlock_templates,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GLOBAL_FIXTURES = FIXTURES / "epic7_global"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"
POPUP = "relationship_unlock_pc_live_20261107.png"


def load_screen(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def popup_screen() -> np.ndarray:
    return load_screen(GLOBAL_FIXTURES / POPUP)


def pc_templates():
    return load_relationship_unlock_templates(TemplateDir(TEMPLATES, "pc"))


def emulator_templates():
    return load_relationship_unlock_templates(TEMPLATES)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


# ── 认得出 / 点得对 ──────────────────────────────────────────────────────────


def test_relationship_unlock_is_recognised_on_pc_and_points_at_ok():
    """PC 双锚点 1.0000，点击点是金色 OK 中心 (957,825)。"""
    screen = popup_screen()
    match = find_relationship_unlock_ok(screen, pc_templates())

    assert match is not None
    assert match.score >= 0.99
    assert abs(match.center[0] - 957) <= 8, match.center
    assert abs(match.center[1] - 825) <= 8, match.center


def test_emulator_loads_no_relationship_unlock_templates():
    """两张图只在 global/pc/：模拟器口径全 None ⇒ 判据恒不生效。"""
    templates = emulator_templates()
    assert templates.title is None
    assert templates.ok is None
    assert find_relationship_unlock_ok(popup_screen(), templates) is None


def test_title_anchor_is_exclusive_across_global_popups():
    """排他回归：全库已知最高分负例 0.4761，阈 0.82 ⇒ 余量 0.3439。

    这里把三张最高分负例与其它 22 张全局弹窗夹具逐帧钉住，防止以后
    「顺手调阈值 / 换低通口径」把冒牌货放进来。
    """
    templates = pc_templates()
    negatives = [
        FIXTURES / "epic7_knights_donation" / "support_confirm.png",
        FIXTURES / "epic7_story" / "battle_auto_off_live_20260809.png",
        FIXTURES / "epic7_hero" / "reward_popup.png",
    ] + [
        path
        for path in sorted(GLOBAL_FIXTURES.glob("*.png"))
        if path.name != POPUP
    ]
    for path in negatives:
        assert find_relationship_unlock_ok(load_screen(path), templates) is None, path.name

    # 真实分数也留一条：最高分负例离阈值还差多少，事后能复核。
    worst = find_template(
        load_screen(negatives[0]),
        templates.title,
        0.0,
        region=_TITLE_REGION,
        reference_size=(1982, 1132),
    )
    assert worst is not None
    assert 0.45 <= worst.score <= 0.50, worst.score
    assert worst.score < _TITLE_THRESHOLD


def test_ok_anchor_alone_cannot_fire():
    """把标题区域抹平 ⇒ 即使 OK 按钮在，也不许出手（OK 单独不是判据）。"""
    screen = popup_screen().copy()
    x, y, w, h = _TITLE_REGION
    screen[y : y + h, x : x + w] = 0
    assert find_relationship_unlock_ok(screen, pc_templates()) is None


def test_missing_ok_anchor_does_not_guess_a_point():
    """标题在、OK 定位不到 ⇒ None，绝不退回到一个猜出来的坐标。"""
    screen = popup_screen().copy()
    x, y, w, h = _OK_REGION
    screen[y : y + h, x : x + w] = 0
    assert find_relationship_unlock_ok(screen, pc_templates()) is None

    # 抹平之后 OK 确实不再命中，保证上面这条不是「碰巧返回 None」。
    assert (
        find_template(
            screen,
            pc_templates().ok,
            _OK_THRESHOLD,
            region=_OK_REGION,
            reference_size=(1982, 1132),
        )
        is None
    )


# ── 装配层：模拟器零改动 / PC 继承既有安全机制 ────────────────────────────────


def _guard() -> Epic7GlobalPopupGuard:
    return Epic7GlobalPopupGuard(load_network_reconnect_templates(TEMPLATES))


def test_install_is_a_complete_noop_on_emulator():
    """模拟器口径：守卫的 _find_popup 一个字节都不换。"""
    guard = _guard()
    before = guard._find_popup
    result = install_pc_only_popups(guard, TEMPLATES)

    assert result is guard
    assert guard._find_popup == before
    assert not getattr(guard, "_pc_only_popups_installed", False)


def test_install_is_idempotent():
    """重复安装不能套出多层闭包。"""
    guard = _guard()
    install_pc_only_popups(guard, TemplateDir(TEMPLATES, "pc"))
    once = guard._find_popup
    install_pc_only_popups(guard, TemplateDir(TEMPLATES, "pc"))
    assert guard._find_popup is once


def test_installed_guard_recognises_relationship_unlock_as_a_new_popup():
    guard = install_pc_only_popups(_guard(), TemplateDir(TEMPLATES, "pc"))
    match, popup, action, label, failure = guard._find_popup(popup_screen())

    assert match is not None
    assert (abs(match.center[0] - 957) <= 8) and (abs(match.center[1] - 825) <= 8)
    assert popup == "relationship_unlock"
    assert action == "dismiss-relationship-unlock"
    assert label == "relationship_unlock_failed"
    assert "解锁缘分" in failure
    assert str(popups_module._MAX_POPUP_CLICKS) in failure


def test_installed_guard_still_handles_the_original_popups():
    """回归：包装不能挡住原守卫的判据链（断线重连仍照常认出）。"""
    guard = install_pc_only_popups(_guard(), TemplateDir(TEMPLATES, "pc"))
    _, popup, action, _, _ = guard._find_popup(
        load_screen(GLOBAL_FIXTURES / "network_reconnect.png")
    )
    assert popup == "network"
    assert action == "retry-network"


def test_persistent_relationship_unlock_inherits_click_budget_and_fuse(tmp_path):
    """弹窗常驻 ⇒ 沿用原守卫的 4 次预算 / 15 秒熔断 / 诊断，不另造一套循环。"""
    screen = popup_screen()
    clock = FakeClock()
    clicks: list[tuple[int, int]] = []
    runtime = Runtime(
        lambda: screen,
        clicks.append,
        monotonic=clock.now,
        diagnostic_dir=tmp_path,
        emit=lambda _: None,
    )
    guard = install_pc_only_popups(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        ),
        TemplateDir(TEMPLATES, "pc"),
    )
    runtime.set_capture_guard(guard)

    with pytest.raises(
        RuntimeError,
        match=(
            f"「解锁缘分」弹窗点击{popups_module._MAX_POPUP_CLICKS}次后仍未消失"
        ),
    ):
        runtime.capture()

    assert len(clicks) == popups_module._MAX_POPUP_CLICKS
    assert all(abs(x - 957) <= 8 and abs(y - 825) <= 8 for x, y in clicks)
    assert len(list(tmp_path.glob("*_relationship_unlock_failed.png"))) == 1


def test_pc_install_leaves_every_other_popup_decision_unchanged():
    """等价性快照：装了 PC 扩展之后，其它 23 类弹窗的判定逐帧一字不差。

    这是「不能影响模拟器 / 不能改公共逻辑」最硬的一条：不是看代码改没改，
    而是拿同一批真实夹具跑两遍守卫，比 popup 名、动作名、点击点、分数。
    """
    plain = _guard()
    installed = install_pc_only_popups(_guard(), TemplateDir(TEMPLATES, "pc"))

    def signature(result):
        match, popup, action, label, failure = result
        return (
            popup,
            action,
            label,
            failure,
            None if match is None else (match.center, round(match.score, 4)),
        )

    checked = 0
    for path in sorted(GLOBAL_FIXTURES.glob("*.png")):
        if path.name == POPUP:
            continue
        screen = load_screen(path)
        assert signature(installed._find_popup(screen)) == signature(
            plain._find_popup(screen)
        ), path.name
        checked += 1
    assert checked >= 20, checked


# ── 装配层：main.py 只有 PC 分支会注入 ────────────────────────────────────────


def _run_mode_on(backend: str, install_mock=None):
    """跑一遍真实的 ``main.run_mode`` 装配；``install_mock=None`` = 不打桩。"""
    from contextlib import nullcontext
    from dataclasses import replace
    from unittest.mock import MagicMock, patch

    from auto_game_unified import main as main_module
    from auto_game_unified.games.epic7.modes import get_mode

    runtime = MagicMock()
    runner_type = MagicMock()
    runner_type.return_value.run.return_value = 0
    spec = replace(
        get_mode("story"),
        runner_type=runner_type,
        build_machine=MagicMock(return_value=object()),
        needs_navigation=False,
    )
    injection = (
        patch.object(main_module, "install_pc_only_popups", install_mock)
        if install_mock is not None
        else nullcontext()
    )
    with (
        patch.object(main_module, "_build_runtime", return_value=runtime),
        injection,
    ):
        main_module.run_mode(
            spec=spec,
            dry_run=False,
            max_cycles=1,
            start_state=spec.default_state,
            window_backend=backend,
        )
    return runtime


def test_main_never_injects_pc_popups_on_emulator():
    from unittest.mock import MagicMock

    inject = MagicMock()
    runtime = _run_mode_on("emulator", inject)

    inject.assert_not_called()
    runtime.set_capture_guard.assert_called_once()
    # 挂上去的必须是**没被打补丁**的原守卫。
    guard = runtime.set_capture_guard.call_args.args[0]
    assert isinstance(guard, Epic7GlobalPopupGuard)
    assert not getattr(guard, "_pc_only_popups_installed", False)


def test_main_injects_pc_popups_only_on_pc():
    from unittest.mock import MagicMock

    inject = MagicMock(side_effect=lambda guard, _: guard)
    runtime = _run_mode_on("pc", inject)

    inject.assert_called_once()
    assert inject.call_args.args[1].name == "global"
    runtime.set_capture_guard.assert_called_once()


def test_real_pc_assembly_recognises_relationship_unlock():
    """端到端：不打桩，真跑一遍 main 的 PC 装配，守卫必须认出这层弹窗。"""
    runtime = _run_mode_on("pc")
    guard = runtime.set_capture_guard.call_args.args[0]
    match, popup, action, _, _ = guard._find_popup(popup_screen())

    assert popup == "relationship_unlock"
    assert action == "dismiss-relationship-unlock"
    assert match is not None and abs(match.center[1] - 825) <= 8


def test_real_emulator_assembly_stays_blind_to_relationship_unlock():
    """端到端：模拟器口径下，同一张 PC 帧仍认不出（守卫没被装任何新判据）。"""
    runtime = _run_mode_on("emulator")
    guard = runtime.set_capture_guard.call_args.args[0]
    _, popup, _, _, _ = guard._find_popup(popup_screen())

    assert popup != "relationship_unlock"
    assert not getattr(guard, "_pc_only_popups_installed", False)


# ── 宠物小屋礼物角标：PC 侧回归（2026-11-07） ──────────────────────────────
#
# 用户 15:51 截图问「宠物小屋旁边的宝箱，模拟器会点、PC 不点，把它加进去」。
# 查证结论：**判据 2026-09-28 就接好了**（``global_popups.find_pet_gift_badge``，
# 单锚点、阈 0.80、ROI (1500,300,300,220)），PC 也一直在用同一张共享图：
#   * 11-06 17:23:37 PC 实跑就点过 ``claim-pet-gift 坐标=(1678, 385)``；
#   * 11-07 全天 26 次「打开快捷菜单」零次 claim-pet-gift，但守卫在跑
#     （36 次 dismiss-reward-notice、20 次 retry-network）；
#   * 11-07 全部 46 张真机诊断帧里，宝箱角标最高只有 0.5124 ⇒ 那些帧没有礼物；
#   * 礼物是低频事件（历史点击约每 1~6 天一次，11-06 领掉后 11-07 无新点击），
#     最后一次实跑 13:55，早于用户 15:51 的截图。
#
# ⇒ **不是「没加过」，也不是「PC 认不出」**。所以这里不改业务逻辑、不补 PC 图
#   （PC 与模拟器是同一套渲染：互比 0.9725，补图只会多一份要维护的副本），
#   只补此前缺的那块：**PC 正例夹具 + PC/模拟器两端端到端回归**。
#   夹具由用户 JPG 截图按 ``pc_window.LEGACY_TOP=52`` 还原成 1982x1132 生产画布
#   （右侧 62px / 顶部 52px 补黑，与 BitBlt 抓帧结构一致），非 BitBlt 原帧。

PET_GIFT_PC = "pet_gift_pc_live_20261107.png"
PET_BADGE_BOX = (1630, 338, 96, 94)  # 与共享模板的裁剪框一致


def pet_gift_screen() -> np.ndarray:
    return load_screen(GLOBAL_FIXTURES / PET_GIFT_PC)


def test_pc_does_not_override_the_shared_pet_gift_badge():
    """PC 与模拟器解析到**同一张**角标图 ⇒ 模拟器侧一个字节都没变。"""
    pc = TemplateDir(TEMPLATES, "pc") / "pet_gift_badge.png"
    emulator = TEMPLATES / "pet_gift_badge.png"
    assert pc == emulator
    assert (
        load_pet_gift_templates(TEMPLATES).badge
        == load_pet_gift_templates(TemplateDir(TEMPLATES, "pc")).badge
    ).all()


def test_pc_pet_gift_frame_is_recognised_by_the_existing_shared_template():
    """PC 客户端（钢铁工坊页常驻侧栏）上，既有共享模板照样高分命中。"""
    badge = load_pet_gift_templates(TEMPLATES).badge
    match = find_pet_gift_badge(pet_gift_screen(), badge)

    assert match is not None
    assert match.score >= 0.95
    assert abs(match.center[0] - 1676) <= 8, match.center
    assert abs(match.center[1] - 383) <= 8, match.center


def test_pc_pet_gift_badge_erased_means_no_click():
    """抹掉角标 ⇒ 不出手，避免在 PC 大厅侧栏上乱点。"""
    screen = pet_gift_screen().copy()
    x, y, w, h = PET_BADGE_BOX
    screen[y : y + h, x : x + w] = 0
    assert find_pet_gift_badge(screen, load_pet_gift_templates(TEMPLATES).badge) is None


def test_real_pc_assembly_claims_pet_gift_badge():
    """端到端：不打桩真跑 main 的 PC 装配，守卫在这张 PC 帧上必须返回 claim-pet-gift。"""
    runtime = _run_mode_on("pc")
    guard = runtime.set_capture_guard.call_args.args[0]
    match, popup, action, _, _ = guard._find_popup(pet_gift_screen())

    assert (popup, action) == ("pet_gift", "claim-pet-gift")
    assert match is not None and match.score >= 0.95
    assert abs(match.center[0] - 1676) <= 8


def test_real_emulator_assembly_claims_pet_gift_badge_too():
    """两端都能点 ⇒ 钉住「这不是 PC 特有的缺口」，别再往 PC 里重复加判据。"""
    runtime = _run_mode_on("emulator")
    guard = runtime.set_capture_guard.call_args.args[0]
    _, popup, action, _, _ = guard._find_popup(pet_gift_screen())

    assert (popup, action) == ("pet_gift", "claim-pet-gift")
