"""从可执行计划和 Worker 日志读取运行进度，供桌面界面展示。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

PENDING = "pending"
RUNNING = "running"
DONE = "done"
IDLE = "idle"
SUCCESS = "success"
FAILURE = "failure"
STOPPING = "stopping"
STOPPED = "stopped"
RESOURCE_EXHAUSTED = "resource_exhausted"
SKIPPED = "skipped"
AWAITING_CONFIRMATION = "awaiting_confirmation"

OUTCOME_LABELS = {
    IDLE: "准备执行",
    RUNNING: "进行中",
    SUCCESS: "本轮完成",
    FAILURE: "任务失败",
    STOPPING: "正在安全停止",
    STOPPED: "已停止",
    RESOURCE_EXHAUSTED: "资源耗尽",
    SKIPPED: "有任务跳过",
    AWAITING_CONFIRMATION: "结果待确认",
}

STATUS_LABELS = {PENDING: "待执行", RUNNING: "进行中", DONE: "已结束"}
RESULT_STATUS_LABELS = {
    **OUTCOME_LABELS,
    **STATUS_LABELS,
    SUCCESS: "已完成",
    FAILURE: "失败",
    SKIPPED: "跳过",
}

SUMMARY_PREFIX = "每日任务汇总："
RESULT_PREFIX = "每日任务结果："
PROGRESS_PREFIX = "每日任务进度："
_SUMMARY_ITEM = re.compile(r"(.+?) ([✓✗—])(?=$|\(|\[)")
_CLOSEOUT_WARNING = "[收尾待确认]"
_LIVE_OUTCOMES = {
    "completed": SUCCESS,
    "failed": FAILURE,
    "resource": RESOURCE_EXHAUSTED,
    "awaiting_confirmation": AWAITING_CONFIRMATION,
    "skipped": SKIPPED,
    "not_supported": SKIPPED,
}


@dataclass(frozen=True)
class RouteProgress:
    """一条路线在窄条里的样子。"""

    mode: str
    label: str
    status: str


class RunProgress:
    """记录执行顺序与正式汇总确认的路线结果。"""

    def __init__(self, routes: Iterable[tuple[str, str]]) -> None:
        self._routes = tuple(RouteProgress(mode, label, PENDING) for mode, label in routes)
        self._statuses = [PENDING] * len(self._routes)
        self._current = -1
        self._current_observed = False
        self._finished = False
        self._aborted = False
        self._reported: dict[str, str] = {}
        if self._routes:
            self._statuses[0] = RUNNING
            self._current = 0
        self._index_by_token: dict[str, int] = {}
        for index, route in enumerate(self._routes):
            self._index_by_token[route.mode] = index
            self._index_by_token[route.label] = index

    @property
    def items(self) -> tuple[RouteProgress, ...]:
        """兼容原有进度清单，DONE 表示已离开该路线。"""
        return tuple(
            RouteProgress(route.mode, route.label, self._statuses[index])
            for index, route in enumerate(self._routes)
        )

    @property
    def result_items(self) -> tuple[RouteProgress, ...]:
        """逐路线结果，已离开的路线在收到正式汇总前显示待确认。"""
        return tuple(
            RouteProgress(
                item.mode,
                item.label,
                self._reported.get(
                    item.mode, AWAITING_CONFIRMATION if item.status == DONE else item.status
                ),
            )
            for item in self.items
        )

    @property
    def completed_count(self) -> int:
        return sum(status == SUCCESS for status in self._reported.values())

    @property
    def processed_count(self) -> int:
        """有结论的执行路线数，失败和资源耗尽也占一条。"""
        return sum(status != SKIPPED for status in self._reported.values())

    @property
    def total_count(self) -> int:
        return len(self._routes)

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def active_label(self) -> str:
        return self._routes[self._current].label if self.active_mode else ""

    @property
    def active_mode(self) -> str:
        if self._finished or self._current < 0 or self._statuses[self._current] != RUNNING:
            return ""
        return self._routes[self._current].mode

    def note_line(self, line: str) -> None:
        """识别路线切换、实时结算和整轮汇总。"""
        if not self._routes or self._finished:
            return
        if line.startswith(PROGRESS_PREFIX):
            mode, _, outcome = line.removeprefix(PROGRESS_PREFIX).partition(" ")
            index = self._index_by_token.get(mode)
            status = _LIVE_OUTCOMES.get(outcome)
            if index is not None and status is not None:
                self._record_result(index, status)
            return
        if line.startswith(SUMMARY_PREFIX):
            self._note_summary(line.removeprefix(SUMMARY_PREFIX))
            return
        tail = line.partition("模式=")[2]
        if not tail:
            return
        parts = tail.split(maxsplit=1)
        if not parts:
            return
        index = self._index_by_token.get(parts[0])
        if index is None or index < self._current or self._routes[index].mode in self._reported:
            return
        if index > self._current:
            self._close_current()
            self._current = index
            self._statuses[index] = RUNNING
        self._current_observed = True

    def _note_summary(self, summary: str) -> None:
        body, aborted, _reason = summary.partition(" ｜ 已中止：")
        self._aborted = bool(aborted)
        self._statuses = [PENDING] * self.total_count
        labels = {route.label: index for index, route in enumerate(self._routes)}
        for entry in body.split(" / "):
            entry = entry.strip()
            match = _SUMMARY_ITEM.match(entry)
            if match is None or match[1] not in labels:
                continue
            index = labels[match[1]]
            mark = match[2]
            detail = entry[match.end():]
            if mark == "✓":
                status = {
                    "": SUCCESS,
                    "(无剩余内容)": RESOURCE_EXHAUSTED,
                    _CLOSEOUT_WARNING: AWAITING_CONFIRMATION,
                    f"(无剩余内容){_CLOSEOUT_WARNING}": AWAITING_CONFIRMATION,
                }.get(detail, AWAITING_CONFIRMATION)
            else:
                status = FAILURE if mark == "✗" else SKIPPED
            self._record_result(index, status)
        self._finished = True

    def _record_result(self, index: int, status: str) -> None:
        self._reported[self._routes[index].mode] = status
        self._statuses[index] = PENDING if status == SKIPPED else DONE

    def outcome(self, exit_code: int | None) -> str:
        """结合进程终态与业务汇总给出本轮结论。"""
        if exit_code == 130:
            return STOPPED
        reported = self._reported.values()
        if self._aborted or FAILURE in reported or exit_code not in {0, 2}:
            return FAILURE
        if exit_code == 2 or RESOURCE_EXHAUSTED in reported:
            return RESOURCE_EXHAUSTED
        if AWAITING_CONFIRMATION in reported:
            return AWAITING_CONFIRMATION
        if SKIPPED in reported:
            return SKIPPED
        if self.total_count and self.completed_count == self.total_count:
            return SUCCESS
        return AWAITING_CONFIRMATION

    def _close_current(self) -> None:
        if self.active_mode:
            self._statuses[self._current] = DONE if self._current_observed else PENDING

    def finish(self, *, complete_current: bool = True) -> None:
        """缺少汇总时，只结束已观察到日志的当前路线。

        ``complete_current=False``（手动停止或运行失败）时当前路线退回待执行，
        已结束的路线不受影响。
        """
        if self._finished:
            return
        self._finished = True
        if self._current < 0 or self._routes[self._current].mode in self._reported:
            return
        done = self._current_observed and complete_current
        self._statuses[self._current] = DONE if done else PENDING


# ── 逐条明细的拆分（只给结果卡排版用，不参与任何判据）──────────────────────
# ``daily_tasks.result_lines()`` 打出来的是「名称 · 状态 · 轮次 · 用时 · 原因」这种
# 给人看的短句。结果卡要把一条路线排成一行，就得把这几段拆开。
#
# ⚠️ 状态词在这里**再写一遍**，没有 import ``games.epic7.daily_tasks`` —— 那会把整条
# 运行链路拖进界面进程。词表对不上时 ``parse_result_line`` 返回 None，界面回落成
# 整段文本，一个字都不丢（宁可退回老样子，也不静默吞掉一行）。
RESULT_STATUS_WORDS = frozenset({"完成", "无剩余内容", "失败", "未执行", "当前环境不支持"})
_FAILURE_WORDS = frozenset({"失败", "未执行"})
_NOT_SUPPORTED_NOTE = "当前运行环境不提供此路线"
_DURATION = re.compile(r"^(?:\d+分\d{2}秒|\d+秒)$")
_CYCLES = re.compile(r"^\d+(?:/\d+)? 轮$")
_ELAPSED = re.compile(r"总用时\s*(\d+分\d{2}秒|\d+秒)")
_HEADLINE_PREFIX = "任务 "


@dataclass(frozen=True)
class ResultLine:
    """一条路线在结果卡里的样子。

    ``meta`` 只放能对齐的短字段（轮次、用时）；成句的东西（战绩、做了什么）
    放 ``text``，跟提醒与原因一起走第二行 —— 混进 meta 会把那一行撑长，
    状态列就被挤得跟别的行对不齐。
    """

    label: str
    status: str
    meta: str
    note: str
    reason: str
    text: str = ""


def parse_result_line(line: str) -> ResultLine | None:
    """拆一行明细。拆不出来返回 ``None``（调用方回落成整段文本）。"""
    tokens = [token.strip() for token in line.split(" · ") if token.strip()]
    if len(tokens) < 2 or tokens[1] not in RESULT_STATUS_WORDS:
        return None
    label, status, rest = tokens[0], tokens[1], tokens[2:]
    notes = [token for token in rest if token.startswith("收尾待确认")]
    rest = [token for token in rest if not token.startswith("收尾待确认")]
    if status == "当前环境不支持":
        rest = [token for token in rest if token != _NOT_SUPPORTED_NOTE]
    # 失败与未执行的那句原因排在最后（见 ``DailyReport._outcome_line`` 的拼接顺序），
    # 而「用时」也是这个位置 —— 靠形状区分：用时永远是「N秒 / N分NN秒」。
    reason = ""
    if status in _FAILURE_WORDS and rest and not _DURATION.match(rest[-1]):
        reason = rest.pop()
    meta = [token for token in rest if _DURATION.match(token) or _CYCLES.match(token)]
    text = [token for token in rest if token not in meta]
    return ResultLine(
        label,
        status,
        " · ".join(meta),
        notes[0] if notes else "",
        reason,
        "；".join(text),
    )


def parse_result_details(
    lines: Iterable[str],
) -> tuple[tuple[ResultLine, ...], str, tuple[str, ...]]:
    """把多行明细拆成（逐条结果, 总账行, 其余说明）。

    其余说明目前包含账号两行、中止原因与收尾巡检那句 —— 界面只用得上中止原因。
    """
    rows: list[ResultLine] = []
    extra: list[str] = []
    headline = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parsed = parse_result_line(line)
        if parsed is not None:
            rows.append(parsed)
        elif line.startswith(_HEADLINE_PREFIX) and _ELAPSED.search(line):
            headline = line
        else:
            extra.append(line)
    return tuple(rows), headline, tuple(extra)


def elapsed_of(headline: str) -> str:
    match = _ELAPSED.search(headline)
    return match.group(1) if match else ""


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
