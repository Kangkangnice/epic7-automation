"""次元探查启动器的纯逻辑测试：参数校验、装配失败、运行与停止。

全部用假的会话，不启动游戏、不加载 WGC。页面在 ``desktop_qt/``，不混进来。
"""

from __future__ import annotations

import threading
from pathlib import Path

from auto_game_unified.desktop.chaos_bridge import (
    ABSENT_MARKER_NAME,
    ChaosBridge,
    absent_marker,
    bundled,
    vendor_root,
    vendor_state,
)


class _FakeSnapshot:
    rounds_completed = 2
    round_limit = 3
    stop_reason = None


class _FakeSession:
    """让后台线程停在闸门上，测试才能稳定地观察 running / stop。"""

    def __init__(self) -> None:
        self.stopped = False
        self.rounds = None
        self.release = threading.Event()

    def run_chaos(self, rounds):
        self.rounds = rounds
        self.release.wait(timeout=5)
        return _FakeSnapshot()

    def request_stop(self) -> None:
        self.stopped = True
        self.release.set()


def _bridge_with_fakes(tmp_path: Path):
    bridge = ChaosBridge(vendor=tmp_path)
    session = _FakeSession()

    def fake_modules():
        return (
            lambda path, *, template_profile: object(),
            lambda config, *, target_stage, lineup_id: object(),
            lambda config, feature, overlay, logger, on_snapshot: session,
        )

    bridge._modules = fake_modules
    return bridge, session


def test_vendor_root_points_into_the_workspace():
    root = vendor_root()
    assert root.name == "e7auto"
    assert root.parent.name == "vendor"


def _layout(tmp_path: Path, *, marker: bool, code: bool) -> Path:
    """摆一个 ``<tmp>/vendor/e7auto`` 布局，返回 e7auto 根目录。"""
    vendor_dir = tmp_path / "vendor"
    root = vendor_dir / "e7auto"
    root.mkdir(parents=True)
    if code:
        (root / "src" / "e7auto").mkdir(parents=True)
    if marker:
        (vendor_dir / ABSENT_MARKER_NAME).write_text("不含次元探查", encoding="utf-8")
    return root


def test_marker_sits_beside_the_vendor_directory():
    """标记与本目录同级 —— 标记在 ``e7auto`` 里面就没法区分「漏拷」了。"""
    marker = absent_marker(Path("C:/x/vendor/e7auto"))
    assert marker.name == ABSENT_MARKER_NAME
    assert marker.parent == Path("C:/x/vendor")


def test_declared_absence_is_not_a_missing_directory(tmp_path: Path):
    """有标记、没代码 ⇒ ``absent``：这是公开候选的正常形态，不该判成缺件。"""
    root = _layout(tmp_path, marker=True, code=False)
    assert vendor_state(root) == "absent"
    assert bundled(root) is False


def test_bundled_code_is_reported_as_present(tmp_path: Path):
    root = _layout(tmp_path, marker=False, code=True)
    assert vendor_state(root) == "present"
    assert bundled(root) is True


def test_missing_code_without_a_marker_is_missing(tmp_path: Path):
    """该有却没有 ⇒ ``missing``：自检据此在打包版里判失败，不静默放过。"""
    root = _layout(tmp_path, marker=False, code=False)
    assert vendor_state(root) == "missing"
    assert bundled(root) is False


def test_marker_wins_over_leftover_code(tmp_path: Path):
    """标记在位就按「声明不含」处理：漏拷的残留不能被当成随包分发。"""
    root = _layout(tmp_path, marker=True, code=True)
    assert vendor_state(root) == "absent"
    assert bundled(root) is False


def test_invalid_inputs_are_rejected_before_anything_runs(tmp_path: Path):
    bridge = ChaosBridge(vendor=tmp_path)
    assert ChaosBridge.validate(0, "dark_twins", 1) != ""
    assert ChaosBridge.validate(6, "dark_twins", 1) != ""
    assert ChaosBridge.validate(True, "dark_twins", 1) != ""
    assert ChaosBridge.validate(1, "unknown", 1) != ""
    assert ChaosBridge.validate(1, "dark_twins", 0) != ""
    assert ChaosBridge.validate(1, "dark_twins", 100) != ""
    assert ChaosBridge.validate(1, "dark_twins", True) != ""
    assert ChaosBridge.validate(1, "dark_twins", 1) == ""
    assert bridge.start(9, "dark_twins", 1) != ""


def test_missing_vendor_code_returns_a_reason(tmp_path: Path):
    bridge = ChaosBridge(vendor=tmp_path)
    error = bridge.start(1, "dark_twins", 1)
    assert "启动失败" in error
    assert not bridge.running


def test_stop_without_a_run_does_nothing(tmp_path: Path):
    assert ChaosBridge(vendor=tmp_path).stop() is False


def test_start_runs_in_background_and_reports_progress(tmp_path: Path):
    bridge, session = _bridge_with_fakes(tmp_path)
    assert bridge.start(2, "budget", 3) == ""
    assert bridge.running
    assert bridge.stop() is True
    assert session.stopped
    assert bridge._thread is not None
    bridge._thread.join(timeout=3)
    assert not bridge.running
    assert session.rounds == 3
    lines = bridge.drain_lines()
    assert any("第 2 阶段" in line for line in lines)
    assert any("运行结束" in line for line in lines)
    assert bridge.drain_lines() == []


def test_second_start_is_refused_while_running(tmp_path: Path):
    bridge, session = _bridge_with_fakes(tmp_path)
    bridge.start(1, "dark_twins", 1)
    try:
        assert "已经" in bridge.start(1, "dark_twins", 1)
    finally:
        session.release.set()
        if bridge._thread is not None:
            bridge._thread.join(timeout=3)
