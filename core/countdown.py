"""支线故事刷新倒计时：单独存一个文件，界面上挂在「今日游戏便签」的待办下面。

为什么要单独存：这是**每天跑完支线巡检**顺手读回来的一句话，跟「本次运行」的进度、
跟用户手写的待办都不是同一类东西；塞进 session.json 会让两边的读写互相打扰。

数据形如::

    {"days": 13, "hours": 12, "raw": "剩余 13天 12小时",
     "moonlight_free": true, "read_at": "2026-11-12 23:40"}

``moonlight_free`` 是**同一趟巡检顺手读的**第二件事（2026-11-15 用户要求）：
月光剧场入口卡左上角有没有绿色 F —— 有 = 今天的免费观览已更新，没有 = 已经用掉。
``None`` 表示这趟没走到能看见那张卡的那一页（**不等于"没有"**，所以不显示）。

读坏/缺失一律返回 None（界面显示「还没读过」），**不抛错**：这是便签，不是业务。

## 按账号分开存（2026-11-23 用户要求）

两个号交替跑时，谁先跑谁把读数盖掉，看到的就是另一个号的倒计时。现在每份读数
落在 ``accounts/<昵称>/`` 下，账号由大厅左上角的昵称自动识别（见
``games/epic7/account_profile.py``）。

* 账号为空（那趟没读到昵称）⇒ 仍旧写数据根下的老文件，界面显示「未识别账号」。
  **这是单号用户的完整退路**：不点头、不选号，行为与加账号之前逐字相同。
* 界面要看「最近一次是谁」，所以另有一个 ``last_account.json`` 指针（由
  ``core.account`` 管）。它和读数分开，因为读数可能读不到，而「这次是谁」依然成立。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from auto_game_unified.core.account import (
    ACCOUNTS_DIRNAME,
    account_file,
    current_account,
    current_rank,
    load_last,
    save_last,
)
from auto_game_unified.core.data_paths import data_root

FILENAME = "side_story_countdown.json"

# 便签上挨着倒计时显示的那半句（用户 2026-11-15 说法：「表示今天月光剧场免费已更新」）。
# 只在**真读到**时才出现：没走到那一页就不写，绝不拿"没看见"冒充"没有"。
MOONLIGHT_FREE_ON = "月光剧场免费已更新"
MOONLIGHT_FREE_OFF = "月光剧场免费已用"


def countdown_path(account: str = "") -> Path:
    """倒计时文件的落点。

    有账号 ⇒ ``accounts/<昵称>/side_story_countdown.json``；
    账号为空 ⇒ 与加账号之前完全相同的路径（单号用户零感知）。
    """

    return account_file(account, FILENAME, fallback=data_root() / FILENAME)


def save_countdown(
    days: int,
    hours: int,
    raw: str = "",
    moonlight_free: bool | None = None,
    account: str | None = None,
    rank: str | None = None,
) -> Path:
    """写一次读数。``read_at`` 用本机时间，界面直接展示，便于判断是不是今天的。

    ``account`` / ``rank`` 只用于「这份读数属于谁」，不参与任何业务判断；
    等级随时会变，所以**不**进目录名、也不进文件名。

    ``None``（默认）表示「取这一趟运行的账号」（``core.account.current_account``）：
    调用方不必为「我这条路线怎么拿到账号」发愁 —— 那是进程级上下文，不是路线参数。
    """

    account = current_account() if account is None else account
    rank = current_rank() if rank is None else rank
    path = countdown_path(account)
    payload = {
        "account": account,
        "rank": rank,
        "days": int(days),
        "hours": int(hours),
        "raw": raw or f"剩余 {days}天 {hours}小时",
        "moonlight_free": moonlight_free,
        "read_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if account:
        # 老文件里没有 accounts 目录，第一次写账号才建；建不出来就让异常照旧冒出去，
        # 由调用方兜住（``main._read_period_countdown`` 的契约是「失败不影响整轮」）。
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_last(account, rank)
    return path


def load_countdown(account: str = "") -> dict[str, Any] | None:
    """读回上次的读数；没有/读坏返回 None。"""

    path = countdown_path(account)
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

    ⚠️ 账号名放在最前面（2026-11-23 用户要求）：两个号交替跑时，用户必须一眼
    看出**这段读数属于谁**，否则会拿另一个号的天数做决定。没有账号（老存档或那趟
    没读到昵称）时如实写「未识别账号」，不省略这一段 —— 省略就等于假装它是自己的。
    """

    last = load_last() or {}
    account = str(last.get("account", "") or "")
    rank = str(last.get("rank", "") or "")
    payload = load_countdown(account)
    if not payload:
        return "支线刷新倒计时：尚未读取"
    days = payload.get("days")
    hours = payload.get("hours")
    read_at = str(payload.get("read_at", ""))
    if isinstance(days, int) and isinstance(hours, int):
        stamp = f"（读取时间 {_short_stamp(read_at)}）" if read_at else ""
        body = (
            f"支线刷新倒计时：剩余 {days} 天 {hours} 小时{stamp}"
            f"{moonlight_suffix(payload)}"
        )
        return f"{_owner_prefix(account, rank)}{body}"
    return "支线刷新倒计时：读数异常"


def _owner_prefix(account: str, rank: str) -> str:
    """``康康626（S.Rank.20）｜`` / ``未识别账号｜``。

    ⚠️ **从没有过任何账号的用户，一个字都不加**（``accounts`` 目录不存在就是这个
    意思）。单号用户升级后打开界面，看到的仍是原来那一行 —— 不能因为他没用过这个
    功能，就平白多出一句「未识别账号」。
    """

    if not account:
        return "未识别账号｜" if _any_account_seen() else ""
    return f"{account}（{rank}）｜" if rank else f"{account}｜"


def _any_account_seen() -> bool:
    """有没有任何一个账号跑过（目录由 ``save_countdown`` 在首次有账号时创建）。"""

    return (data_root() / ACCOUNTS_DIRNAME).is_dir()


def moonlight_suffix(payload: dict[str, Any] | None) -> str:
    """挨着倒计时那半句「月光剧场免费…」；没读到/旧文件没有这个键 ⇒ 空串。

    两个消费者共用这一处文案：便签那一行（``countdown_text``）与每日任务汇总那一行
    （``daily_tasks._run_inspect``）。文案只写在常量里，改口径只改一个地方。
    """

    if not payload:
        return ""
    flag = payload.get("moonlight_free")
    if flag is True:
        return f"｜{MOONLIGHT_FREE_ON}"
    if flag is False:
        return f"｜{MOONLIGHT_FREE_OFF}"
    return ""


def _short_stamp(read_at: str) -> str:
    """`YYYY-MM-DD HH:MM` → `MM-DD HH:MM`；认不出格式就原样返回（不猜）。"""

    head, sep, tail = read_at.partition("-")
    if sep and len(head) == 4 and tail:
        return tail
    return read_at
