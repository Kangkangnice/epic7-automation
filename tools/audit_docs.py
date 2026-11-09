"""文档体检：正文里引用的路径 / 函数名，是否还对得上仓库现状。

**它不是门禁**，是体检工具。为什么不进门禁：存量里有几百处「引用已清理的临时探针」
和「墓碑式引用」，把它们全做成红会把提交钩子淹掉，人就会习惯性绕过 —— 那比不查更糟。
用法是**定期跑一次、人看报告**，或者改完某份文档后单独看一眼。

判断口径（跑完自己套一遍）：**同一句话在教你现在怎么做 → 必须能解析到真实文件；
在讲过去发生过什么 → 不用管。** 后者这类占了存量的大多数，工具会尽量过滤
（同行的墓碑词、`runtime_logs/` 临时探针、历史诊断帧名），但**过不干净也别改工具去凑**：
它给出的永远是候选清单，最后一步得人看。

    python -m auto_game_unified.tools.audit_docs
    python -m auto_game_unified.tools.audit_docs --only path

检查三件事：
1. 反引号里的文件路径是否还存在（``.py`` / ``.png`` / ``.md`` / ``.json``）；
2. 反引号里的 ``func()`` 是否还是仓库里的 ``def`` / ``class``；
3. 只写文件名的引用（``result.png``）按全库同名搜索放宽，**不报** ——
   文档里常这么指「某个目录里的那张图」，报出来全是噪音。

明确不当漂移的三类（各自有理由）：
- **临时探针**：``runtime_logs/`` 整个目录不入库、随时被清空。文档提到它只是记录
  「当时用什么取的数」，不是承诺那个脚本还在。单独归到「临时探针引用」一段。
- **诊断产物**：``evidence.json`` / ``screen.png`` 这些是运行时生成，仓库里本来就不该有。
- **决策记录**：``docs/decisions/`` 只增不改，里面提到已删除的旧 API 是在说明「当初为什么删」。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
DOCS = REPO / "docs"

CODE_ROOTS = [REPO / "games", REPO / "core", REPO / "desktop", REPO / "tools", REPO / "tests"]
TEMPLATE_ROOT = REPO / "games" / "epic7" / "templates"

PATH_EXTS = (".py", ".png", ".md", ".json", ".iss", ".spec")
DIAGNOSTIC_ARTIFACTS = {"evidence.json", "screen.png", "source.png", "target.png", "current.png"}
# 内置 / 标准库 / 教学占位，不当项目符号
BUILTIN_SYMBOLS = {"super", "zip", "print", "len", "open", "time", "get", "format"}


def code_symbols() -> set[str]:
    names: set[str] = set()
    pattern = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
    for base in CODE_ROOTS:
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                names.update(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    return names


def resolve_path(token: str, doc: Path) -> Path | None:
    candidates = [
        ROOT / token,
        REPO / token,
        TEMPLATE_ROOT / token,
        doc.parent / token,
        DOCS / token,
        REPO / "games" / "epic7" / token,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if "/" not in token:
        for base in (TEMPLATE_ROOT, REPO / "tests", REPO / "tools", REPO / "games",
                     REPO / "desktop", REPO / "desktop_qt", REPO / "packaging"):
            if not base.is_dir():
                continue
            if next(base.rglob(token), None) is not None:
                return base
    return None


HISTORICAL_FRAME = re.compile(r"^\d{8}_\d{4,6}")
# 同一行出现这些词 ⇒ 这是「墓碑式引用」（讲已删掉的东西、或拿旧名当反例），不是活引用
TOMBSTONE_WORDS = ("已删除", "已作废", "已废弃", "已清掉", "已移除", "别照着", "不要另开",
                   "曾经", "当时", "快照", "旧名", "历史做法", "不要再")


def is_temp_probe(token: str) -> bool:
    """临时资源：不入库 / 会被轮转删掉，文档提到它只是记录「当时那张图叫什么」。"""
    name = token.rsplit("/", 1)[-1]
    if token.startswith("runtime_logs/") or token.startswith("runtime_diagnostics/"):
        return True
    if name.startswith("_") and name.endswith(".py"):
        return True
    return bool(HISTORICAL_FRAME.match(name))


def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    symbols = code_symbols()
    real_missing: list[tuple[str, int, str]] = []
    temp_refs: list[tuple[str, int, str]] = []
    missing_symbols: list[tuple[str, int, str]] = []

    for doc in sorted(DOCS.rglob("*.md")):
        rel = doc.relative_to(REPO).as_posix()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for token in re.findall(r"`([^`\n]+)`", line):
                raw = token.strip()
                if any(ch in raw for ch in ("{", "}", "<", ">", "*", " ", "…", "...")):
                    continue
                if raw in DIAGNOSTIC_ARTIFACTS:
                    continue
                if raw.endswith(PATH_EXTS):
                    if resolve_path(raw, doc) is not None:
                        continue
                    if any(word in line for word in TOMBSTONE_WORDS):
                        continue
                    (temp_refs if is_temp_probe(raw) else real_missing).append((rel, lineno, raw))
                    continue
                match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*)\(\)", raw)
                if match:
                    name = match.group(1).split(".")[-1]
                    if name in BUILTIN_SYMBOLS or name in symbols:
                        continue
                    if rel.startswith("docs/decisions/"):
                        continue
                    missing_symbols.append((rel, lineno, raw))

    if only in (None, "path"):
        print(f"=== 真·路径漂移（{len(real_missing)} 处，值得修）===")
        for rel, line, token in real_missing:
            print(f"  {rel}:{line}  {token}")

        print(f"\n=== 临时探针引用（{len(temp_refs)} 处，`runtime_logs/` 不入库、不追改）===")
        for rel, line, token in temp_refs[:10]:
            print(f"  {rel}:{line}  {token}")
        if len(temp_refs) > 10:
            print(f"  …另有 {len(temp_refs) - 10} 处")

    if only in (None, "symbol"):
        print(f"\n=== 引用不存在的函数/类（{len(missing_symbols)} 处）===")
        for rel, line, token in missing_symbols:
            print(f"  {rel}:{line}  {token}")


if __name__ == "__main__":
    main()
