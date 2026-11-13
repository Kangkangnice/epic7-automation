"""首次启动须知：确认记录的判定。

⚠️ 2026-11-09 删掉 Tk 界面时，界面门禁那几条（「开始任务」点不点得动）一起删了 ——
它们测的是 `DesktopApp`，而那个类已经不存在。现在这里只剩**纯函数**：条款文案
与 consent.json 的读写。界面对接在 `desktop_qt/app.py` 里，靠 PySide6 才能起，
不适合放在这套纯逻辑测试里。
"""

from __future__ import annotations

from datetime import datetime
import json

import pytest

from auto_game_unified.desktop import onboarding


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

    # 2026-10-20 用户要求把风险那几点**合成一条**讲（非官方 / 不读取数据 /
    # 只做视觉识别），顺序照他给的来。这条断言钉住「是一条」。
    assert len(onboarding.RISK_POINTS) == 1
    assert "非官方" in risk
    # 合成的几点各自都要在里面 —— 少一条就不是他要的那一条了。
    assert "依据游戏画面" in risk
    assert "常规点击" in risk
    assert "不读取" in risk
    # ⚠️ 2026-10-21 用户拍板**去掉「非商业用途」**（「别人随便怎么用都行，
    # 许可也不用换，把措辞删掉就行」）。代码是 MIT，界面不该再说反话。
    assert "非商业" not in risk
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
    # 「游戏语言用简体中文」这条**被用户要求从弹窗里删掉**（2026-10-20）。
    # 约束本身还在，只是搬到 README §环境要求 与 USER_GUIDE §前置条件。
    assert "简体中文" not in setup

    # 2026-10-20 用户实测纠正：模拟器**可以**被别的窗口挡住跑，鼠标也不占用。
    # 旧文案「自动化期间必须保持前台，不能最小化或被挡住，不支持后台运行」是从
    # PC 后端（`core/pc_window.py` 用 SendInput 真实鼠标）那套结论抄过来的，
    # 对模拟器不成立 —— 别把它写回来。
    assert "不支持后台运行" not in setup
    assert "必须保持前台" not in setup
    assert "遮挡" in setup
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


def test_the_notice_stays_narrow():
    """2026-10-20 用户反馈「使用须知太宽了」，随后要求「一列写完」。

    两栏时代每栏 560、整窗约 1200 逻辑像素，1600 的屏要占 3/4。
    这条钉住「别再随手调宽」，调宽之前先按 1366 的屏量一遍。
    """
    assert onboarding.DIALOG_WIDTH <= 560


