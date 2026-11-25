"""账号：用游戏昵称当标识，数据按号分目录。

## 为什么用昵称（用户 2026-11-23 定）

大厅左上角就写着当前登录的是谁。每趟巡检本来就要从大厅走进去，顺手 OCR 读一次
即可 —— 用户零操作，不需要选号、不需要起名、也不会忘。原先那套「界面下拉选大号
小号」在评审时被否掉：多一个动作就多一次忘记的机会，而且名字还得用户自己想。

## 三条硬约定

1. **账号为空 = 未识别**，所有路径回到加账号之前的位置。单号用户零感知，现有
   存档与测试一个字节都不用改。
2. **目录名必须净化**。昵称是玩家自己起的，可能含 ``/ \\ : * ? " < > |``、``..``
   或 Windows 保留名 —— 直接拼路径会写到数据根之外，或在那台机器上根本建不出来。
   净化只改目录名，**显示一律用原名**。
3. **本模块不碰 OCR**。识别在 ``games/epic7/account_profile.py``，这里只管名字与
   路径，因此可以被 core 层（倒计时）直接引用，不引入图像依赖。

## 昵称会变的那两件事

改名 = 新账号，旧数据留在旧名字下（用户知情）。改等级不影响归属 —— 等级只用于
显示，**不参与分号**，因为它随时会变。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from auto_game_unified.core.data_paths import data_root

ACCOUNTS_DIRNAME = "accounts"
LAST_FILENAME = "last_account.json"
MAX_NAME_LEN = 32
# 这一趟运行登录的是谁 —— **进程级**设置，与 ``EPIC7_DATA_DIR`` / ``EPIC7_ACCOUNT``
# 同一套路数：界面起子进程时写、子进程里所有模块直接读，不必穿过每一层函数签名。
# 这样新增一条要记账的路线，拿账号是零成本的（用户 2026-11-23 明确要求的开发体验）。
ACCOUNT_ENV = "EPIC7_ACCOUNT"
ACCOUNT_RANK_ENV = "EPIC7_ACCOUNT_RANK"

# Windows 不允许出现在文件名里的字符。昵称里出现就把它们换成下划线。
_ILLEGAL = '<>:"/\\|?*'
# 保留设备名：即使在目录里也建不出来（CON 会变成控制台设备）。
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalize(name: object) -> str:
    """把玩家昵称变成可以作为目录名的形式；净化后为空 ⇒ 返回空串（当未识别）。

    ⚠️ 只做「能不能安全建目录」这一件事：不转小写、不去重音、不做音译。
    多做一步转换就等于给同一个号造出第二个目录，那正是要避免的混乱。
    """

    if not isinstance(name, str):
        return ""
    text = name.strip()
    if not text:
        return ""
    cleaned = "".join("_" if ch in _ILLEGAL or ord(ch) < 32 else ch for ch in text)
    # ``..`` 会被当成「上一级目录」；换成下划线后仍保持可读。
    cleaned = cleaned.replace("..", "__")
    # Windows 会悄悄吃掉结尾的点和空格，导致「看起来一样、实际两个目录」。
    cleaned = cleaned.rstrip(". ")
    cleaned = cleaned.strip()
    if not cleaned:
        return ""
    # 净化之后只剩占位下划线（``..`` / ``///`` 这类）⇒ 没有区分度，按未识别处理：
    # 否则两个不同的符号昵称会落到同一个 ``__`` 目录里，正好是要避免的混乱。
    if not cleaned.strip("_"):
        return ""
    if cleaned.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:MAX_NAME_LEN]


def current_account() -> str:
    """这一趟运行登录的是谁；未识别（或还没读）返回空串。

    ⚠️ 读的是进程级环境变量，**不是** ``last_account.json``：那个文件说的是
    「上一次跑的是谁」，而这里要的是「我正在跑的是谁」，两者在换号那一刻会不同。
    """

    return normalize(os.environ.get(ACCOUNT_ENV, ""))


def current_rank() -> str:
    """与 ``current_account`` 同源的账号等级；只用于显示，不参与任何判据。"""

    return str(os.environ.get(ACCOUNT_RANK_ENV, "") or "")


def set_current(account: object, rank: str = "") -> None:
    """把「这次是谁」写进进程环境；``account`` 为空表示未识别（会清掉等级）。"""

    cleaned = normalize(account)
    os.environ[ACCOUNT_ENV] = cleaned
    os.environ[ACCOUNT_RANK_ENV] = str(rank or "") if cleaned else ""


def account_dir(name: object) -> Path | None:
    """该账号的数据目录；未识别时返回 ``None``（调用方据此走老路径）。"""

    cleaned = normalize(name)
    if not cleaned:
        return None
    return data_root() / ACCOUNTS_DIRNAME / cleaned


def account_file(name: object, filename: str, *, fallback: Path) -> Path:
    """账号目录下的某个文件；未识别时用调用方给的老路径。

    ``fallback`` 由调用方自己定，因为倒计时与买票锁原本就不在同一个目录下
    （一个在数据根，一个在 ``runtime_logs``）—— 加账号不该顺手把老文件搬家。
    """

    directory = account_dir(name)
    return fallback if directory is None else directory / filename


def save_last(name: object, rank: str = "") -> Path:
    """记下「最近一次运行是谁」，只给界面展示用（便签要写明这读数属于谁）。

    单独一个指针文件，而不是把账号写进倒计时文件：读数可能读不到（那趟没有
    倒计时），但「这次是谁」依然成立，两者生命周期不同。
    """

    path = data_root() / LAST_FILENAME
    payload = {"account": str(name or ""), "rank": str(rank or "")}
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    return path


def load_last() -> dict[str, Any] | None:
    """读回「最近一次运行是谁」；没有/读坏返回 ``None``（界面按未识别显示）。"""

    path = data_root() / LAST_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
