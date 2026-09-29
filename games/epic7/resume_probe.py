"""开局接力探针的**共用零件**：落点类型 + 「重判页面 → 命中就接管」的执行器。

## 为什么要有它（2026-09-30）

8 条路线的 ``detect_resume_point`` 各自回答同一个问题：「这一帧上，人停在本路线的哪一步？」
它们的**判据**当然不同（有的重判页面、有的看状态机状态、有的问导航器），但有两样东西
是逐字重复的：

1. **落点类型**：8 条路线各写了一份一模一样的 3 字段 ``XxxResumePoint(NamedTuple)``，
   连字段注释都一字不差。=> 收成这里的 ``ResumePoint``，各路线直接用。
2. **「重判页面 → 命中就接管」这种形态**：圣域收菜 / 骑士团捐赠 / 迷宫强化石三条
   一字不差地写着同一段控制流（先判 None、再判落点、必要时补 ``entry`` 或
   ``mark_entered()``）。=> 收成 ``observe_page_probe()``。

⚠️ **「按顺序问一串判据」那一种形态故意没有抽**（远征 / 主线 / 竞技场 / 世界首领战）：
它们的判据分别是「状态机自己认页」「按锚点名认页」「问导航器」，逐个不同；抽成
``first_hit(order, lambda ...)`` 只会把直白的 ``for`` 循环换成 lambda，**没有去掉任何重复**，
却把每条顺序表旁边那句「为什么这么排」的注释推远了。项目自己的结论也是
「只共享逐字相同的机制，循环策略各留各的」（见 ``docs/TODO.md`` 的可扩展性条目）。
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple, Optional

import numpy as np


class ResumePoint(NamedTuple):
    """接力落点：认出停在哪儿之后，调用方据此决定「怎么接着往下跑」。

    ⚠️ 这是**路线侧构造用**的形状，与 ``modes.ResumePoint`` 字段同名同义 —— 后者是对外的
    公开形状，``modes._resume_probe`` 负责把前者归一化过去（``state`` 是枚举就取 ``.value``）。
    两者不合并是因为 ``modes`` 会 import 各路线，而各路线不能反过来 import ``modes``（成环）。
    """

    page: str                       # 中文页面名，给日志和诊断看
    state: Any = None               # 要拨过去的状态机状态；None = 不动状态机
    entry: Optional[str] = None     # 非空 = 已经在导航链的某一级上，从这里接着导航


def observe_page_probe(
    machine: Any,
    screen: np.ndarray,
    *,
    resumable: Any,
    label: Callable[[Any], str],
    entry_page: Any = None,
    entry: str = "",
    after_entry: Any = (),
) -> Optional[ResumePoint]:
    """「重判页面 → 命中就接管」这一形态的执行器。

    控制流（三条路线原先逐字相同的那段）：

    1. ``observe_page`` 认不出、或认出的页**不在** ``resumable`` 里 -> 返回 None（不接力，
       调用方照旧走「回大厅 → 重新导航」）；
    2. 认出的页在 ``after_entry`` 里 -> 先调 ``machine.mark_entered()``（迷宫那条需要：停在
       已经进过迷宫的页面上，不记这一笔会被当成「还没进场」）；
    3. 认出的页正是 ``entry_page`` -> 落点额外带上 ``entry``（那一页在导航链上，从这里接着
       导航能省掉一次点击）；
    4. 否则 -> 只给页面名的落点。

    ⚠️ ``resumable`` 必须包含 ``entry_page`` —— 否则第 3 步永远走不到（先被第 1 步拦掉）。
    ⚠️ ``state`` 恒为 None：这三条路线都是**每帧重判页面**，拨了下一帧就被覆盖，留着只会
    制造「日志说拨到了 A、实际画面是 B」的假象。
    """
    page = machine.observe_page(screen)
    if page is None or page not in resumable:
        return None
    if after_entry and page in after_entry:
        machine.mark_entered()
    if entry_page is not None and page is entry_page:
        return ResumePoint(page=label(page), entry=entry)
    return ResumePoint(page=label(page))
