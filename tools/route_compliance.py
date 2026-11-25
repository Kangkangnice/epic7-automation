"""路线契约合规矩阵：一次看清 21 条路线各缺哪几项（只读、离线）。

这只是**声明层**的结论：声明齐了不等于实机跑过。欠债名单与真实声明都来自
``modes.MODE_SPECS``，不另建一份表；危险动作一列读 ``SAFETY_MATRIX.md`` 的行名。

用法（仓库父目录）：

    python -m auto_game_unified.tools.route_compliance
    python -m auto_game_unified.tools.route_compliance --strict
    python -m auto_game_unified.tools.route_compliance --json
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

from auto_game_unified.games.epic7.modes import (
    CONTRACT_BACKLOG,
    MODE_SPECS,
    TRANSITION_EXEMPT,
)
from auto_game_unified.games.epic7.route_contract import validate_contract

SAFETY_MATRIX = Path(__file__).resolve().parents[1] / "docs" / "SAFETY_MATRIX.md"
# 「剧情」是主线在安全矩阵第一节里的旧行名，其余按路线名或中文名匹配。
SAFETY_ROW_ALIASES = {"story": ("剧情",)}

COLUMNS = ("路线", "契约", "终点", "覆盖层", "空态", "回执", "危险动作", "结论")


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _safety_rows() -> list[str]:
    if not SAFETY_MATRIX.exists():
        return []
    lines = SAFETY_MATRIX.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("## 一、危险动作")), None
    )
    if start is None:
        return []
    rows: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## ") or line.startswith("### "):
            break
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        cell = line.split("|", 2)[1].strip()
        if cell and cell != "路线":
            rows.append(cell)
    return rows


def _has_safety_row(mode: str, label: str, rows: list[str]) -> bool:
    names = (mode, label.strip(), *SAFETY_ROW_ALIASES.get(mode, ()))
    return any(name and name in row for row in rows for name in names)


def build_rows() -> list[dict[str, Any]]:
    safety_rows = _safety_rows()
    result: list[dict[str, Any]] = []
    for mode, spec in MODE_SPECS.items():
        contract = spec.contract
        owed = mode in CONTRACT_BACKLOG
        # 与加载期断言同源：豁免名单里的路线可以写自己的回执机制，
        # 不传这张表会把「在豁免名单里、用自己的机制验收」误判成不一致。
        problems = (
            validate_contract(
                contract, spec.states, transition_exempt=TRANSITION_EXEMPT
            )
            if contract is not None
            else []
        )
        if contract is None and owed:
            conclusion = "欠债"
        elif contract is None or problems or (owed and contract is not None):
            conclusion = "不一致"
        else:
            conclusion = "达标"

        if contract is None:
            terminal = overlays = empty = evidence = "—"
        else:
            where = "回大厅" if contract.finish_at_home else "不回大厅"
            terminal = f"{contract.terminal}（{where}）"
            overlays = (
                f"{len(contract.overlays)} 类"
                if contract.overlays
                else "0 类（显式空）"
            )
            empty = (
                f"{len(contract.empty_states)} 项"
                if contract.empty_states
                else "无（显式空）"
            )
            evidence = (
                "转场契约"
                if contract.action_evidence == "transition_contract"
                else contract.action_evidence
            )

        result.append(
            {
                "路线": f"{spec.label.strip()} `{mode}`",
                "契约": "已声明" if contract is not None else "欠债",
                "终点": terminal,
                "覆盖层": overlays,
                "空态": empty,
                "回执": evidence,
                "危险动作": (
                    "有" if _has_safety_row(mode, spec.label, safety_rows) else "缺行"
                ),
                "结论": conclusion,
                "问题": problems,
                "欠债理由": CONTRACT_BACKLOG.get(mode, ""),
            }
        )
    return result


def format_table(rows: list[dict[str, Any]]) -> str:
    widths = {
        column: max(_display_width(column), *( _display_width(str(row[column])) for row in rows))
        for column in COLUMNS
    }

    def line(values: tuple[str, ...]) -> str:
        return " | ".join(
            value + " " * (widths[column] - _display_width(value))
            for column, value in zip(COLUMNS, values, strict=True)
        )

    header = line(COLUMNS)
    body = [line(tuple(str(row[column]) for column in COLUMNS)) for row in rows]
    return "\n".join([header, "-" * _display_width(header), *body])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="有欠债或不一致时返回非零")
    parser.add_argument("--json", action="store_true", help="输出 JSON，供脚本复核")
    args = parser.parse_args(argv)

    rows = build_rows()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(format_table(rows))

    if not args.strict:
        return 0
    bad = [row for row in rows if row["结论"] != "达标"]
    if not bad:
        return 0
    print(f"\n未达标 {len(bad)} 条：", file=sys.stderr)
    for row in bad:
        print(f"  {row['路线']}：{row['结论']} {row['欠债理由']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
