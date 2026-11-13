"""``core/countdown.py``：支线刷新读数的那一个小文件。

它是**便签**，不是业务状态：读坏 / 缺失 / 没有那个字段，一律返回 ``None`` 或一句
「还没读过」，**绝不抛错** —— 界面在启动时就会读它，读坏一次就是主窗口起不来。
"""

from __future__ import annotations

import json

import pytest

from auto_game_unified.core import countdown


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """把落点挪到临时目录：别去动开发者机器上真的那份读数。"""

    monkeypatch.setenv("EPIC7_DATA_DIR", str(tmp_path))
    return tmp_path


def test_saves_into_the_data_root_with_a_read_stamp(_isolated_data_dir):
    path = countdown.save_countdown(13, 12, raw="剩余 13天 12小时")

    assert path.parent == _isolated_data_dir
    assert path.name == countdown.FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["days"] == 13
    assert payload["hours"] == 12
    assert payload["raw"] == "剩余 13天 12小时"
    # 时间戳是给眼睛看的（判断是不是今天读的），格式固定成这一种。
    assert len(payload["read_at"]) == 16
    assert payload["read_at"][4] == "-" and payload["read_at"][10] == " "


def test_raw_defaults_to_a_sentence_when_not_given(_isolated_data_dir):
    countdown.save_countdown(3, 4)

    assert countdown.load_countdown()["raw"] == "剩余 3天 4小时"


def test_missing_file_means_not_read_yet(_isolated_data_dir):
    assert countdown.load_countdown() is None
    assert countdown.countdown_text() == "支线刷新：还没读过"


def test_broken_file_does_not_raise(_isolated_data_dir):
    """写坏的文件（半截 JSON / 根本不是 JSON）只能当成"还没读过"。"""

    countdown.countdown_path().write_text("{不是 JSON", encoding="utf-8")

    assert countdown.load_countdown() is None
    assert countdown.countdown_text() == "支线刷新：还没读过"


def test_non_object_json_is_treated_as_missing(_isolated_data_dir):
    countdown.countdown_path().write_text("[1, 2, 3]", encoding="utf-8")

    assert countdown.load_countdown() is None


def test_text_carries_both_numbers_and_the_stamp(_isolated_data_dir):
    countdown.save_countdown(13, 12)

    text = countdown.countdown_text()
    assert text.startswith("支线刷新：剩余 13 天 12 小时")
    assert "读）" in text


def test_text_reports_an_abnormal_reading_instead_of_crashing(_isolated_data_dir):
    """字段类型不对（人手改坏了）⇒ 说"读数异常"，不去拼一句假的倒计时。"""

    countdown.countdown_path().write_text(
        json.dumps({"days": "十三", "hours": 12}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert countdown.countdown_text() == "支线刷新：读数异常"


def test_display_strips_the_year_to_keep_it_on_one_line(_isolated_data_dir):
    """窄条只有 280~340 px 宽，带年份正好折成两行（真机抓图验过）。

    年份对「是不是今天读的」没有信息量 ⇒ 显示时去掉；文件里仍存完整的
    `YYYY-MM-DD HH:MM`（机器读的那份不缩水）。
    """

    countdown.save_countdown(13, 12)
    text = countdown.countdown_text()
    stored = countdown.load_countdown()["read_at"]

    assert text.startswith("支线刷新：剩余 13 天 12 小时（")
    assert " 读）" in text
    assert stored[:4] not in text, f"显示时还带着年份：{text}"
    assert stored.startswith(stored[:4]) and len(stored) == 16, "文件里那份不许缩水"


def test_display_keeps_an_unrecognised_stamp_verbatim(_isolated_data_dir):
    """人手改过的怪格式**原样显示**，不去猜它的年月日。"""

    countdown.countdown_path().write_text(
        json.dumps({"days": 1, "hours": 2, "read_at": "昨天"}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert "（昨天 读）" in countdown.countdown_text()
