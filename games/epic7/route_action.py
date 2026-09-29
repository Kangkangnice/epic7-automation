"""路线上「点一次」这件事的**唯一字段契约**。

## 为什么要有它（2026-09-30）

每条路线原先各自声明一份 ``XxxAction`` dataclass，字段名与顺序都能自由漂移。实测的后果
不是「看起来乱」，而是**契约静默失效**：

- 世界首领战的 ``in_page_evidence`` 是 2026-09-24 才补的，补之前它**根本不存在**：那条
  路线有 5 个同页动作**事实上**都有验收判据（下一帧重判画面），但判据写在 ``next_action``
  的代码里、没有以字段形式登记。于是契约开关一开（规则是「``target_pages`` **或**
  ``in_page_evidence``」）它们全被拒发 —— **规则里的备选项根本不存在**。
- 英雄合成用的是 ``source_observation``，机器认的是 ``in_page_evidence``。两个名字指同一件
  事，所以它至今进 ``TRANSITION_EXEMPT``（理由就写着「字段名要先对齐」）。
- 竞技场按**位置**传 5 个参数，第 3 个是自己的 ``source_state``；而契约里第 3 个位置是
  ``source_page``。字段一重排，一个枚举会被静默当成页面名，**不报错**。

=> 把「转场契约」那 6 个字段收成一份基类，各路线只声明自己**额外**的东西。字段名从此
只有一处，加字段也只有一处。

## 位置参数：只允许前两个

``name`` 与 ``point`` 可以按位置传，**其余一律用关键字**。这不是风格要求，是安全要求 ——
理由就是上面第三条。``tests/test_route_actions.py`` 用 AST 把这条钉死：任何
``*Action(...)`` 调用只要超过 2 个位置参数就红。

## 与「表态」的关系

继承本基类**不会**让一条路线自动达标：``target_pages`` / ``in_page_evidence`` 仍然要
**填内容**才算有验收依据。所以 ``@_REQUIRE_TRANSITION_CONTRACT`` 与
``TRANSITION_EXEMPT`` 那套「二选一表态」照旧，本模块只负责让字段名不可能漂。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteAction:
    """一条路线上「点一次」的全部事实（= ``runner_base`` 认的那份转场契约）。"""

    name: str
    point: tuple[int, int]
    # 来源页。换页动作靠它与下一帧的 ``machine._confirmed_page`` 对账。
    source_page: str = ""
    # 允许到达的目标页（换页动作用；与 ``in_page_evidence`` 至少填一个）。
    target_pages: tuple[str, ...] = ()
    # 不换页动作的出口验收依据（同页动作用）。
    in_page_evidence: str = ""
    # 日志里的「判断依据」。给人看，不参与机器判定。
    reason: str = ""
