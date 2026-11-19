"""试算（``preview``）用的业务状态快照：按对象属性自动抓取 / 还原。

审查 E：社区路线原先用 31 项手工元组，新增字段漏一次就会「试算把真跑的账烧掉」。
这里把「抓哪些字段」改成「排除哪些只读字段」，以后新增业务字段默认就在快照里。

只依赖标准库，接口稳定；因此纳入 mypy 检查（见 ``pyproject.toml`` 的 files）。
"""

from __future__ import annotations

import copy
from typing import Any, Mapping


def snapshot(obj: object, *, stable: frozenset[str]) -> dict[str, Any]:
    """深拷贝 ``obj.__dict__``，跳过运行期只读的 ``stable`` 字段。"""
    return {
        name: copy.deepcopy(value)
        for name, value in vars(obj).items()
        if name not in stable
    }


def restore(
    obj: object,
    snapshot: Mapping[str, Any],
    *,
    stable: frozenset[str] = frozenset(),
) -> None:
    """把对象还原到快照时刻：写回旧字段，**并删掉预览期间新长出来的字段**。

    只写回不够（审查 E 的复验反例）：子类在 ``next_action`` 里首次创建
    ``self.xxx`` 后抛错，``finally`` 恢复时旧字段回来了，新字段却留在机器上，
    下一次真跑会把它当成上一轮留下的账本。``stable`` 是快照本就排除的只读
    基础设施（模板、字形、计划），它们不参与增删。
    """
    for name in set(vars(obj)) - set(snapshot) - set(stable):
        delattr(obj, name)
    for name, value in snapshot.items():
        setattr(obj, name, value)
