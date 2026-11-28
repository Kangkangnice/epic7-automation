"""读取失败诊断包，打印一页结论。

用法：

    python -m auto_game_unified.tools.triage_report <诊断包.zip>

只读压缩包，不解压到磁盘。输出面向维护者与自动化处理：版本、退出码、失败
路线、失败动作、各锚点分数与阈值、画面与日志位置。阅读顺序的完整说明在包内
``investigate.md``。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from zipfile import ZipFile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="triage_report",
        description="读取失败诊断包并打印一页结论。",
    )
    parser.add_argument("archive", type=Path, help="诊断包路径（E7-*.zip）")
    args = parser.parse_args(argv)
    if not args.archive.is_file():
        print(f"找不到诊断包：{args.archive}")
        return 2
    try:
        with ZipFile(args.archive) as archive:
            report = _load_report(archive)
    except (OSError, ValueError) as error:
        print(f"读取失败：{error}")
        return 2
    print(_render(report))
    return 0


def _load_report(archive: ZipFile) -> dict:
    names = archive.namelist()
    target = next(
        (name for name in names if name.endswith("/report.json")), None
    )
    if target is None:
        raise ValueError("包内没有 report.json")
    payload = json.loads(archive.read(target).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report.json 不是对象")
    return payload


def _render(report: dict) -> str:
    failure = report.get("failure") or {}
    lines = [
        f"诊断包 {report.get('short_code', '-')}",
        (
            f"版本 {report.get('product_version', '-')}"
            f" · 后端 {report.get('backend', '-')}"
            f" · 输入 {report.get('pc_input_mode', '-')}"
        ),
        (
            f"退出码 {report.get('exit_code', '-')}"
            f" · 失败路线 {report.get('failed_route') or '未判定'}"
        ),
        (
            f"失败动作 {failure.get('action') or '-'}"
            f" · 来源 {failure.get('source') or '-'}"
            f" · 目标 {_targets(failure.get('targets'))}"
        ),
        (
            f"结论 {failure.get('conclusion') or '-'}"
            f" · 尝试 {failure.get('attempt') if failure.get('attempt') is not None else '-'}"
        ),
    ]
    if failure.get("evidence_dir"):
        lines.append(f"证据目录 {failure['evidence_dir']}")
    if report.get("first_error"):
        lines.append(f"首个故障 {report['first_error']}")
        lines.append(f"截帧时机 {report['window_reason']}")
    lines.append(f"最后输出 {_clip(report.get('last_output'), 160)}")
    lines.append("")
    lines.append("识别分数")
    scores = report.get("top_scores") or []
    if not scores:
        lines.append("  无（未找到失败帧的证据包）")
    for row in scores:
        score = _num(row.get("score"))
        threshold = _num(row.get("threshold"))
        relation = ">=" if _passes(row) else "< "
        state = "observed" if row.get("observed") else "miss    "
        lines.append(
            f"  {score} {relation} {threshold}  {state}  {row.get('atom', '-')}"
        )
    lines.append("")
    lines.append("画面")
    for name in report.get("frames") or []:
        lines.append(f"  {name}")
    if not report.get("frames"):
        lines.append("  无")
    lines.append("")
    lines.append("日志")
    for name in report.get("logs") or []:
        lines.append(f"  {name}")
    if not report.get("logs"):
        lines.append("  无")
    if report.get("frames_compressed"):
        lines.append("")
        lines.append("说明 帧已转为 JPG，尺寸不变")
    if report.get("note"):
        lines.append(f"说明 {report['note']}")
    return "\n".join(lines)


def _targets(value: object) -> str:
    if isinstance(value, (list, tuple)) and value:
        return "/".join(str(item) for item in value)
    return "-"


def _num(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}"
    return "  -  "


def _passes(row: dict) -> bool:
    score = row.get("score")
    threshold = row.get("threshold")
    if isinstance(score, (int, float)) and isinstance(threshold, (int, float)):
        return score >= threshold
    return False


def _clip(value: object, limit: int) -> str:
    text = str(value or "-").strip().replace("\n", " ")
    return text if len(text) <= limit else f"{text[:limit]}..."


if __name__ == "__main__":
    sys.exit(main())
