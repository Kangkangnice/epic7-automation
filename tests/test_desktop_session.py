"""会话存档：读坏了不许崩、非法值要被挡回去。

这些用例守的是 ``desktop/session.py`` 开头那三条约定 —— 尤其是第 1 条：
**存档出问题不能影响助手启动**，否则用户为了「记住上次勾选」付出打不开程序的代价。
"""

import json
from pathlib import Path

from auto_game_unified.desktop import session
from auto_game_unified.games.epic7.modes import MODE_SPECS


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert session.load(tmp_path / "session.json") is None


def test_broken_json_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text("{ 这不是 json", encoding="utf-8")
    assert session.load(path) is None


def test_non_dict_payload_returns_none(tmp_path: Path) -> None:
    path = _write(tmp_path / "session.json", ["arena"])
    assert session.load(path) is None


def test_round_trip_keeps_every_field(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    state = session.SessionState(
        selection=("arena", "sanctuary"),
        cycles={"arena": 3},
        backend="pc",
        last_run=session.LastRun(
            at="2026-10-22 19:40", summary="竞技场 ✓ / 圣域 ✓", exit_code=0
        ),
        params={"arena": {"only_npc": True}},
    )

    session.save(path, state)
    loaded = session.load(path)

    assert loaded == state


def test_unknown_route_dropped_and_duplicates_collapsed(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "session.json",
        {"selection": ["arena", "不存在的路线", "arena", "sanctuary"]},
    )
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.selection == ("arena", "sanctuary")


def test_cycles_out_of_range_fall_back_to_default(tmp_path: Path) -> None:
    editable = next(spec for spec in MODE_SPECS.values() if spec.cycles_editable)
    fixed = next(spec for spec in MODE_SPECS.values() if not spec.cycles_editable)
    path = _write(
        tmp_path / "session.json",
        {"cycles": {editable.name: editable.min_cycles - 5, fixed.name: 99}},
    )

    loaded = session.load(path)

    assert loaded is not None
    # 越界 → 回默认；「次数不可编辑」的路线被改成 99 → 也回默认。
    assert loaded.cycles[editable.name] == editable.default_cycles
    assert loaded.cycles[fixed.name] == fixed.default_cycles


def test_non_int_cycles_ignored(tmp_path: Path) -> None:
    editable = next(spec for spec in MODE_SPECS.values() if spec.cycles_editable)
    path = _write(tmp_path / "session.json", {"cycles": {editable.name: "3"}})
    loaded = session.load(path)
    assert loaded is not None
    assert editable.name not in loaded.cycles


def test_missing_fields_use_defaults(tmp_path: Path) -> None:
    """旧文件 / 手工精简过的文件：缺字段就用默认，不许报错。"""
    path = _write(tmp_path / "session.json", {"version": 1})
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.selection == ()
    assert loaded.cycles == {}
    assert loaded.backend == "emulator"
    assert loaded.last_run is None


def test_unknown_fields_ignored(tmp_path: Path) -> None:
    """将来的版本多写了字段：现在这一版必须照读不误（向前兼容）。"""
    path = _write(
        tmp_path / "session.json",
        {"selection": ["arena"], "future_field": {"nested": 1}},
    )
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.selection == ("arena",)


def test_params_for_unknown_route_dropped(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "session.json",
        {"params": {"arena": {"only_npc": True}, "不存在的路线": {"x": 1}}},
    )
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.params == {"arena": {"only_npc": True}}


def test_window_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    session.save(path, session.SessionState(window={"x": 120, "y": 80, "w": 1400, "h": 900}))
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.window == {"x": 120, "y": 80, "w": 1400, "h": 900}


def test_tiny_or_broken_window_discarded(tmp_path: Path) -> None:
    """窗口尺寸太小 / 字段缺失 ⇒ 当作没记过（否则下次开窗会是一条缝）。"""
    for payload in (
        {"x": 0, "y": 0, "w": 50, "h": 40},
        # 能转成数字的字符串是**合理宽容**（手改文件写成 "1400" 就照收）；
        # 真正无法转换的才丢掉。
        {"x": 0, "y": 0, "w": "很宽", "h": 900},
        {"x": 1},
    ):
        path = _write(tmp_path / "session.json", {"window": payload})
        loaded = session.load(path)
        assert loaded is not None
        assert loaded.window is None


def test_input_mode_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    state = session.SessionState(backend="pc", pc_input_mode="background")
    session.save(path, state)
    loaded = session.load(path)
    assert loaded == state
    assert loaded is not None
    assert loaded.pc_input_mode == "background"


def test_bad_input_mode_falls_back_to_background(tmp_path: Path) -> None:
    """手改坏的存档一律退回默认通道（后台），不能把默认反过来。"""
    for raw in ("backgroundd", 1, None, "", ["background"]):
        path = _write(tmp_path / "session.json", {"pc_input_mode": raw})
        loaded = session.load(path)
        assert loaded is not None
        assert loaded.pc_input_mode == "background"


def test_legacy_session_without_input_mode_defaults_to_background(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "session.json", {"selection": ["arena"], "backend": "pc"}
    )
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.pc_input_mode == "background"


def test_todos_round_trip(tmp_path: Path) -> None:
    """改了三条便签，关掉助手再打开还在。"""
    path = tmp_path / "session.json"
    state = session.SessionState(todos=("给暗法刷速度套", "竞技场打到 1600 分", ""))
    session.save(path, state)
    loaded = session.load(path)
    assert loaded == state


def test_legacy_session_without_todos_has_three_empty_slots(tmp_path: Path) -> None:
    path = _write(tmp_path / "session.json", {"selection": ["arena"]})
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.todos == ("", "", "")


def test_broken_todos_fall_back_to_empty(tmp_path: Path) -> None:
    """手改坏的存档不能让窄条面板打不开，也不能塞进非字符串。"""
    for raw in ("一句话", 42, {"1": "a"}, ["第一", None, 3], None):
        path = _write(tmp_path / "session.json", {"todos": raw})
        loaded = session.load(path)
        assert loaded is not None
        assert all(isinstance(item, str) for item in loaded.todos)
        assert len(loaded.todos) == 3


def test_todos_are_truncated_and_padded(tmp_path: Path) -> None:
    """只留三个槽位；超长文本截断，免得把窄条撑爆。"""
    path = _write(
        tmp_path / "session.json",
        {"todos": ["甲" * 200, "乙"]},
    )
    loaded = session.load(path)
    assert loaded is not None
    assert loaded.todos == ("甲" * session.TODO_MAX_CHARS, "乙", "")
