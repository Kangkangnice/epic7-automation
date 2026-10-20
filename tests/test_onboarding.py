"""首次启动须知：确认记录的判定，以及「不同意就不许开始」这条线。

分两层测：
- **纯函数**（``has_consent`` / ``record_consent`` / ``clear_consent``）：不碰 Tk；
- **界面门禁**：``consent_required=True`` 时「开始任务」必须点不动，同意后才放开。

⚠️ 测试里的 ``consent_required`` 一律**显式传 True**。默认值是 False（只有真正的
入口 ``main()`` 才打开它），所以现有 GUI 测试不会因为没点过同意就被挡住 ——
这条默认值本身就是被测对象之一，见 ``test_onboarding_is_off_by_default``。
"""

from __future__ import annotations

from datetime import datetime
import json
import re

import pytest
import tkinter as tk

from auto_game_unified.desktop import onboarding
from auto_game_unified.desktop.app import DesktopApp, DesktopController
from auto_game_unified.desktop.preflight import PreflightReport, PreflightStatus

PASSED = PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132))


class IdleWorker:
    """不起真进程的假 worker：只提供界面问得到的那几个属性。"""

    def __init__(self) -> None:
        self.running = False
        self.request = None

    def start(self, request) -> None:
        self.request = request

    def request_stop(self) -> None:
        pass

    def force_stop(self) -> bool:
        return True

    def drain_events(self) -> list:
        return []


class ImmediateThread:
    def __init__(self, *, target, **_kwargs) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def ready_controller() -> DesktopController:
    """勾好一条、且环境检测已通过 —— 只剩「同意」这一道门。"""
    controller = DesktopController(worker=IdleWorker())
    controller.toggle("story", True)
    controller.apply_preflight(PASSED)
    return controller


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        # 环境级偶发：一次进程里建第二个 Tk 根时，偶尔会报
        # "Can't find a usable init.tcl"（全量 2026-10-20 撞过一次，单跑这个文件不复现）。
        # 跳过而不是整轮变红 —— 目录、Tcl 本身都好好的，换个进程就能起。
        pytest.skip(f"Tk 起不来：{exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tk_window(tk_root):
    existing_callbacks = set(tk_root.tk.call("after", "info"))
    window = tk.Toplevel(tk_root)
    window.withdraw()
    yield window
    for callback in set(tk_root.tk.call("after", "info")) - existing_callbacks:
        tk_root.tk.call("after", "cancel", callback)
    window.destroy()


def make_app(tk_window, tmp_path, **overrides) -> DesktopApp:
    options = {
        "consent_required": True,
        "consent_probe": lambda _root: False,
        "consent_prompt": lambda *_args: False,
        "preflight_runner": lambda **_kwargs: PASSED,
        "thread_factory": ImmediateThread,
    }
    options.update(overrides)
    return DesktopApp(
        tk_window,
        controller=ready_controller(),
        project_root=tmp_path,
        **options,
    )


# --------------------------------------------------------------------------
# 纯函数：认不出就当没同意过
# --------------------------------------------------------------------------


def test_missing_record_means_not_consented(tmp_path):
    assert onboarding.has_consent(tmp_path) is False


def test_record_then_read_roundtrip(tmp_path):
    assert onboarding.record_consent(tmp_path) is True

    assert onboarding.has_consent(tmp_path) is True
    payload = json.loads(
        (tmp_path / onboarding.CONSENT_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["accepted"] is True
    assert payload["version"] == onboarding.CONSENT_VERSION
    assert payload["accepted_at"]


def test_record_stamps_time_from_injected_clock(tmp_path):
    onboarding.record_consent(tmp_path, now=lambda: datetime(2026, 10, 19, 22, 0, 0))

    payload = json.loads(
        (tmp_path / onboarding.CONSENT_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["accepted_at"] == "2026-10-19T22:00:00"


@pytest.mark.parametrize(
    "payload",
    [
        "这不是 JSON",
        "[]",
        '"已同意"',
        "{}",
        '{"accepted": true}',
        '{"version": 1, "accepted": false}',
        '{"version": 1, "accepted": "yes"}',
    ],
)
def test_damaged_record_asks_again(tmp_path, payload):
    """文件在、但内容认不出 —— 一律当「没同意过」，宁可多问一遍。"""
    (tmp_path / onboarding.CONSENT_FILENAME).write_text(payload, encoding="utf-8")

    assert onboarding.has_consent(tmp_path) is False


def test_old_consent_version_asks_again(tmp_path):
    """条款改版靠版本号把老用户重新问一遍 —— 这是唯一的机制，别让它失效。"""
    stale = {
        "version": onboarding.CONSENT_VERSION - 1,
        "accepted": True,
        "accepted_at": "2020-01-01T00:00:00",
    }
    (tmp_path / onboarding.CONSENT_FILENAME).write_text(
        json.dumps(stale), encoding="utf-8"
    )

    assert onboarding.has_consent(tmp_path) is False


def test_unwritable_root_is_reported_not_raised(tmp_path):
    """写不进去要返回 False，不能抛 —— 抛了会把用户直接关在程序外面。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("占位", encoding="utf-8")

    assert onboarding.record_consent(blocker / "data") is False


def test_write_leaves_no_temporary_file_behind(tmp_path):
    onboarding.record_consent(tmp_path)

    assert [item.name for item in tmp_path.iterdir()] == [onboarding.CONSENT_FILENAME]


def test_clear_consent_forgets_the_record(tmp_path):
    onboarding.record_consent(tmp_path)

    assert onboarding.clear_consent(tmp_path) is True
    assert onboarding.has_consent(tmp_path) is False


def test_clear_consent_tolerates_a_missing_record(tmp_path):
    assert onboarding.clear_consent(tmp_path) is True


# --------------------------------------------------------------------------
# 文案：必须有文档依据，也不许写文档里没有的承诺
# --------------------------------------------------------------------------


def test_risk_points_state_the_real_boundaries():
    risk = " ".join(onboarding.RISK_POINTS)

    # 2026-10-20 用户要求把风险那四点**合成一条**讲（非官方 / 不读取数据 /
    # 只做视觉识别 / 非商业用途），顺序照他给的来。这条断言钉住「是一条」。
    assert len(onboarding.RISK_POINTS) == 1
    assert "非官方" in risk
    # 合成的四点各自都要在里面 —— 少一条就不是他要的那一条了。
    assert "视觉识别" in risk
    assert "不读取" in risk
    assert "非商业" in risk
    # 落点必须还在：可以不说「会封号」，但不能只讲我们干净、不讲风险归谁。
    assert "自行承担" in risk
    # 不许给出「不会封号」这类保证（NOTICE.md / SECURITY.md 都明确不保证）
    assert "不会封号" not in risk
    assert "不封号" not in risk
    # 竞技场（PVP）路线是**存在**的 —— 文案不许声称不提供 PVP，
    # 那会让用户以为竞技场是安全的、或者以为没有这条路线。
    assert "不提供 PVP" not in risk


def test_setup_points_cover_the_limits_users_actually_hit():
    """这几句对应 README §环境要求 / §已知限制 里最容易踩的几条。"""
    setup = " ".join(onboarding.SETUP_POINTS)

    assert "大厅" in setup  # 起点是人工停好的大厅
    assert "1920×1080" in setup  # 渲染区尺寸
    assert "简体中文" in setup  # 模板按中文界面采集

    # 2026-10-20 用户实测纠正：模拟器**可以**被别的窗口挡住跑，鼠标也不占用。
    # 旧文案「自动化期间必须保持前台，不能最小化或被挡住，不支持后台运行」是从
    # PC 后端（`core/pc_window.py` 用 SendInput 真实鼠标）那套结论抄过来的，
    # 对模拟器不成立 —— 别把它写回来。
    assert "不支持后台运行" not in setup
    assert "必须保持前台" not in setup
    assert "挡住" in setup
    # 「建议不要最小化」是保守留的（最小化后 PrintWindow 还灵不灵要看显卡驱动），
    # 不是硬限制；这条只保证那句话还在，别悄悄升级成「必须」。
    assert "建议不要" in setup


def test_text_has_no_markdown_markup():
    """文案直接进 tk 的 Label，不解释标记 —— 写 `**重点**` 会原样冒出星号。

    2026-10-19 渲染截图时踩过：SETUP_POINTS 里一处 `**大厅**` 显示了字面星号。
    """
    text = "".join(onboarding.RISK_POINTS + onboarding.SETUP_POINTS)

    assert "**" not in text
    assert "__" not in text
    assert "](" not in text


def test_the_consent_dialog_gets_a_sane_position(tk_window):
    """不摆位置的话 Tk 会把对话框丢在屏幕左上角 —— 2026-10-19 打包版截图才发现。

    这里只守两件事：位置被显式设过、且不在负坐标（父窗口贴边时算出来的负值）。
    """
    from auto_game_unified.desktop import theme as theme_module
    from auto_game_unified.desktop.onboarding import ConsentDialog

    theme = theme_module.build(tk_window)
    dialog = ConsentDialog(tk_window, theme)
    try:
        geometry = dialog.geometry()
        match = re.match(r"^\d+x\d+\+(-?\d+)\+(-?\d+)$", geometry)
        assert match, f"geometry 里没有位置：{geometry}"
        assert int(match.group(1)) >= 0
        assert int(match.group(2)) >= 0
    finally:
        dialog.destroy()


# --------------------------------------------------------------------------
# 界面门禁
# --------------------------------------------------------------------------


def test_the_accept_button_works_without_a_checkbox(tk_window):
    """点「开始使用」就是同意 —— 这一屏不该再有勾选框或二次确认。

    2026-10-20 用户要求去掉「我已阅读并理解…」勾选 + 按钮置灰。这里守三件事：
    按钮一上来就是可点的、没有那颗勾选框、点下去 ``accepted`` 直接翻成真。
    """
    from auto_game_unified.desktop import theme as theme_module
    from auto_game_unified.desktop.onboarding import ConsentDialog

    theme = theme_module.build(tk_window)
    dialog = ConsentDialog(tk_window, theme)
    try:
        assert str(dialog._accept_button.cget("state")) == "normal"
        # 旧的勾选框属性必须整个消失，而不是留一个永远为真的哑变量 ——
        # 留着它，下一个人就会以为「这里还有一道确认」。
        assert not hasattr(dialog, "_acknowledged")
        assert not hasattr(dialog, "_refresh_buttons")

        dialog._on_accept()
        assert dialog.accepted is True
    finally:
        dialog.destroy()


def test_onboarding_is_off_by_default(tk_window, tmp_path):
    """默认不开：测试和嵌入式调用不该凭空被一个模态窗挡住。"""
    app = DesktopApp(
        tk_window, controller=ready_controller(), project_root=tmp_path
    )

    assert app.consented is True


def test_unconsented_app_keeps_start_disabled(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path)

    assert app.consented is False
    assert str(app.start_button.cget("state")) == "disabled"


def test_declining_keeps_start_disabled_and_says_why(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path)

    app._ensure_consent()

    assert app.consented is False
    assert onboarding.has_consent(tmp_path) is False
    assert str(app.start_button.cget("state")) == "disabled"
    # 拒绝时不该再弹第二个窗，而是留一句「为什么点不动、去哪重新看」
    log = app.log_text.get("1.0", tk.END)
    assert "使用须知" in log


def test_accepting_records_consent_and_unlocks_start(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path, consent_prompt=lambda *_args: True)

    app._ensure_consent()

    assert app.consented is True
    assert onboarding.has_consent(tmp_path) is True
    # 同意之后会顺手跑一次环境检测；测试里没有 mainloop，手动把结果送回去
    app._finish_environment_check(PASSED)
    assert str(app.start_button.cget("state")) == "normal"


def test_consent_that_cannot_be_saved_still_lets_this_session_run(
    tk_window, tmp_path
):
    """落盘失败不许把人关在门外：用户刚刚确实点了同意，只是下次还得再问一次。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("占位", encoding="utf-8")
    app = make_app(
        tk_window,
        tmp_path,
        data_root=blocker,  # 写不进去的根目录
        consent_prompt=lambda *_args: True,
    )

    app._ensure_consent()

    assert app.consented is True
    app._finish_environment_check(PASSED)
    assert str(app.start_button.cget("state")) == "normal"
    assert "无法保存确认记录" in app.log_text.get("1.0", tk.END)


def test_second_launch_skips_the_dialog(tk_window, tmp_path):
    onboarding.record_consent(tmp_path)
    calls: list[tuple] = []
    app = make_app(
        tk_window,
        tmp_path,
        consent_probe=onboarding.has_consent,
        consent_prompt=lambda *args: calls.append(args) or True,
    )

    app._ensure_consent()

    assert app.consented is True
    assert calls == []
