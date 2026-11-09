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
    python -m auto_game_unified.tools.audit_docs --verbose   # 逐条列出已判定项

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

## 2026-11-09 逐条判定（把当时报出的 120 处「真·路径漂移」全部过完）

结论：**真正需要改的只有 2 处**，且都已修：
- ``topics/disciplines.md`` → 专题真名是单数 ``topics/discipline.md``（复数笔误）；
- ``scripts/watch_pc_frames.py`` → 一次性旁观抓帧探针，脚本从未入库，文档却写成
  「跑之前先开」的现行做法，已改为「一次性探针、不入库、别去找具体文件」。

其余**全部有意保留**，按下面 6 类归档（不写死条数：判定规则一放宽，各类的数量就会变；
新增引用若落到「待人工判断」，按开头口径判）：
1. ``workspace-external`` —— 工作区外：``.workbuddy/memory/`` 记忆专题、
   ``.reverse/`` 反编译产物。仓内解析不到是对的，README 第 47–57 行整张表都指向这里；
2. ``link-label`` —— Markdown 链接的**显示文字**（``[`story.md`](...)``），
   真实目标写在后面的 ``(...)`` 里，本来就不是路径；
3. ``placeholder`` —— 泛指 / 教学占位 / 反例命名（``.md``、``xxx.py``、
   ``live_verification_v2.md``「不要另开」的反例名等）；
4. ``historical-snapshot`` —— 已标「快照 / 存档 / 只供追溯」的文档或小节里的
   墓碑式引用（``launcher.py``、已删的量分脚本等），它们讲的是过去发生过什么；
5. ``historical-frame`` —— 一次性探针与历史现场帧名，脚本 / 帧不入库；
6. ``layered-path`` —— 文件真实存在，只是省略了 ``pc/``、``tests/fixtures/`` 等前缀
   （PC 分层回落本来就是项目机制，写全路径反而与「共用模板」的表述冲突）。

另外工具报的 8 处「不存在的函数/类」也逐条看过：4 处是已删除 API 的墓碑式列举、
2 处是 ``home_return()`` 这类叙述性简称、2 处是 ``foo()`` / ``_xxx_present()``
教学占位，都不是漏符号。

⚠️ 归类规则是**判定记录**，不是「把数字洗成 0」的开关：规则放宽会吞掉真问题，
所以只按明确特征归类，拿不准的一律留在「待人工判断」段落里等人看。
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
# 工作区外、但文档里有意引用的两个根（仓内解析不到，不该算漂移）
WORKSPACE_ROOTS = (ROOT / ".workbuddy" / "memory", ROOT / ".reverse")

PATH_EXTS = (".py", ".png", ".md", ".json", ".iss", ".spec")
DIAGNOSTIC_ARTIFACTS = {"evidence.json", "screen.png", "source.png", "target.png", "current.png"}
# 内置 / 标准库 / 教学占位，不当项目符号
BUILTIN_SYMBOLS = {"super", "zip", "print", "len", "open", "time", "get", "format"}

# 2026-11-09 判定用的归类依据
HISTORICAL_DOCS = {
    "docs/WORLD_BOSS_DESIGN.md",                       # 头部明写「整份只作追溯」
    "docs/maintenance/route_extensibility_review.md",  # README 标 2026-09-27 快照
}
SECTION_MARKERS = ("存档", "快照", "只供追溯", "施工记录", "仅留")
# 同行出现这些词 ⇒ 讲已删掉的东西、或拿错误路径当反例，不是活引用
TOMBSTONE_WORDS = (
    "已删除", "已作废", "已废弃", "已清掉", "已移除", "已删", "一并删除", "整套已删除",
    "别照着", "别去找", "不要另开", "不要再", "刻意不存在", "（文件不存在）", "读不到",
    "传错", "写错目录", "曾经", "当时", "快照", "旧名", "历史做法", "已随", "整体删除",
)
# 这些前缀本身就是「工作区外」的意思，不必靠同名文件碰运气
WORKSPACE_PREFIXES = ("topics/", ".workbuddy/", ".reverse/", "e7lua/", "e7out/", "reatest/")
# 教学占位 / 反例命名：本来就不是仓库里的文件
PLACEHOLDER_TOKENS = {
    "hunt.py",                              # EXTENDING 里虚构的示例路线
    "live_verification_v2.md",              # 「不要另开第二份」的反例名
    "实机验证新方案.md",
    "docs/wip/2026-11-08-arena-refresh.md",  # wip 模板里的示例文件名
    "sanctuary_title.png",                  # 文档明说「刻意不存在」
    "maintenance/fodder.md",                # 文档明说「别去找」
}
CATEGORY_DESC = {
    "workspace-external": "工作区外引用：.workbuddy/memory/ 与 .reverse/ 反编译产物",
    "link-label": "Markdown 链接显示文字，真实目标写在后面的 (...) 里",
    "placeholder": "泛指 / 教学占位 / 反例命名，本就不是文件",
    "historical-snapshot": "已标快照·存档·只供追溯的文档或小节（墓碑式引用）",
    "historical-frame": "一次性探针与历史现场帧名，脚本 / 帧不入库",
    "layered-path": "文件真实存在，只是省略 pc/ 或 tests/fixtures/ 等前缀",
}


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


def repo_names() -> set[str]:
    """全仓文件名集合（排除构建产物）——用于认「路径简写」。"""
    names: set[str] = set()
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        text = path.as_posix()
        if "packaging/dist" in text or "__pycache__" in text:
            continue
        names.add(path.name)
    return names


def workspace_names() -> set[str]:
    """只收「文档确实会引用」的工作区外文件名，不递归第三方目录。

    ⚠️ 别改成 ``rglob``：``.reverse/ghidra/`` 里塞着 Ghidra 自带的上千个 py 文件，
    其中就有一个 ``launcher.py`` —— 递归收名会把仓内**已删除**的 ``launcher.py``
    误判成「工作区外引用」，把墓碑式引用洗掉（2026-11-09 实测踩过）。
    """
    names: set[str] = set()
    memory = ROOT / ".workbuddy" / "memory"
    topics = memory / "topics"
    if topics.is_dir():
        names.update(path.name for path in topics.glob("*.md"))
    if memory.is_dir():
        names.update(path.name for path in memory.glob("*.md"))
    reverse = ROOT / ".reverse"
    if reverse.is_dir():
        names.update(path.name for path in reverse.glob("*") if path.is_file())
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
# 现场帧名：03_ / 04_ / 05_ 序列帧、_tpl_ / _probe_ 前缀、日期戳、legacy、分辨率名
FRAME_NAME = re.compile(r"^\d{2}_|^_(?:tpl|probe)_|20\d{6}|legacy|\d{3,4}x\d{3,4}", re.I)


def is_temp_probe(token: str) -> bool:
    """临时资源：不入库 / 会被轮转删掉，文档提到它只是记录「当时那张图叫什么」。"""
    name = token.rsplit("/", 1)[-1]
    if token.startswith("runtime_logs/") or token.startswith("runtime_diagnostics/"):
        return True
    if name.startswith("_") and name.endswith(".py"):
        return True
    if HISTORICAL_FRAME.match(name) or FRAME_NAME.search(name):
        return True
    return False


def classify(rel: str, line: str, raw: str, section: str,
             names: set[str], external: set[str]) -> str | None:
    """给一处「解析不到」的引用打判定标签；返回 None = 拿不准，留给人看。

    顺序有意义：先认「本来就不是仓内路径」的，再认历史引用，最后才认路径简写，
    免得把 ``templates/world_boss/world_boss/...`` 这种**故意写错**的示例
    误归成「文件存在、只是省了前缀」。
    """
    name = raw.rsplit("/", 1)[-1]
    if raw.startswith(WORKSPACE_PREFIXES) or name in external:
        return "workspace-external"
    if f"[`{raw}`](" in line:
        return "link-label"
    if ((name.startswith(".") and len(name) <= 4) or "xxx" in name
            or "模板根/路线名" in raw or "时间戳_原因" in name
            or raw in PLACEHOLDER_TOKENS):
        return "placeholder"
    if (rel in HISTORICAL_DOCS or any(mark in section for mark in SECTION_MARKERS)
            or any(word in line for word in TOMBSTONE_WORDS)):
        return "historical-snapshot"
    if is_temp_probe(raw):
        return "historical-frame"
    if name in names:
        return "layered-path"
    return None


def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    verbose = "--verbose" in sys.argv

    symbols = code_symbols()
    names = repo_names()
    external = workspace_names()
    unreviewed: list[tuple[str, int, str]] = []
    reviewed: list[tuple[str, str, int, str]] = []
    temp_refs: list[tuple[str, int, str]] = []
    missing_symbols: list[tuple[str, int, str]] = []

    for doc in sorted(DOCS.rglob("*.md")):
        rel = doc.relative_to(REPO).as_posix()
        section = ""
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("#"):
                section = line
            for token in re.findall(r"`([^`\n]+)`", line):
                raw = token.strip()
                if any(ch in raw for ch in ("{", "}", "<", ">", "*", " ", "…", "...")):
                    continue
                if raw in DIAGNOSTIC_ARTIFACTS:
                    continue
                if raw.endswith(PATH_EXTS):
                    if resolve_path(raw, doc) is not None:
                        continue
                    if is_temp_probe(raw):
                        temp_refs.append((rel, lineno, raw))
                        continue
                    category = classify(rel, line, raw, section, names, external)
                    if category is None:
                        unreviewed.append((rel, lineno, raw))
                    else:
                        reviewed.append((category, rel, lineno, raw))
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
        print(f"=== 待人工判断的路径漂移（{len(unreviewed)} 处，值得修）===")
        for rel, line, token in unreviewed:
            print(f"  {rel}:{line}  {token}")

        print(f"\n=== 已判定·合理保留（{len(reviewed)} 处，按类别）===")
        for category, desc in CATEGORY_DESC.items():
            count = sum(1 for item in reviewed if item[0] == category)
            if count:
                print(f"  {category:22s} {count:3d}  {desc}")
        if verbose:
            for category, rel, line, token in reviewed:
                print(f"    [{category}] {rel}:{line}  {token}")

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
