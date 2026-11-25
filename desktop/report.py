"""失败诊断包：把一次运行失败的现场收成一个可直接发送的压缩包。

## 为什么放在这里，而不是放进路线

路线只回答「哪一页认不出」，它不知道这次运行由谁启动（后端、输入通道、勾了
哪几条路线），也拿不到外层进程的退出码。这几样只有 ``desktop.worker`` 在收尾
时同时掌握。成包因此放在 worker 层，路线与主程序一行不改。

## 触发条件

只有退出码 1（运行失败）成包。0 是达到目标、2 是资源耗尽、130 是用户停止，
这三种不需要诊断包；每次正常结束都留一个包，会让真正失败的那次被埋掉。

## 包内固定五项

``README.txt`` 提交方式、``report.json`` 事实与分数、``logs`` 内外两层日志、
``frames`` 失败画面与识别证据、``config`` 环境与勾选。``investigate.md`` 是阅读
顺序。目录名与文件名固定，人与自动化工具按同一套路径取。

## 体积

一帧 1982x1132 的 PNG 约 1~2 MB。超过上限时整包帧转 JPG；仍超只保留第一张。
日志只取最新两份（``.log`` 与 ``.log.1``）：失败现场在这两份里，更早的轮转
文件对定位没有增量信息。
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import platform
import sys
from typing import Mapping, Sequence
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from auto_game_unified.core.account import ACCOUNT_ENV, normalize
from auto_game_unified.desktop.catalog import PRODUCT_VERSION, route_by_name

#: 一包里最多收几张画面。失败帧本身之外再留两张前序帧，足以看出转场还是改版。
MAX_FRAMES = 3
#: 保留最近几份诊断包。十份覆盖一段时间的反馈，又不至于让目录无限增长。
DEFAULT_KEEP = 10
#: 单包上限。群文件对单文件大小敏感，超过这个量级发送与下载都会变慢。
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
#: 日志随包只取最新两份（本体与一份轮转）。
LOG_PARTS = 2

_README = """第七史诗助手 运行诊断包

短码      {code}
生成时间  {created_at}
版本      {version}
失败路线  {route}
退出码    1

提交方式
1. 包内文件保持原样。
2. 将压缩包发送至反馈群。
3. 同时提供三项信息：短码、失败前的操作、界面最后显示的内容。

包内文件
README.txt       本文件
report.json      本次运行的结论与识别分数
investigate.md   阅读顺序（维护与自动化处理使用）
logs/            本次运行的应用日志
frames/          失败画面与识别证据
config/          运行环境与勾选配置

隐私处理
日志与配置中的用户目录替换为 %USERPROFILE%。
账号名替换为「账号A」。
诊断画面仅包含游戏窗口，不包含桌面或其他程序。
"""

_INVESTIGATE = """# 诊断包阅读顺序

本文件供维护者与自动化处理使用。按顺序阅读，前一步已能定性时不必继续。

## 1. report.json

- `exit_code`：1 为运行失败。0、2、130 不生成诊断包。
- `failed_route`：失败路线。为空表示未能从文件名判定。
- `failure`：失败动作、来源页、目标页、尝试次数、结论，来自失败帧的 evidence.json。
- `top_scores`：失败帧上各锚点的实际分数与阈值，按分数降序。
  - 分数略低于阈值：判据边缘，检查画质、缩放与比对口径。
  - 分数显著低于阈值：页面不符或模板已失效。
  - `observed=true` 但页面仍判错：排他性不足，检查同页其他锚点。
- `recent_output`：外层进程记录的最后若干行。
- `frames_compressed`：帧已转为 JPG，尺寸不变。

## 2. frames/

- 整屏图确认游戏停留页面、弹窗、黑屏与遮挡。
- 证据目录（名称见 report.json 的 failure.evidence_dir）内的 evidence.json 是
  全部锚点观测；source.png 与 target.png 为来源区与目标区的裁剪。
- 多帧时以文件名时间最新的一张为失败瞬间。

## 3. logs/

- `epic7_<路线>.log`：动作序列。定位最后一次成功动作到第一个失败动作之间的记录。
- `desktop_worker.log`：外层记录。`事件=结束` 一行含退出码、最后输出与现场帧。

## 4. config/

- `run.json`：后端、输入通道、勾选路线与次数。
- `environment.txt`：版本、系统、Python、屏幕、数据目录（已脱敏）。

## 5. 处理顺序

1. 用失败帧写失败测试，确认修改前为红。
2. 修改实现，测试转绿。
3. 去掉修复后能复现故障（反向验证）。
4. 运行受影响路线与全量门禁。
5. 在 memory/YYYY-MM-DD.md 记录病根、改动与验证结果。
"""


def export_failure_report(
    *,
    root: Path,
    modes: Sequence[str],
    backend: str,
    pc_input_mode: str,
    exit_code: int,
    last_output: str,
    recent_output: Sequence[str] = (),
    cycles: Mapping[str, int] | None = None,
    keep: int = DEFAULT_KEEP,
    max_bytes: int = DEFAULT_MAX_BYTES,
    user_home: Path | None = None,
) -> Path:
    """收一次失败的现场，返回生成的压缩包路径。

    调用方只在退出码为 1 时调用。本函数不抛业务异常给界面：写盘失败由调用方
    记一行日志，``finished`` 事件照常发出。
    """

    created_at = datetime.now()
    code = uuid4().hex[:4].upper()
    output_dir = root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / (
        f"E7-{created_at:%Y%m%d-%H%M}-{code}.zip"
    )

    frame, route = _failure_frame(root, modes, exit_code)
    frames = _collect_frames(root, route, frame)
    evidence_dir = _evidence_dir(root, route, frame)
    evidence = _read_evidence(evidence_dir)
    home = user_home or Path.home()
    account = _account_names()

    top_scores = _top_scores(evidence)
    log_files = _log_files(root, route)
    payload = {
        "short_code": code,
        "created_at": created_at.isoformat(timespec="seconds"),
        "product_version": PRODUCT_VERSION,
        "modes": list(modes),
        "backend": backend,
        "pc_input_mode": pc_input_mode,
        "exit_code": exit_code,
        "failed_route": route,
        "last_output": _redact(last_output, home, account),
        "recent_output": [
            _redact(line, home, account) for line in recent_output
        ],
        "failure": _failure_summary(evidence, evidence_dir, home, account),
        "top_scores": top_scores,
        "frames": [f"frames/{name}" for name, _ in frames],
        "logs": [f"logs/{path.name}" for path in log_files],
        "frames_compressed": False,
        "note": "" if evidence else "未找到失败帧的证据包，failure 与 top_scores 为空。",
    }

    entries: list[tuple[str, bytes]] = []
    entries.append(
        (
            "README.txt",
            _encode(
                _README.format(
                    code=code,
                    created_at=payload["created_at"].replace("T", " "),
                    version=PRODUCT_VERSION,
                    route=_route_label(route),
                )
            ),
        )
    )
    entries.append(("investigate.md", _encode(_INVESTIGATE)))
    entries.append(
        (
            "config/run.json",
            _encode(
                json.dumps(
                    {
                        "modes": list(modes),
                        "cycles": dict(cycles or {}),
                        "backend": backend,
                        "pc_input_mode": pc_input_mode,
                        "exit_code": exit_code,
                        "product_version": PRODUCT_VERSION,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        )
    )
    entries.append(
        (
            "config/environment.txt",
            _encode(_environment(root, backend, pc_input_mode, home, account)),
        )
    )
    for path in log_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        entries.append(
            (f"logs/{path.name}", _encode(_redact(text, home, account)))
        )

    image_entries = [(f"frames/{name}", data) for name, data in frames]
    evidence_entries = _evidence_entries(evidence_dir)
    for name, data in evidence_entries:
        entries.append((name, data))

    payload["frames_compressed"] = _over_limit(
        entries, image_entries, max_bytes
    )
    if payload["frames_compressed"]:
        image_entries = [
            (f"{Path(name).with_suffix('.jpg').as_posix()}", _to_jpeg(data))
            for name, data in image_entries
        ]
        payload["frames"] = [name for name, _ in image_entries]
    if _over_limit(entries, image_entries, max_bytes) and image_entries:
        image_entries = image_entries[:1]
        payload["frames"] = [image_entries[0][0]]
        payload["note"] = _join_note(
            payload["note"], "帧总量超过单包上限，仅保留一张。"
        )

    entries.insert(
        1, ("report.json", _encode(json.dumps(payload, ensure_ascii=False, indent=2)))
    )

    prefix = archive_path.stem
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(f"{prefix}/{name}", data)
        for name, data in image_entries:
            archive.writestr(f"{prefix}/{name}", data)

    _prune(output_dir, keep)
    return archive_path


def short_code_of(archive_path: Path) -> str:
    """从包名取短码；不符合命名规则时返回空串。"""

    parts = archive_path.stem.split("-")
    return parts[-1] if len(parts) >= 4 else ""


def _route_label(mode: str) -> str:
    """路线在提交说明里用中文名，玩家不需要知道内部代号。"""

    if not mode:
        return "未判定"
    try:
        return route_by_name(mode).label
    except Exception:
        return mode


def _failure_frame(
    root: Path, modes: Sequence[str], exit_code: int
) -> tuple[Path | None, str]:
    """找失败瞬间的整屏帧，并判定它属于哪条路线。

    外层进程在收尾时会把最后一次 ``current.png`` 复制成
    ``desktop_worker/<时间>_<路线>_exit_<码>.png``。找不到时退回各路线目录里
    最新的一张，并只从已勾选的路线里匹配文件名，避免把别的路线认成现场。
    """

    worker_dir = root / "runtime_diagnostics" / "desktop_worker"
    candidates = sorted(
        worker_dir.glob(f"*_exit_{exit_code}.png"),
        key=_mtime,
    )
    for path in reversed(candidates):
        route = _route_in_name(path.stem, modes)
        if route:
            return path, route
    for mode in reversed(modes):
        directory = root / "runtime_diagnostics" / f"epic7_{mode}"
        if not directory.is_dir():
            continue
        frames = sorted(
            (path for path in directory.glob("*.png") if path.name != "current.png"),
            key=_mtime,
        )
        if frames:
            return frames[-1], mode
    return None, ""


def _route_in_name(stem: str, modes: Sequence[str]) -> str:
    for mode in modes:
        if f"_{mode}_exit_" in stem:
            return mode
    return ""


def _collect_frames(
    root: Path, route: str, primary: Path | None
) -> list[tuple[str, bytes]]:
    """最多三帧：失败帧在前，同一路线的更早诊断帧补充在后。"""

    frames: list[Path] = []
    if primary is not None and primary.is_file():
        frames.append(primary)
    if route:
        directory = root / "runtime_diagnostics" / f"epic7_{route}"
        if directory.is_dir():
            for path in sorted(
                (
                    path
                    for path in directory.glob("*.png")
                    if path.name != "current.png"
                ),
                key=_mtime,
                reverse=True,
            ):
                if len(frames) >= MAX_FRAMES:
                    break
                if path not in frames:
                    frames.append(path)
    return [
        (path.name, path.read_bytes())
        for path in frames[:MAX_FRAMES]
        if path.is_file()
    ]


def _evidence_dir(
    root: Path, route: str, frame: Path | None
) -> Path | None:
    """失败帧对应的证据目录。

    外层进程复制 ``current.png`` 时只复制了图片，帧旁边没有证据目录；真正的
    evidence.json 在 ``runtime_diagnostics/epic7_<路线>/<时间>_<动作>/`` 里。
    因此先看帧旁，再退回该路线最新的一份证据。两者是同一时刻的帧：失败帧来自
    ``current.png``，而 current.png 每次采集都覆盖，最后一张即失败那一张。
    """

    if frame is not None:
        beside = frame.with_suffix("")
        if (beside / "evidence.json").is_file():
            return beside
    if not route:
        return None
    directory = root / "runtime_diagnostics" / f"epic7_{route}"
    if not directory.is_dir():
        return None
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_dir() and (path / "evidence.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=_mtime)


def _evidence_entries(
    directory: Path | None,
) -> list[tuple[str, bytes]]:
    """把证据包收进 ``frames/<证据目录名>/``。

    evidence.json 是定位的核心（分数、阈值、页面结论），必须随包走；
    source/target 是来源区与目标区的裁剪，体积小，同样保留。
    """

    if directory is None:
        return []
    entries: list[tuple[str, bytes]] = []
    for child in ("evidence.json", "source.png", "target.png"):
        path = directory / child
        if path.is_file():
            entries.append(
                (f"frames/{directory.name}/{child}", path.read_bytes())
            )
    return entries


def _read_evidence(directory: Path | None) -> dict:
    if directory is None:
        return {}
    path = directory / "evidence.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _failure_summary(
    evidence: dict,
    evidence_dir: Path | None,
    home: Path,
    account: Sequence[str],
) -> dict:
    if not evidence:
        return {}
    evidence_body = evidence.get("evidence") or {}
    pages = evidence_body.get("pages") or {}
    return {
        "action": evidence.get("action"),
        "source": evidence.get("source"),
        "targets": evidence.get("targets"),
        "attempt": evidence.get("attempt"),
        "conclusion": evidence.get("conclusion"),
        "mode": evidence.get("mode"),
        "pages": pages,
        "evidence_dir": evidence_dir.name if evidence_dir else "",
        "template_root": _redact(
            str((evidence_body.get("profile") or {}).get("template_root", "")),
            home,
            account,
        ),
    }


def _top_scores(evidence: dict, limit: int = 8) -> list[dict]:
    atoms = ((evidence.get("evidence") or {}).get("atoms")) or {}
    rows = []
    for key, atom in atoms.items():
        if not isinstance(atom, dict) or atom.get("score") is None:
            continue
        rows.append(
            {
                "atom": key,
                "score": atom.get("score"),
                "threshold": atom.get("threshold"),
                "observed": atom.get("observed"),
                "region": atom.get("region"),
            }
        )
    rows.sort(key=lambda row: float(row["score"]), reverse=True)
    return rows[:limit]


def _log_files(root: Path, route: str) -> list[Path]:
    logs = root / "runtime_logs"
    selected: list[Path] = []
    if route:
        selected.extend(_with_rotations(logs / f"epic7_{route}.log", LOG_PARTS))
    selected.extend(_with_rotations(logs / "desktop_worker.log", LOG_PARTS))
    return selected


def _with_rotations(path: Path, parts: int) -> list[Path]:
    candidates = [path, *(
        Path(f"{path}.{index}") for index in range(1, parts)
    )]
    return [candidate for candidate in candidates if candidate.is_file()]


def _environment(
    root: Path,
    backend: str,
    pc_input_mode: str,
    home: Path,
    account: Sequence[str],
) -> str:
    lines = [
        f"版本：{PRODUCT_VERSION}",
        f"系统：{platform.platform()}",
        f"Python：{platform.python_version()}",
        f"屏幕：{_screen_size()}",
        f"窗口后端：{backend}",
        f"输入通道：{pc_input_mode}",
        f"数据目录：{_redact(str(root), home, account)}",
        f"账号：{'账号A' if account else '未识别'}",
    ]
    return "\n".join(lines) + "\n"


def _screen_size() -> str:
    if sys.platform != "win32":
        return "未记录"
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}"
    except Exception:
        return "未记录"


def _account_names() -> tuple[str, ...]:
    """要脱敏的账号写法：原始值与环境里净化后的值。

    日志可能打印原名，也可能打印目录名，两种都要替换，否则包内仍会带昵称。
    """

    raw = os.environ.get(ACCOUNT_ENV, "")
    cleaned = normalize(raw)
    return tuple(dict.fromkeys(item for item in (raw, cleaned) if item))


def _redact(text: str, home: Path, account: Sequence[str]) -> str:
    redacted = text.replace(str(home), "%USERPROFILE%")
    redacted = redacted.replace(home.as_posix(), "%USERPROFILE%")
    for name in account:
        redacted = redacted.replace(name, "账号A")
    return redacted


def _over_limit(
    entries: Sequence[tuple[str, bytes]],
    images: Sequence[tuple[str, bytes]],
    max_bytes: int,
) -> bool:
    total = sum(len(data) for _, data in entries)
    total += sum(len(data) for _, data in images)
    return total > max_bytes


def _to_jpeg(data: bytes) -> bytes:
    # 延迟导入：只有帧超过单包上限才需要转码，界面启动不该为这条冷路径加载 cv2。
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return data
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return encoded.tobytes() if ok else data


def _join_note(current: str, extra: str) -> str:
    return f"{current}{extra}" if current else extra


def _encode(text: str) -> bytes:
    return text.encode("utf-8")


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _prune(output_dir: Path, keep: int) -> None:
    if keep < 1:
        return
    archives = sorted(output_dir.glob("E7-*.zip"), key=_mtime)
    for path in archives[:-keep]:
        try:
            path.unlink()
        except OSError:
            pass
