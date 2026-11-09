"""文档漂移审查：**按本次改动**列出该复审哪几份文档。

用法（在**工作区根**执行）：:

    python -m auto_game_unified.tools.doc_review            # 工作区相对 HEAD 的改动
    python -m auto_game_unified.tools.doc_review --staged   # 只看暂存区

提交钩子会另外带 ``--staged --require-note <提交信息文件>`` 调用本脚本。

为什么不再用游标
----------------
`docs/STATUS.md` 那套只能保证**结构化事实**（路线数、放行名单）不与代码脱节。
剩下的文档 —— 架构说明、每路线维护手册、用户手册、转场契约 —— 谁也没法自动判断
「里面那句话还成不成立」。业界能做的只有一件事：**把复审变得便宜**。

初版借社区 skill `doc-maintenance` 的游标记「上次审到哪个提交」。2026-11-09 验收发现
它天生有洞：游标是**要人记得推进的状态**，一忙就落后 7 个提交；而且它只看两个提交
之间的 diff，**工作区里未提交的改动完全看不见**。现在改成按「本次暂存区 / 本次工作区」
即时判定，没有任何需要记忆的状态。

复审留痕
--------
命中规则的提交必须在提交信息里写一行 ``Doc-reviewed:``。机器只能验证「有没有留痕」，
不能验证「有没有真读」—— 但它把「审文档」从可跳过的自觉动作，变成提交时必然碰到的一问。
确实没有文档变化就写「无变化」，**不要为了留痕造文档改动**。

开发闭环（2026-11-09 治理 V2）
------------------------------
文档要能对开发有用，得回答三件事，而不是只在提交时提醒「该复审哪份」：
**开工前读什么 → 改完更新什么 → 新发现沉淀到哪**。``SCENARIOS`` 是这张清单的
**唯一来源**，``--scenario <key>`` 开工时打印、提交时按本次改动自动提示。
仓库文档里不要再抄一份「登记四处」，直接引用命令；清单里的文档路径与章节锚点
由 ``tests/test_doc_review.py`` 反向验，改名 / 删节会直接报红。

    python -m auto_game_unified.tools.doc_review --scenarios
    python -m auto_game_unified.tools.doc_review --scenario new-route

清单做成代码而不是新写一份文档，是因为「为了写文档而写文档」正是这套治理要治的病。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
#: git 仓库根就是包目录本身（工作区根 `auto_game` 不是仓库）。
REPO_ROOT = PACKAGE_ROOT

#: 关键改动路径：每一条都必须能映射到至少一份文档。
#: 守的是「新增/改动了某个模块，映射表却没登记」这类静默漏提醒
#: （2026-11-09 就漏过 core/pc_window.py）。反向护栏在 tests/test_doc_review.py。
MUST_MAP: tuple[str, ...] = (
    "core/pc_window.py",
    "core/matcher.py",
    "main.py",
    "games/epic7/arena.py",
    "games/epic7/templates/story/home.png",
    "desktop/catalog.py",
    "desktop/preflight.py",
    "desktop_qt/app.py",
    "tools/live_check.py",
    "packaging/epic7_auto_assistant.spec",
    ".github/workflows/tests.yml",
)

#: 改动路径 → 需要复审的文档。按前缀匹配，**所有命中的规则都会叠加**
#: （具体规则给「这条路线的维护手册」，通用规则 ``games/epic7/`` 再补一份 STATUS）。
#: 只写「改了这个文件，哪份文档里的话可能就不成立了」，不追求完备：
#: 漏掉的代价是「下次看别的文档时会顺带发现」，错报的代价是白读几页。
DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("games/epic7/templates/", ("docs/TEMPLATE_CAPTURE.md", "docs/STATUS.md")),
    ("games/epic7/evidence/", ("docs/STATUS.md", "docs/TRANSITION_CONTRACTS.md")),
    ("games/epic7/modes.py", ("docs/STATUS.md", "docs/EXTENDING.md")),
    ("games/epic7/daily_tasks.py", ("docs/STATUS.md", "docs/EXTENDING.md")),
    ("games/epic7/navigation.py", ("docs/STATUS.md", "docs/TRANSITION_CONTRACTS.md")),
    ("games/epic7/hero_synthesis.py", ("docs/maintenance/hero_synthesis.md",)),
    ("games/epic7/arena.py", ("docs/maintenance/arena.md",)),
    ("games/epic7/story.py", ("docs/maintenance/story.md",)),
    ("games/epic7/side_story.py", ("docs/maintenance/side_story.md",)),
    ("games/epic7/tower.py", ("docs/maintenance/tower.md",)),
    ("games/epic7/expedition.py", ("docs/maintenance/expedition.md",)),
    ("games/epic7/community.py", ("docs/maintenance/community_checkin.md",)),
    ("games/epic7/knights_donation.py", ("docs/maintenance/knights_donation.md",)),
    ("games/epic7/labyrinth_stone.py", ("docs/maintenance/labyrinth_stone.md",)),
    ("games/epic7/moonlight_theater.py", ("docs/maintenance/moonlight_theater.md",)),
    ("games/epic7/sanctuary.py", ("docs/maintenance/sanctuary.md",)),
    ("games/epic7/achievement.py", ("docs/maintenance/achievement.md",)),
    ("games/epic7/", ("docs/STATUS.md",)),
    # PC 移植这条线（2026-11-08 补）：主文档自称「PC 结论唯一权威」，但此前
    # DOC_RULES 里 0 条指向它 —— 改了窗口层、补了 pc 图都不会提醒复审那份 666 行文档。
    ("core/pc_window.py", ("docs/PC_TEMPLATE_MIGRATION.md", "docs/howto/live_verification.md")),
    ("games/epic7/template_paths.py", ("docs/PC_TEMPLATE_MIGRATION.md",)),
    ("games/epic7/templates/", ("docs/PC_TEMPLATE_MIGRATION.md",)),
    ("desktop/catalog.py", ("docs/STATUS.md", "docs/PC_TEMPLATE_MIGRATION.md")),
    ("main.py", ("docs/PC_TEMPLATE_MIGRATION.md",)),
    ("core/", ("docs/ARCHITECTURE.md", "docs/TRANSITION_CONTRACTS.md")),
    # 权限/实机这条线：知识与代码是「判断」，改了就一定要回头读那份手册。
    ("core/elevation.py", ("docs/howto/live_verification.md",)),
    ("desktop/preflight.py", ("docs/howto/live_verification.md", "docs/USER_GUIDE.md")),
    ("tools/live_check.py", ("docs/howto/live_verification.md",)),
    ("tools/_run_live", ("docs/howto/live_verification.md",)),
    ("tools/_verify_", ("docs/howto/live_verification.md",)),
    ("tools/_diagnose_", ("docs/howto/live_verification.md",)),
    ("desktop_qt/", ("docs/USER_GUIDE.md",)),
    ("desktop/", ("docs/USER_GUIDE.md",)),
    ("main.py", ("docs/USER_GUIDE.md", "docs/ARCHITECTURE.md")),
    ("packaging/", ("CONTRIBUTING.md",)),
    (".github/", ("CONTRIBUTING.md",)),
)

#: 这些路径的改动**不会**让任何文档过期（改了它们不必复审）。
IGNORED_PREFIXES = (
    "tests/",
    "tools/",
    "runtime_logs/",
    "runtime_diagnostics/",
)


# ---------------------------------------------------------------- 开发闭环
#
# 文档要能对开发有用，就得回答三件事：开工前读什么、改完更新什么、新发现沉淀到哪。
# 这张表是**唯一来源**：EXTENDING.md 等文档不要再抄一份「登记四处」，直接引用
# `doc_review --scenario <key>`。做成代码而不是新文档，是为了让它跟代码一起被门禁验。
#
# `section` 写标题前缀（不带动态数字），护栏会去文档里找 `## <section>` 开头的行。
# `target` 里带 `<...>` 是占位符，护栏跳过存在性检查。

@dataclass(frozen=True)
class DocStep:
    target: str
    section: str = ""
    why: str = ""


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    when: str
    triggers: tuple[str, ...]
    read_first: tuple[DocStep, ...]
    update_after: tuple[DocStep, ...]
    deposit: tuple[str, ...]
    verify: str = ""


#: 新增路线时手册必须有的六节。清单即模板，不再另建 _TEMPLATE.md。
ROUTE_MANUAL_SECTIONS = (
    "这条路线在游戏里干什么",
    "页面链路",
    "判据为什么这么设计",
    "危险边界",
    "现行事实",
    "已知缺口",
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="new-route",
        title="新增一条自动化路线",
        when="开工前先跑一次；改完代码、提交前再对照 update_after 逐项核",
        triggers=("games/epic7/modes.py", "desktop/catalog.py"),
        read_first=(
            DocStep("docs/STATUS.md", "一、路线总览", "现在有哪些路线、分组与放行状态；别撞名，也别把条数写死"),
            DocStep("docs/EXTENDING.md", "4. 注册模式", "注册要填哪些字段、两道准入关；复用优先，别重造轮子"),
            DocStep("docs/TRANSITION_CONTRACTS.md", "基本原则", "判据可证伪、转场两帧确认的最低要求"),
            DocStep("docs/SAFETY_MATRIX.md", "一、危险动作", "这条路线会不会花资源、靠什么拦住误点"),
            DocStep("docs/maintenance/<相近路线>.md", "判据为什么这么设计", "找一条同族路线照着抄结构"),
        ),
        update_after=(
            DocStep("docs/maintenance/<route>.md", ROUTE_MANUAL_SECTIONS[0],
                    "按六节新建：" + " / ".join(ROUTE_MANUAL_SECTIONS)
                    + "；数字、张数、尺寸一律链 STATUS，不手写"),
            DocStep("docs/README.md", "二、每条路线怎么维护", "登记新手册；第六节逐份总表补一行"),
            DocStep("docs/STATUS.md", "", "重生成（禁手改）：python -m auto_game_unified.tools.gen_status"),
            DocStep("docs/TODO.md", "PC 迁移矩阵", "补一行「未在 PC 上做过」，别把候选写成已支持"),
            DocStep("docs/SAFETY_MATRIX.md", "一、危险动作", "若这条路线花资源，补一行危险动作 × 拦截机制"),
            DocStep("docs/maintenance/pc_page_capture_checklist.md", "", "若上 PC，把该路线页面补进采页清单"),
        ),
        deposit=(
            "判据「为什么」变了 → 手册「判据为什么这么设计」那一节，把旧说法一并删掉",
            "推翻了既有决定 → docs/decisions/ 新增一条，旧文标 superseded",
            "发现新缺口 → docs/TODO.md「待验证 / 缺口登记」，别埋在手册里",
            "事故过程与实跑流水 → 提交信息 + .workbuddy/memory/，不进仓库文档",
        ),
        verify="python -m pytest -q tests/test_docs_index.py tests/test_status_doc.py tests/test_doc_review.py",
    ),
    Scenario(
        key="fix-bug",
        title="修 bug / 改判据 / 补识别素材",
        when="改代码前先看「当初为什么这么定」，别直接调阈值",
        triggers=("games/epic7/", "core/", "main.py"),
        read_first=(
            DocStep("docs/maintenance/<route>.md", "判据为什么这么设计", "先搞清当初靠哪一维排除外观同类"),
            DocStep("docs/STATUS.md", "一、路线总览", "确认这条路线的放行范围"),
            DocStep("docs/TRANSITION_CONTRACTS.md", "结论门槛", "这次改动有没有触碰判据门槛"),
        ),
        update_after=(
            DocStep("docs/maintenance/<route>.md", "判据为什么这么设计",
                    "只有「为什么」变了才改；改完顺手删掉同一判据的旧结论"),
            DocStep("docs/decisions/", "", "仅当推翻了既有决定时新增一条"),
            DocStep("docs/TODO.md", "待验证 / 缺口登记", "若暴露出新缺口"),
        ),
        deposit=(
            "新踩的坑只留结论 → 手册「判据为什么这么设计」；过程进提交信息 / 项目记忆",
            "新缺口 → docs/TODO.md「待验证 / 缺口登记」",
            "确实没有文档变化 → 提交信息写 Doc-reviewed: 无变化，不要造文档改动",
        ),
        verify="python -m auto_game_unified.tools.doc_review --staged",
    ),
    Scenario(
        key="new-mechanism",
        title="新增一个全局机制（新弹窗类 / 新通道 / 新公共层）",
        when="机制会跨路线生效，先确认它落在哪一层，再数清接触点",
        triggers=("games/epic7/global_popups.py", "games/epic7/runner_base.py",
                  "games/epic7/transactional_runner_base.py", "core/recovery_gate.py"),
        read_first=(
            DocStep("docs/ARCHITECTURE.md", "分层边界", "新机制该落在哪一层，别塞进某条路线"),
            DocStep("docs/ARCHITECTURE.md", "全局弹窗守卫", "新弹窗的接触点清单（dataclass/loader/find/装配/测试）"),
            DocStep("docs/TRANSITION_CONTRACTS.md", "基本原则", "契约有没有受影响"),
            DocStep("docs/PC_TEMPLATE_MIGRATION.md", "2. 真实差异清单", "会不会引入平台差异"),
        ),
        update_after=(
            DocStep("docs/ARCHITECTURE.md", "目录职责", "新模块上榜；若改了公共层，补「分层边界」"),
            DocStep("docs/README.md", "一、按你要做的事找", "若新增了开发入口，补一行"),
            DocStep("docs/TRANSITION_CONTRACTS.md", "", "若改变了契约或结论门槛"),
            DocStep("docs/maintenance/<受影响路线>.md", "判据为什么这么设计", "逐条路线改「为什么」，不写数字"),
        ),
        deposit=(
            "为什么引入这个机制 → docs/decisions/ 一条（回答当初为什么这么定）",
            "新缺口 → docs/TODO.md「待验证 / 缺口登记」",
            "实跑证据 → 提交信息 + .workbuddy/memory/，不进仓库文档",
        ),
        verify="python -m auto_game_unified.tools.doc_review --staged",
    ),
)


def scenario_for(changed: list[str]) -> Scenario | None:
    """按本次改动推断最可能的开发场景；拿不准就返回 None（宁可不提示，也不误报）。

    按**触发路径的特异性**择优，不按表顺序：``games/epic7/modes.py`` 必须压过
    ``games/epic7/``，否则「新增路线」永远被「修 bug」抢走；新增全局弹窗同理。
    """
    normalised = [p.strip().replace("\\", "/") for p in changed if p.strip()]
    code = [p for p in normalised if not p.startswith("docs/")]
    matches: list[tuple[int, Scenario]] = []
    for scenario in SCENARIOS:
        for trigger in scenario.triggers:
            if any(p.startswith(trigger) for p in code):
                matches.append((len(trigger), scenario))
                break
    if not matches:
        return None
    # 同长度时保留表中靠前的那个（max 对相等值取首个）
    return max(matches, key=lambda item: item[0])[1]


def affected_docs(changed: list[str]) -> list[str]:
    """改动文件清单 → 需要复审的文档（去重、排序）。

    纯函数：不碰 git、不碰磁盘，方便直接拿假数据验。

    判定顺序：**先看规则，再看忽略名单** —— 否则 ``tools/`` 整体被忽略之后，
    ``tools/live_check.py`` 这种「本来就该提醒复审手册」的路径永远轮不到。
    """
    docs: set[str] = set()
    for path in changed:
        normalised = path.strip().replace("\\", "/")
        if not normalised:
            continue
        if normalised.startswith("docs/"):
            # 文档自己改了，就不用「提醒你去看它」了。
            continue
        matched = False
        for prefix, targets in DOC_RULES:
            if normalised.startswith(prefix):
                docs.update(targets)
                matched = True
        if matched:
            continue
        if normalised.startswith(IGNORED_PREFIXES):
            continue
    return sorted(docs)


#: 提交信息里的复审留痕标记。大小写敏感，写错等于没留。
REVIEW_NOTE = "Doc-reviewed:"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout


def staged_files() -> list[str]:
    """本次暂存区改了哪些文件。提交钩子用它 —— 天然包含还没提交的改动。"""
    return [line for line in _git("diff", "--cached", "--name-only").splitlines() if line.strip()]


def working_files() -> list[str]:
    """工作区相对 HEAD 的全部改动（含未暂存），日常自查用。"""
    return [line for line in _git("diff", "--name-only", "HEAD").splitlines() if line.strip()]


def review_note_missing(message_path: Path, docs: list[str]) -> bool:
    """命中了复审规则、但提交信息没留痕 ⇒ 返回 True（应当拒绝提交）。

    只验证「有没有留痕」，不假装能验证「有没有真读」—— 后者是人的判断。
    """
    if not docs:
        return False
    try:
        message = Path(message_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return REVIEW_NOTE not in message


def _step_line(step: DocStep) -> str:
    location = step.target + (f" §{step.section}" if step.section else "")
    return location + (f" — {step.why}" if step.why else "")


def print_scenario(scenario: Scenario) -> None:
    """开工前打印：读什么 → 改什么 → 新发现往哪沉淀 → 怎么验闭环。"""
    print(f"=== {scenario.title}（{scenario.key}）===")
    print(scenario.when)
    print("\n【开工前先读：了解现状再动手】")
    for index, step in enumerate(scenario.read_first, 1):
        print(f"  {index}. {_step_line(step)}")
    print("\n【改完代码后要更新：有变化才改，没变化就不造文档动作】")
    for index, step in enumerate(scenario.update_after, 1):
        print(f"  {index}. {_step_line(step)}")
    print("\n【新发现沉淀到哪】")
    for item in scenario.deposit:
        print(f"  - {item}")
    if scenario.verify:
        print(f"\n【闭环校验】{scenario.verify}")


def _print_scenario_hint(scenario: Scenario, *, stream) -> None:
    print(f"[doc-review] 本次改动属于场景「{scenario.title}」({scenario.key})，改完代码后该同步：",
          file=stream)
    for step in scenario.update_after:
        print(f"  - {_step_line(step)}", file=stream)
    print(f"[doc-review] 开工前读什么、新发现往哪沉淀：doc_review --scenario {scenario.key}",
          file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按本次改动列出该复审的文档 / 打印开发闭环清单")
    parser.add_argument("--staged", action="store_true", help="只看暂存区（提交钩子用）")
    parser.add_argument(
        "--require-note", default="", help="提交信息文件路径；命中规则却没留痕就返回 1"
    )
    parser.add_argument("--scenario", default="", help="打印某个开发场景的开工 / 收尾清单")
    parser.add_argument("--scenarios", action="store_true", help="列出所有可用场景")
    args = parser.parse_args(argv)

    if args.scenarios:
        print("可用场景：")
        for scenario in SCENARIOS:
            print(f"  {scenario.key:16s} {scenario.title} — {scenario.when}")
        print("\n开工前跑：python -m auto_game_unified.tools.doc_review --scenario new-route")
        return 0

    if args.scenario:
        scenario = next((item for item in SCENARIOS if item.key == args.scenario), None)
        if scenario is None:
            print(
                f"未知场景 {args.scenario!r}；可用：{', '.join(s.key for s in SCENARIOS)}",
                file=sys.stderr,
            )
            return 1
        print_scenario(scenario)
        return 0

    changed = staged_files() if args.staged else working_files()
    docs = affected_docs(changed)
    scenario = scenario_for(changed)

    if args.require_note:
        if review_note_missing(args.require_note, docs):
            print("[doc-review] 本次改动命中了文档复审规则，但提交信息里没有留痕。", file=sys.stderr)
            print("[doc-review] 该复审：", file=sys.stderr)
            for doc in docs:
                print(f"  - {doc}", file=sys.stderr)
            if scenario:
                _print_scenario_hint(scenario, stream=sys.stderr)
            print(
                f"[doc-review] 看过之后在提交信息里加一行「{REVIEW_NOTE} 改了哪几份 / 无变化」"
                "（确实没有变化就写「无变化」，不要为了留痕造文档改动）。",
                file=sys.stderr,
            )
            print("[doc-review] CI 会在干净检出上再查一遍。", file=sys.stderr)
            return 1
        print(f"[doc-review] 复审留痕已确认（{len(docs)} 份）。")
        return 0

    source = "暂存区" if args.staged else "工作区相对 HEAD"
    if not docs:
        print(f"{source}的改动不影响任何文档。")
    else:
        print(f"{source}的改动需要复审 {len(docs)} 份文档：")
        for doc in docs:
            exists = "" if (REPO_ROOT / doc).exists() else "  （文件不存在，考虑清理规则或补写）"
            print(f"  {doc}{exists}")
        print(f"\n看完在提交信息里加一行 {REVIEW_NOTE} 说明改了哪几份（没变化就写「无变化」）。")
    if scenario:
        print()
        _print_scenario_hint(scenario, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
