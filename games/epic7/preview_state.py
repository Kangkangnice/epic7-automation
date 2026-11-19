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


def restore(obj: object, snapshot: Mapping[str, Any]) -> None:
    for name, value in snapshot.items():
        setattr(obj, name, value)
