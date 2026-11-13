"""本次运行跑到哪了 —— 只给悬浮窄条展示用，不参与任何判据或业务决定。

状态完全在界面层推导：

- 清单来自 ``controller.resolve_plan()``（用户勾了哪几条、按什么顺序）；
- 运行时子进程会打印 ``模式=<路线名>`` 这类行，出现下一条就把上一条记作完成；
- 整轮结束那行「每日任务汇总：…」把状态一次补齐；
- 同一次结算的「每日任务结果：…」逐条明细，由 ``extract_run_result`` 收给结果卡。

⚠️ 这里刻意不碰 ``games/``：解析只用于「给人看」，认错了也不会影响任何点击、
判据、阈值或收工条件。日志格式哪天变了，最坏结果是进度停在原地，不会误操作。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

PENDING = "pending"
RUNNING = "running"
DONE = "done"

STATUS_LABELS = {PENDING: "待执行", RUNNING: "进行中", DONE: "已完成"}


@dataclass(frozen=True)
class RouteProgress:
    """一条路线在窄条里的样子。"""

    mode: str
    label: str
    status: str


class RunProgress:
    """按日志行推进「完成 / 进行中 / 待跑」，只前进不回退。"""

    def __init__(self, routes: Iterable[tuple[str, str]]) -> None:
        self._routes = tuple(RouteProgress(mode, label, PENDING) for mode, label in routes)
        self._statuses = [PENDING] * len(self._routes)
        self._current = -1
        self._finished = False
        if self._routes:
            self._statuses[0] = RUNNING
            self._current = 0
        self._index_by_token: dict[str, int] = {}
        for index, route in enumerate(self._routes):
            self._index_by_token[route.mode] = index
            self._index_by_token[route.label] = index

    @property
    def items(self) -> tuple[RouteProgress, ...]:
        return tuple(
            RouteProgress(route.mode, route.label, self._statuses[index])
            for index, route in enumerate(self._routes)
        )

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def active_label(self) -> str:
        if self._finished or self._current < 0:
            return ""
        return self._routes[self._current].label

    def note_line(self, line: str) -> None:
        """读一行运行日志；只认「模式=」这种带路线名的行，汇总行单独处理。"""
        if not self._routes or self._finished:
            return
        if "每日任务汇总" in line:
            # 整轮结束才会打印这一行，里面每条都跑过（成功或失败都一样）。
            self._statuses = [DONE] * len(self._routes)
            self._current = len(self._routes) - 1
            return
        tail = line.partition("模式=")[2]
        if not tail:
            return
        parts = tail.split(maxsplit=1)
        if not parts:
            return
        index = self._index_by_token.get(parts[0])
        if index is None or index <= self._current:
            # 只前进不回退：同一条路线的日志会反复出现，不能把进度拨回去。
            return
        for previous in range(self._current, index):
            self._statuses[previous] = DONE
        self._statuses[index] = RUNNING
        self._current = index

    def finish(self) -> None:
        """运行结束：当前这条收尾，没轮到的保持「待跑」（手动停止时就是这样）。"""
        self._finished = True
        if 0 <= self._current < len(self._statuses):
            self._statuses[self._current] = DONE


SUMMARY_PREFIX = "每日任务汇总："
RESULT_PREFIX = "每日任务结果："


def extract_run_result(
    lines: Iterable[str],
) -> tuple[str | None, tuple[str, ...]]:
    """从最近日志里取**最后一次**整轮结算：一行老摘要 + 逐条明细。

    只认 ``main._run_daily`` 打印的这两组前缀。以最后一行「每日任务汇总」为界，
    往后的明细才算数 —— 免得把上一次运行残留的行混进结果卡。
    认不出来返回 ``(None, ())``，界面回落成不显示，不会误操作。
    """
    items = list(lines)
    start = next(
        (
            index
            for index in range(len(items) - 1, -1, -1)
            if items[index].startswith(SUMMARY_PREFIX)
        ),
        None,
    )
    if start is None:
        return None, ()
    summary = items[start].split("：", 1)[1].strip()
    details = tuple(
        line.split("：", 1)[1].strip()
        for line in items[start + 1 :]
        if line.startswith(RESULT_PREFIX)
    )
    return summary, details
