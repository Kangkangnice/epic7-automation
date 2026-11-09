"""会话存档：记住上次勾了哪几条、每条几次、窗口后端、上次跑成什么样。

## 为什么有这个模块（2026-10-22 用户拍板）

界面过去**一行都不落盘**：关掉助手再打开，勾选与次数全部回到默认（一条都不勾）。
用户每天都要重勾一遍，这是纯摩擦。竞品有「保存 / 读取 / 转移 / 替换 / 删除」五件套，
本期只做最小的一层：**记住上次**，外加把上次那一行汇总留下来。

## 三条硬约定（改这个文件前必读）

1. **读坏了不许崩**：文件缺失、JSON 坏了、被人手改花了 —— 一律返回 ``None``，
   界面照旧「一条都不勾」。这里抛异常会让助手打不开，代价远大于丢一次勾选。
2. **路线名与次数都要按 ``MODE_SPECS`` 校验**：手改过的文件不能让界面进入非法状态
   （不存在的路线、负数次数、只读路线被改成别的值 —— 全部退回默认）。
3. **只存「用户视角」的东西**：勾选、次数、后端、输入通道、上次结果。
   路线内部参数这里**只原样搬运、不解释**（见 ``params``）—— 哪些参数有意义由各路线
   自己声明，本模块不认任何具名路线，将来加参数不用回来改这里。

## 为什么不存「进度」

``resume_probe`` 那套是**认画面**接力，不是存数字。两件事不要混：
本文件只管「你上次是怎么配的」，不管「上次跑到第几步」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from auto_game_unified.core.pc_window import (
    PC_INPUT_FOREGROUND,
    PC_INPUT_MODES,
)

SESSION_FILENAME = "session.json"
SESSION_VERSION = 1


@dataclass(frozen=True)
class LastRun:
    """上一次运行的结果摘要。``at`` 是给人看的时间串，不是时间戳。"""

    at: str
    summary: str
    exit_code: int | None = None


@dataclass(frozen=True)
class SessionState:
    """界面需要记住的全部东西。字段全是**界面视角**，与路线实现无关。"""

    # 勾选是**有序**的（勾选先后 = 执行顺序），所以是 tuple 而不是 set。
    selection: tuple[str, ...] = ()
    cycles: Mapping[str, int] = field(default_factory=dict)
    backend: str = "emulator"
    # PC 端输入通道：foreground=抢前台 / background=不抢前台。
    # 和勾选/后端一样「记住上次」；坏值一律退回 foreground（约定 2 的同一条）。
    # ⚠️ 保留默认约束：全新安装、旧存档缺这个字段时，绝不能默认成后台通道。
    pc_input_mode: str = PC_INPUT_FOREGROUND
    last_run: LastRun | None = None
    # 路线内部参数的口袋：``{路线名: {参数名: 值}}``。
    # 现在没有任何路线往里写，但格式先定死 —— 将来加参数只加内容，不改结构。
    params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # 窗口位置与大小：``{"x", "y", "w", "h"}``。None = 还没记过，用默认摆放。
    window: Mapping[str, int] | None = None


def session_path(root: Path) -> Path:
    """会话文件的位置：与 consent.json / 日志同一个运行产物根。"""
    return Path(root) / SESSION_FILENAME


def _clean_selection(raw: object, specs: Mapping[str, Any]) -> tuple[str, ...]:
    """勾选名：只留已知路线，重复的只算第一次（顺序就是执行顺序）。"""
    selection: list[str] = []
    if isinstance(raw, list):
        for name in raw:
            if isinstance(name, str) and name in specs and name not in selection:
                selection.append(name)
    return tuple(selection)


def _clean_cycles(raw: object, specs: Mapping[str, Any]) -> dict[str, int]:
    """次数：只读路线、越界值一律退回该路线的默认值 —— 不让坏文件带出非法状态。"""
    cycles: dict[str, int] = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            spec = specs.get(name) if isinstance(name, str) else None
            if spec is None or isinstance(value, bool) or not isinstance(value, int):
                continue
            if not spec.cycles_editable or value < spec.min_cycles:
                cycles[name] = spec.default_cycles
            else:
                cycles[name] = value
    return cycles


def _clean_params(raw: object, specs: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """路线参数：**只搬不解释** —— 哪些参数有意义由路线自己说了算。"""
    params: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(name, str) and name in specs and isinstance(value, dict):
                params[name] = dict(value)
    return params


def load(path: Path) -> SessionState | None:
    """读出上次的状态；任何不可用的情形一律返回 ``None``（约定 1）。"""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    # 延迟 import：与 worker.py 同一个理由（desktop ⇄ games 不要在这个层面互相拉）。
    from auto_game_unified.games.epic7.modes import MODE_SPECS

    selection = _clean_selection(payload.get("selection"), MODE_SPECS)
    cycles = _clean_cycles(payload.get("cycles"), MODE_SPECS)
    params = _clean_params(payload.get("params"), MODE_SPECS)

    backend = payload.get("backend")
    if not isinstance(backend, str) or not backend:
        backend = "emulator"

    # 输入通道只认两种：手改坏 / 版本升级后残留的怪值一律退回前台 ——
    # 不能让一份坏存档把助手悄悄送进「点了没反应」的后台通道。
    raw_input_mode = payload.get("pc_input_mode")
    pc_input_mode = (
        raw_input_mode
        if isinstance(raw_input_mode, str) and raw_input_mode in PC_INPUT_MODES
        else PC_INPUT_FOREGROUND
    )

    last_run: LastRun | None = None
    raw_last = payload.get("last_run")
    if isinstance(raw_last, dict):
        at = raw_last.get("at")
        summary = raw_last.get("summary")
        if isinstance(at, str) and isinstance(summary, str):
            code = raw_last.get("exit_code")
            last_run = LastRun(
                at=at,
                summary=summary,
                exit_code=code if isinstance(code, int) else None,
            )

    window: dict[str, int] | None = None
    raw_window = payload.get("window")
    if isinstance(raw_window, dict):
        try:
            candidate = {key: int(raw_window[key]) for key in ("x", "y", "w", "h")}
        except (KeyError, TypeError, ValueError):
            candidate = None
        # 太小的尺寸当成坏数据（可能是没写完整就退出）。
        if candidate is not None and candidate["w"] > 200 and candidate["h"] > 150:
            window = candidate

    return SessionState(
        selection=selection,
        cycles=cycles,
        backend=backend,
        pc_input_mode=pc_input_mode,
        last_run=last_run,
        params=params,
        window=window,
    )


def save(path: Path, state: SessionState) -> None:
    """原子写：先写 ``.tmp`` 再替换，避免中途断电留下半个文件。"""
    payload = {
        "version": SESSION_VERSION,
        "selection": list(state.selection),
        "cycles": dict(state.cycles),
        "backend": state.backend,
        "pc_input_mode": state.pc_input_mode,
        "params": {name: dict(value) for name, value in state.params.items()},
        "window": dict(state.window) if state.window is not None else None,
        "last_run": (
            None
            if state.last_run is None
            else {
                "at": state.last_run.at,
                "summary": state.last_run.summary,
                "exit_code": state.last_run.exit_code,
            }
        ),
    }
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)
    except OSError:
        # 写不进去（只读目录、磁盘满）不该让用户连任务都开不了 —— 约定 1 的同一条理由。
        return
