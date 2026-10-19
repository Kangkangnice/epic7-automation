"""版本检查：**只提示，不下载、不静默更新**。

## 为什么要有、以及为什么只做这么多

游戏一改版，模板就会整体失效。没有版本检查时，用户的处境是「昨天还能用，今天就报
一堆认不出页面」，而他并不知道这可能是版本问题。所以启动时顺手看一眼有没有新版，
有就在界面上留一行「点这里查看」。

但这一行**只到「告诉你去哪看」为止**：

- 不自动下载、不自动替换文件 —— 自动更新等于在用户机器上执行新代码，那是另一件
  需要被认真设计（签名、回滚、断点续传）的事，不是这个版本该顺手做掉的；
- 不弹模态窗、不拦启动 —— 用户此刻可能急着跑日常，一个「有新版本」的弹窗只会碍事；
- 连不上就当没这回事 —— 局域网、代理、公司网络都可能访问不到 GitHub，
  一次静默失败不该变成一次报错。

## 频率

成功查到后 **24 小时**内不再查；查失败后 **6 小时**再试（网络抖动不该让用户等一天）。
状态存在运行产物目录（`core/data_paths.py` 定的那个根），装到只读目录也不受影响。

设环境变量 ``EPIC7_DISABLE_UPDATE_CHECK=1`` 可整体关掉 —— 离线部署、或不希望程序
任何时刻联网的用户，有权利彻底关掉它。

## 版本号怎么比

只认 `tag_name` 里的数字段：`v0.2.0` 与 `0.2.0` 等价。数字段相同时，**正式版比预发布新**
（`0.1.0` 比 `0.1.0-dev` 新，反之不成立）。解析不了的版本号一律**不提示** ——
宁可漏报一次，也不要因为解析错而天天喊「有新版本」。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

#: GitHub 的「最新正式发布」接口。跟着仓库走，不在别处再写一份。
RELEASES_API = (
    "https://api.github.com/repos/Kangkangnice/epic7-automation/releases/latest"
)
#: 用户点「查看」时打开的页面（比 API 地址更适合给人看）。
RELEASES_PAGE = "https://github.com/Kangkangnice/epic7-automation/releases/latest"

DISABLE_ENV = "EPIC7_DISABLE_UPDATE_CHECK"
STATE_FILENAME = "update_check.json"

#: 网络超时。启动路径上的事，宁可放弃也不要拖住界面。
TIMEOUT_SECONDS = 5.0
#: 查到之后隔多久再查 / 查失败之后隔多久再试。
SUCCESS_INTERVAL = timedelta(hours=24)
FAILURE_INTERVAL = timedelta(hours=6)

#: 大小写都认：标签写成 `V0.2.0` 的仓库不少，为这点差异放弃整次比较不划算。
_VERSION_PATTERN = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-+](.+))?$", re.IGNORECASE)


@dataclass(frozen=True)
class UpdateInfo:
    """「有新版可用」。只带信息，不带任何可执行动作。"""

    current: str
    latest: str
    url: str


def parse_version(text: str) -> tuple[tuple[int, ...], str] | None:
    """`v0.2.0` → `((0, 2, 0), "")`；`0.1.0-dev` → `((0, 1, 0), "dev")`。

    解析不了返回 `None` —— 调用方当作「不比较」。
    """
    if not isinstance(text, str):
        return None
    match = _VERSION_PATTERN.match(text.strip())
    if match is None:
        return None
    numbers = tuple(int(part) for part in match.group(1).split("."))
    return numbers, (match.group(2) or "")


def is_newer(current: str, latest: str) -> bool:
    """`latest` 是不是比 `current` 新。任何一边解析不了都返回 `False`。"""
    parsed_current = parse_version(current)
    parsed_latest = parse_version(latest)
    if parsed_current is None or parsed_latest is None:
        return False
    current_numbers, current_suffix = parsed_current
    latest_numbers, latest_suffix = parsed_latest
    if current_numbers != latest_numbers:
        return latest_numbers > current_numbers
    # 数字段一样：只有「从预发布升到正式版」算新（0.1.0-dev → 0.1.0）。
    return bool(current_suffix) and not latest_suffix


def fetch_latest_release(
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = TIMEOUT_SECONDS,
) -> tuple[str, str] | None:
    """问一次 GitHub，返回 `(版本号, 页面地址)`；任何问题都返回 `None`。

    ⚠️ 这里**必须**把异常全部吞掉：调用方在启动路径上，一次网络异常不该让程序起不来。
    """
    request = Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "epic7-auto-assistant",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 —— 网络、DNS、TLS、JSON 坏了，全都当「没查到」
        return None
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        return None
    url = payload.get("html_url")
    page = url if isinstance(url, str) and url.startswith("https://") else RELEASES_PAGE
    return tag.strip(), page


def state_path(data_root: Path) -> Path:
    return data_root / STATE_FILENAME


def _read_state(data_root: Path) -> dict:
    try:
        payload = json.loads(state_path(data_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(data_root: Path, payload: Mapping[str, object]) -> None:
    """写失败就算了 —— 版本检查是锦上添花，不该因为写不进文件而报错。"""
    path = state_path(data_root)
    temp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)


def _last_checked(state: Mapping[str, object]) -> datetime | None:
    raw = state.get("checked_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def due_for_check(
    state: Mapping[str, object],
    now: datetime,
) -> bool:
    """这次启动该不该问一次。上次是成功还是失败，决定等 24 小时还是 6 小时。"""
    last = _last_checked(state)
    if last is None:
        return True
    interval = SUCCESS_INTERVAL if state.get("outcome") == "ok" else FAILURE_INTERVAL
    return now - last >= interval


def check_for_update(
    current_version: str,
    data_root: Path,
    *,
    fetch: Callable[[], tuple[str, str] | None] = fetch_latest_release,
    now: Callable[[], datetime] = datetime.now,
    environ: Mapping[str, str] | None = None,
) -> UpdateInfo | None:
    """该查就查一次；有更新返回 `UpdateInfo`，否则 `None`。

    **不抛异常**：这条路径在启动时跑，任何意外都只意味着「这次不提示」。
    """
    env = os.environ if environ is None else environ
    if env.get(DISABLE_ENV, "").strip() not in ("", "0", "false", "False"):
        return None

    moment = now()
    state = _read_state(data_root)
    if not due_for_check(state, moment):
        return None

    release = fetch()
    record: dict[str, object] = {"checked_at": moment.isoformat(timespec="seconds")}
    if release is None:
        record["outcome"] = "failed"
        _write_state(data_root, record)
        return None

    tag, url = release
    record.update({"outcome": "ok", "latest": tag, "url": url})
    _write_state(data_root, record)

    if not is_newer(current_version, tag):
        return None
    return UpdateInfo(current=current_version, latest=tag, url=url)


__all__ = [
    "DISABLE_ENV",
    "RELEASES_PAGE",
    "UpdateInfo",
    "check_for_update",
    "due_for_check",
    "fetch_latest_release",
    "is_newer",
    "parse_version",
    "state_path",
]
