"""支线故事刷新倒计时：单独存一个文件，界面上挂在「今日游戏便签」的待办下面。

为什么要单独存：这是**每天跑完支线巡检**顺手读回来的一句话，跟「本次运行」的进度、
跟用户手写的待办都不是同一类东西；塞进 session.json 会让两边的读写互相打扰。

数据形如::

    {"days": 13, "hours": 12, "raw": "剩余 13天 12小时", "read_at": "2026-11-12 23:40"}

读坏/缺失一律返回 None（界面显示「还没读过」），**不抛错**：这是便签，不是业务。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from auto_game_unified.core.data_paths import data_root

FILENAME = "side_story_countdown.json"


def countdown_path() -> Path:
    """倒计时文件的落点（与 session.json 同一个数据根）。"""

    return data_root() / FILENAME


def save_countdown(days: int, hours: int, raw: str = "") -> Path:
    """写一次读数。``read_at`` 用本机时间，界面直接展示，便于判断是不是今天的。"""

    path = countdown_path()
    payload = {
        "days": int(days),
        "hours": int(hours),
        "raw": raw or f"剩余 {days}天 {hours}小时",
        "read_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_countdown() -> dict[str, Any] | None:
    """读回上次的读数；没有/读坏返回 None。"""

    path = countdown_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def countdown_text() -> str:
    """界面那一行的文案。

    ⚠️ 时间戳在显示时**去掉年份**（`2026-11-12 23:40` → `11-12 23:40`）：这一行
    挂在待办下面的窄条里，宽度只有 280~340 px，带上年份正好折成两行（真机抓图
    验过）。年份对「是不是今天读的」没有信息量，加上去只是把一行挤成两行。
    """

    payload = load_countdown()
    if not payload:
        return "支线刷新倒计时：尚未读取"
    days = payload.get("days")
    hours = payload.get("hours")
    read_at = str(payload.get("read_at", ""))
    if isinstance(days, int) and isinstance(hours, int):
        stamp = f"（读取时间 {_short_stamp(read_at)}）" if read_at else ""
        return f"支线刷新倒计时：剩余 {days} 天 {hours} 小时{stamp}"
    return "支线刷新倒计时：读数异常"


def _short_stamp(read_at: str) -> str:
    """`YYYY-MM-DD HH:MM` → `MM-DD HH:MM`；认不出格式就原样返回（不猜）。"""

    head, sep, tail = read_at.partition("-")
    if sep and len(head) == 4 and tail:
        return tail
    return read_at
