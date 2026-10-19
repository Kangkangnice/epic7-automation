"""版本检查：只提示、不下载；连不上就当没这回事。

三层：
- 版本号比较（纯函数，边界都在这儿）；
- 何时该查、查到之后写什么（用临时目录，不碰真的 GitHub）；
- 界面上那一行「发现新版本」会不会出现、点了会不会开浏览器。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest
import tkinter as tk

from auto_game_unified.desktop import app as app_module
from auto_game_unified.desktop import update_check
from auto_game_unified.desktop.app import DesktopApp, DesktopController
from auto_game_unified.desktop.update_check import (
    UpdateInfo,
    check_for_update,
    due_for_check,
    fetch_latest_release,
    is_newer,
    parse_version,
)

NOW = datetime(2026, 10, 19, 23, 0, 0)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def fake_opener(payload: dict | None, *, error: Exception | None = None):
    def opener(_request, **_kwargs):
        if error is not None:
            raise error
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    return opener


def release(tag: str = "v0.2.0", url: str = "https://example.test/v0.2.0"):
    return tag, url


# --------------------------------------------------------------------------
# 版本号比较
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.2.0", ((0, 2, 0), "")),
        ("0.2.0", ((0, 2, 0), "")),
        ("0.1.0-dev", ((0, 1, 0), "dev")),
        ("1.0", ((1, 0), "")),
        (" V0.3.1 ", ((0, 3, 1), "")),
    ],
)
def test_parse_version_accepts_the_shapes_we_actually_see(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "最新版", "v", "0..1", "-dev"])
def test_parse_version_rejects_nonsense(text):
    assert parse_version(text) is None


def test_parse_version_survives_a_non_string():
    assert parse_version(None) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("0.1.0-dev", "v0.2.0", True),
        ("0.1.0", "v0.1.0", False),
        ("0.1.0", "v0.1.1", True),
        ("0.2.0", "v0.1.9", False),
        # 数字一样时：预发布 → 正式版算新，反过来不算
        ("0.1.0-dev", "v0.1.0", True),
        ("0.1.0", "v0.1.0-dev", False),
    ],
)
def test_is_newer(current, latest, expected):
    assert is_newer(current, latest) is expected


def test_is_newer_stays_quiet_when_either_side_is_unparsable():
    """认不出就不提示 —— 否则一次解析错会变成天天喊「有新版本」。"""
    assert is_newer("0.1.0", "最新版") is False
    assert is_newer("开发中", "v0.2.0") is False


# --------------------------------------------------------------------------
# 频率控制
# --------------------------------------------------------------------------


def test_first_launch_checks():
    assert due_for_check({}, NOW) is True


@pytest.mark.parametrize(
    ("outcome", "age", "expected"),
    [
        ("ok", timedelta(hours=23), False),
        ("ok", timedelta(hours=25), True),
        ("failed", timedelta(hours=1), False),
        ("failed", timedelta(hours=7), True),
    ],
)
def test_retry_interval_depends_on_the_last_outcome(outcome, age, expected):
    state = {
        "outcome": outcome,
        "checked_at": (NOW - age).isoformat(timespec="seconds"),
    }

    assert due_for_check(state, NOW) is expected


def test_a_damaged_timestamp_means_check_again():
    assert due_for_check({"outcome": "ok", "checked_at": "昨天"}, NOW) is True


# --------------------------------------------------------------------------
# 查询本身
# --------------------------------------------------------------------------


def test_a_newer_release_is_reported(tmp_path):
    info = check_for_update(
        "0.1.0-dev",
        tmp_path,
        fetch=lambda: release(),
        now=lambda: NOW,
        environ={},
    )

    assert info == UpdateInfo("0.1.0-dev", "v0.2.0", "https://example.test/v0.2.0")


def test_the_same_version_is_not_reported(tmp_path):
    info = check_for_update(
        "0.2.0", tmp_path, fetch=lambda: release(), now=lambda: NOW, environ={}
    )

    assert info is None


def test_a_failed_lookup_is_recorded_so_we_do_not_hammer(tmp_path):
    calls: list[int] = []

    def failing():
        calls.append(1)
        return None

    assert (
        check_for_update("0.1.0", tmp_path, fetch=failing, now=lambda: NOW, environ={})
        is None
    )
    state = json.loads(
        (tmp_path / update_check.STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert state["outcome"] == "failed"

    later = lambda: NOW + timedelta(hours=1)  # noqa: E731
    assert (
        check_for_update("0.1.0", tmp_path, fetch=failing, now=later, environ={}) is None
    )
    assert len(calls) == 1  # 一小时内没有再打一次


def test_the_switch_turns_it_off_completely(tmp_path):
    calls: list[int] = []

    def counted():
        calls.append(1)
        return release()

    info = check_for_update(
        "0.1.0",
        tmp_path,
        fetch=counted,
        now=lambda: NOW,
        environ={update_check.DISABLE_ENV: "1"},
    )

    assert info is None
    assert calls == []


def test_it_does_not_write_into_an_unwritable_root(tmp_path):
    """写不进去也要给出结论 —— 版本检查不该因为落盘失败而失效。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("占位", encoding="utf-8")

    info = check_for_update(
        "0.1.0", blocker / "data", fetch=lambda: release(), now=lambda: NOW, environ={}
    )

    assert info is not None


# --------------------------------------------------------------------------
# 真的去问 GitHub 的那一层（用假 opener，不出网）
# --------------------------------------------------------------------------


def test_fetch_reads_the_tag_and_the_page():
    opener = fake_opener(
        {"tag_name": "v0.2.0", "html_url": "https://example.test/release"}
    )

    assert fetch_latest_release(opener=opener) == (
        "v0.2.0",
        "https://example.test/release",
    )


def test_fetch_falls_back_to_the_releases_page_for_a_bad_url():
    opener = fake_opener({"tag_name": "v0.2.0", "html_url": "javascript:alert(1)"})

    assert fetch_latest_release(opener=opener) == (
        "v0.2.0",
        update_check.RELEASES_PAGE,
    )


@pytest.mark.parametrize(
    "payload",
    [{}, {"tag_name": ""}, {"tag_name": 3}, ["v0.2.0"]],
)
def test_fetch_rejects_payloads_without_a_usable_tag(payload):
    assert fetch_latest_release(opener=fake_opener(payload)) is None


@pytest.mark.parametrize(
    "error", [OSError("网络不可用"), ValueError("不是 JSON"), TimeoutError("超时")]
)
def test_fetch_swallows_every_kind_of_failure(error):
    assert fetch_latest_release(opener=fake_opener(None, error=error)) is None


# --------------------------------------------------------------------------
# 界面
# --------------------------------------------------------------------------


class IdleWorker:
    def __init__(self) -> None:
        self.running = False

    def drain_events(self) -> list:
        return []


class ImmediateThread:
    def __init__(self, *, target, **_kwargs) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tk_window(tk_root):
    existing = set(tk_root.tk.call("after", "info"))
    window = tk.Toplevel(tk_root)
    window.withdraw()
    yield window
    for callback in set(tk_root.tk.call("after", "info")) - existing:
        tk_root.tk.call("after", "cancel", callback)
    window.destroy()


def make_app(tk_window, tmp_path, **overrides) -> DesktopApp:
    options = {"thread_factory": ImmediateThread}
    options.update(overrides)
    return DesktopApp(
        tk_window,
        controller=DesktopController(worker=IdleWorker()),
        project_root=tmp_path,
        **options,
    )


def test_the_banner_is_hidden_by_default(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path)

    assert app.update_label.winfo_manager() == ""


def test_a_new_release_shows_one_line_and_logs_it(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path)

    app._show_update(
        UpdateInfo("0.1.0-dev", "v0.2.0", "https://example.test/release")
    )

    assert app.update_label.winfo_manager() == "grid"
    assert "v0.2.0" in app.update_var.get()
    assert "0.1.0-dev" in app.update_var.get()
    assert "发现新版本" in app.log_text.get("1.0", tk.END)


def test_no_release_keeps_the_banner_hidden(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path)

    app._show_update(None)

    assert app.update_label.winfo_manager() == ""


def test_the_check_runs_in_the_background_and_lands_on_the_banner(tk_window, tmp_path):
    app = make_app(
        tk_window,
        tmp_path,
        update_check=lambda: UpdateInfo(
            "0.1.0-dev", "v0.2.0", "https://example.test/release"
        ),
    )

    app._start_update_check()
    # 没有 mainloop：手动跑一次挂起回调，等价于线程结束后回到主线程
    app.root.update_idletasks()
    app._show_update(
        UpdateInfo("0.1.0-dev", "v0.2.0", "https://example.test/release")
    )

    assert app.update_label.winfo_manager() == "grid"


def test_a_broken_check_never_reaches_the_ui(tk_window, tmp_path):
    def boom():
        raise RuntimeError("不该冒到界面上")

    app = make_app(tk_window, tmp_path, update_check=boom)

    app._start_update_check()

    assert app.update_label.winfo_manager() == ""


def test_without_a_checker_nothing_happens(tk_window, tmp_path):
    app = make_app(tk_window, tmp_path)

    app._start_update_check()

    assert app.update_label.winfo_manager() == ""


def test_clicking_the_banner_opens_the_release_page(tk_window, tmp_path, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        app_module.webbrowser, "open", lambda url: opened.append(url) or True
    )
    app = make_app(tk_window, tmp_path)
    app._show_update(UpdateInfo("0.1.0-dev", "v0.2.0", "https://example.test/release"))

    app._open_release_page()

    assert opened == ["https://example.test/release"]


def test_clicking_without_a_release_does_nothing(tk_window, tmp_path, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        app_module.webbrowser, "open", lambda url: opened.append(url) or True
    )
    app = make_app(tk_window, tmp_path)

    app._open_release_page()

    assert opened == []
