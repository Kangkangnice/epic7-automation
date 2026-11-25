"""账号名净化与落点。

玩家昵称是**用户自己起的**，可以直接变成目录名 —— 所以这里是全项目唯一一处
「外来字符串拼路径」的地方，必须证明它出不了数据根。

为什么不转换更多（不转小写、不音译）：多一步转换就等于给同一个号造出第二个目录，
那正是要避免的混乱。文件系统本身不区分大小写，这一点交给它自己处理。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_game_unified.core import account


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EPIC7_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("康康626", "康康626"),
        ("  康康626  ", "康康626"),
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        ("a:b*c?d", "a_b_c_d"),
        ("a|b<c>d", "a_b_c_d"),
        # 结尾的点和空格会被 Windows 悄悄吃掉，导致「看着一样、实际两个目录」。
        ("name. ", "name"),
    ],
)
def test_illegal_characters_become_underscores(raw, expected):
    assert account.normalize(raw) == expected


def test_parent_directory_segments_cannot_escape(_isolated_data_dir):
    """``..`` 不许存活：那是唯一能写到数据根之外的方式。"""

    cleaned = account.normalize("../../etc/passwd")
    assert ".." not in cleaned

    directory = account.account_dir("../../etc/passwd")
    assert directory is not None
    assert _isolated_data_dir in directory.parents


def test_account_dir_always_stays_under_data_root(_isolated_data_dir):
    """任何输入拼出来的目录都必须落在 ``<数据根>/accounts`` 里面。"""

    for raw in ("../../etc/passwd", "..\\..\\windows", "C:\\Windows", "/etc", "康康626"):
        directory = account.account_dir(raw)
        assert directory is not None
        assert directory.parent == _isolated_data_dir / account.ACCOUNTS_DIRNAME
        assert _isolated_data_dir in directory.parents


@pytest.mark.parametrize("raw", ["", "   ", None, 123, "..."])
def test_unusable_names_mean_not_identified(raw):
    assert account.normalize(raw) == ""
    assert account.account_dir(raw) is None


def test_reserved_device_names_get_a_prefix():
    """``CON`` / ``COM1`` 这类名字在 Windows 上根本建不出目录。"""

    assert account.normalize("CON") == "_CON"
    assert account.normalize("com1") == "_com1"


def test_too_long_names_are_cut():
    assert len(account.normalize("名" * 100)) == account.MAX_NAME_LEN


def test_account_file_falls_back_to_the_old_path_when_not_identified(tmp_path):
    fallback = tmp_path / "side_story_countdown.json"

    assert account.account_file("", "x.json", fallback=fallback) == fallback
    assert account.account_file(None, "x.json", fallback=fallback) == fallback


def test_account_file_goes_into_its_own_directory(_isolated_data_dir):
    path = account.account_file("康康626", "x.json", fallback=Path("ignored"))

    assert path.parent == _isolated_data_dir / account.ACCOUNTS_DIRNAME / "康康626"
    assert path.name == "x.json"


def test_last_account_round_trip(_isolated_data_dir):
    account.save_last("康康626", "S.Rank.20")

    assert account.load_last() == {"account": "康康626", "rank": "S.Rank.20"}


def test_last_account_missing_means_none(_isolated_data_dir):
    assert account.load_last() is None
