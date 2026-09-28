"""只读测量：共享模板在 PC 画面上到底够不够用。

背景
----
PC 客户端已经能截图和点击，但所有路线仍在使用**同一套为模拟器采集的**模板。
两边字体、抗锯齿、亮度不同 ⇒ 同一张图在 PC 上匹配分数被压低，于是代码里长出一批
「PC 专用阈值」补丁（`evidence/{story,arena,hero_synthesis}.py` 的
`PC_THRESHOLD_OVERRIDES`，以及 arena / navigation / hero_synthesis 里就地写死的三元表达式）。

**2026-09-28：那批补丁已经全删了。** 平台差异现在只允许存在于**图片**
（`templates/<路线>/pc/<同名图>.png`，机制见 `games/epic7/template_paths.py`）。
所以本工具的结论从「要不要多一列阈值」变成一句话：**哪些锚点真的需要那张 PC 图。**

判据
----
对每个证据锚点，分别在「模拟器整帧」和「PC 整帧」上求区域限定匹配的最高分：

| emu_max | pc_max | 判定 | 含义 |
| --- | --- | --- | --- |
| 过阈 | 未过阈 | **需要 PC 专属图** | 典型的跨客户端渲染差异，换图能解决 |
| 未过阈 | 未过阈 | **两侧都低，先查覆盖** | 多半是手里没有该锚点的正例帧；先补覆盖再下结论 |
| 过阈 | 过阈 | 共用图够用 | 不需要 PC 图 |
| 过阈 | 勉强过阈（余量 < 0.05） | **余量偏小** | 能用但脆弱，建议也换一张 |

为什么必须两侧都量
------------------
只量 PC 会把「这一页我们压根没拍到」误报成「渲染差异」。
`emu_max` 也低就说明手里没有该锚点的正例帧（模板的裁切来源常常不在 `tests/fixtures/` 里），
那是覆盖问题而不是渲染问题，不该混进「要换哪张图」的清单。

⚠️ 预期内的假象：内容明显是「同一块 UI」的锚点，`emu_max` 常常正好是 `1.000` ——
因为模板就是从某个夹具裁出来的。所以 `emu_max ≈ 1.0` **不能**当成「阈值标定良好」的证明，
它只说明「这个锚点不是死的」。

覆盖范围
--------
只有**两个客户端都拍过**的页面能量出结论。PC 侧目前仅主线、英雄合成、竞技场
有实拍帧；其余路线一律列进「无法测量」，等用户在 PC 上拍到那一页才有数据。

只读
----
不写任何文件（除非显式 `--out` / `--json`）、不改模板、不开窗口、不需要管理员。
调用的是生产诊断同一个 `inspect_profile`，量出来的分数与真跑一致。

用法（任意目录均可）：
    D:\\anaconda\\python.exe auto_game_unified/tools/report_pc_template_scores.py
    D:\\anaconda\\python.exe auto_game_unified/tools/report_pc_template_scores.py --out 某处.md
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path

import cv2

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.core.pc_window import (
    REFERENCE_SIZE,
    RENDER_SIZE,
    Epic7PcWindow,
)
from auto_game_unified.games.epic7.evidence.arena import build_arena_evidence
from auto_game_unified.games.epic7.evidence.expedition import (
    build_expedition_evidence,
)
from auto_game_unified.games.epic7.evidence.hero_synthesis import (
    build_hero_evidence,
)
from auto_game_unified.games.epic7.evidence.knights_donation import (
    build_knights_donation_evidence,
)
from auto_game_unified.games.epic7.evidence.labyrinth_stone import (
    build_labyrinth_stone_evidence,
)
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    build_shop_refresh_evidence,
)
from auto_game_unified.games.epic7.evidence.story import build_story_evidence
from auto_game_unified.games.epic7.evidence.survivor import build_survivor_evidence
from auto_game_unified.games.epic7.evidence.world_boss import (
    build_world_boss_evidence,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState

SAFE_STATE = EvidenceState.SAFE

# 纯序号连拍帧（`07.jpg` / `00.png`）本身不含页面信息，展示时排到最后。
NUMERIC_BURST_RE = re.compile(r"^\d+\.(jpg|jpeg|png|bmp)$", re.IGNORECASE)

PACKAGE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = PACKAGE_DIR / "games" / "epic7" / "templates"
FIXTURES_ROOT = PACKAGE_DIR / "tests" / "fixtures"
# 人工复核帧：比 `tests/fixtures/` 新得多（常常就是当天的真机画面），
# 是「模拟器侧正例」的补充来源。按 `docs/manual_review/<路线名>/` 组织。
MANUAL_REVIEW_ROOT = PACKAGE_DIR / "docs" / "manual_review"

# 判定阈值：PC 侧余量小于它就算「脆弱」，即使当前能过阈。
FRAGILE_MARGIN = 0.05

VERDICT_NEEDS_PC_IMAGE = "需要 PC 专属图"
VERDICT_FRAGILE = "余量偏小"
VERDICT_SHARED_OK = "共用图够用"
# ⚠️ 不要叫它「判据偏弱」：两侧都低**通常只是手里没有该锚点的正例帧**
# （模板的裁切来源可能不在 tests/fixtures 里）。所以这一档的正确动作是
# 「先查覆盖」，而不是「断言这条判据不行」。
VERDICT_BOTH_LOW = "两侧都低，先查覆盖"


@dataclass(frozen=True)
class RoutePlan:
    """一条路线的测量计划。

    ``template_subdirs`` 是按优先级排的候选模板目录（``None`` = 模板根）。
    各路线证据模块对「根目录」的理解并不统一（竞技场把图放在模板根、
    故事放在 ``templates/story``），所以这里**不猜**：逐个候选建画像，
    取第一个「所有必填锚点的文件都存在」的。猜错的候选会打印告警。
    """

    name: str
    builder: object
    template_subdirs: tuple[str | None, ...]
    emulator_fixtures: tuple[str, ...]
    pc_fixtures: tuple[str, ...]


ROUTES: tuple[RoutePlan, ...] = (
    RoutePlan(
        "story",
        build_story_evidence,
        ("story", None),
        ("epic7_story",),
        ("epic7_pc_story",),
    ),
    RoutePlan(
        "arena",
        build_arena_evidence,
        (None, "arena"),
        ("epic7_arena",),
        ("epic7_pc_arena",),
    ),
    RoutePlan(
        "hero_synthesis",
        build_hero_evidence,
        ("hero", None),
        ("epic7_hero",),
        ("epic7_pc_hero", "epic7_pc_shared_hero"),
    ),
    RoutePlan(
        "expedition",
        build_expedition_evidence,
        ("expedition",),
        ("epic7_expedition",),
        (),
    ),
    RoutePlan(
        "knights_donation",
        build_knights_donation_evidence,
        ("knights_donation",),
        ("epic7_knights_donation",),
        (),
    ),
    RoutePlan(
        "labyrinth_stone",
        build_labyrinth_stone_evidence,
        ("labyrinth_stone",),
        ("epic7_labyrinth_stone",),
        (),
    ),
    RoutePlan(
        "shop_refresh",
        build_shop_refresh_evidence,
        ("shop_refresh", None),
        ("epic7_shop_refresh",),
        (),
    ),
    RoutePlan(
        "survivor",
        build_survivor_evidence,
        ("survivor",),
        ("epic7_survivor",),
        (),
    ),
    RoutePlan(
        "world_boss",
        build_world_boss_evidence,
        ("world_boss",),
        ("epic7_world_boss",),
        (),
    ),
)

# 在 PC 迁移表/业务流程里存在、但没有独立证据画像 ⇒ 本工具量不了它们，
# 单独列出来，免得报告看起来「漏了几条路线」。
NO_PROFILE_TARGETS = (
    ("fodder（狗粮）", "复用 story 的证据画像，没有自己的锚点表"),
    ("navigation（大厅导航）", "有 43 处模板读取，但没有 EvidenceProfile"),
    ("global_popups（全局弹窗）", "有 14 处模板读取，但没有 EvidenceProfile"),
    ("pre_battle / stamina / home_return", "只有少量模板读取，没有 EvidenceProfile"),
    ("daily（每日任务）", "是编排入口，不是路线"),
)


# 人工复核目录名与路线名不一致的地方（其余同名）。
REVIEW_SUBDIR_ALIASES = {"hero_synthesis": "hero_synthesis_crops"}


def load_canvas(path: Path):
    """把一张夹具读成 1982x1132 兼容画布；不是整帧就返回 None。

    1920x1080 的裸客户区截图走**生产同一个**补边函数，避免两套换算漂移。
    """
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    shape = image.shape[:2]
    if shape == (REFERENCE_SIZE[1], REFERENCE_SIZE[0]):
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    if shape == (RENDER_SIZE[1], RENDER_SIZE[0]):
        return Epic7PcWindow._legacy_canvas(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    return None


def collect_frames(directory: Path) -> tuple[list[tuple[Path, object]], int]:
    """返回 (可用整帧, 跳过的非整帧数量)。"""
    frames: list[tuple[Path, object]] = []
    skipped = 0
    if not directory.is_dir():
        return frames, skipped
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            continue
        canvas = load_canvas(path)
        if canvas is None:
            skipped += 1
            continue
        frames.append((path, canvas))
    return frames, skipped


def call_builder(builder, root: Path, backend: str):
    """按构建器**实际签名**决定传不传 ``backend``。

    ⚠️ 这里踩过一次坑：骑士团捐赠 / 迷宫强化石 / 世界首领战 / 刷书签 / 活动的
    证据构建器还没有 ``backend`` 形参，一律按 keyword 传会 `TypeError`，
    而那个异常会被「候选目录选错」的分支吞掉 ⇒ 这 5 条路线整条静默不测。
    所以必须先看签名，再决定怎么调。
    """
    try:
        parameters = inspect.signature(builder).parameters
    except (TypeError, ValueError):  # 拿不到签名时退回更保守的调用方式
        parameters = {}
    if "backend" in parameters:
        return builder(root, backend=backend)
    return builder(root)


def resolve_profile(plan: RoutePlan) -> tuple[Path | None, object | None, str]:
    """挑出能解析**全部**必填锚点的模板目录，并返回该目录下的模拟器基线画像。

    ⚠️ 两个已踩过的坑：
    1. 候选目录顺序不能只写 ``templates/<路线名>`` —— 有些路线的锚点路径**自带**
       子目录前缀（活动是 `survivor/xxx.png`），正确根是 `templates` 而不是
       `templates/survivor`；拼错会得到一个 `survivor/survivor/xxx.png` 并崩在解码上。
       所以候选表末尾**永远补一个模板根**兜底。
    2. 不能「差一个也算成功」：只要还有必填锚点找不到文件，就必须判成解析失败，
       否则会把不完整画像带进测量，量出来的分数没有意义。
    """
    notes: list[str] = []
    candidates: list[Path] = []
    for subdir in plan.template_subdirs:
        candidate = TEMPLATES_ROOT / subdir if subdir else TEMPLATES_ROOT
        if candidate not in candidates:
            candidates.append(candidate)
    if TEMPLATES_ROOT not in candidates:
        candidates.append(TEMPLATES_ROOT)

    for root in candidates:
        if not root.is_dir():
            notes.append(f"候选目录不存在: {root}")
            continue
        try:
            profile = call_builder(plan.builder, root, "emulator")
        except Exception as error:  # 候选目录选错时会解码失败，属预期
            notes.append(f"{root} 建画像失败: {error}")
            continue
        missing = [
            key
            for key, atom in profile.atoms.items()
            if atom.required and not (root / atom.template_path).is_file()
        ]
        if not missing:
            return root, profile, ""
        notes.append(f"{root} 缺 {len(missing)} 个必填模板（如 {missing[0]}）")
    return None, None, "；".join(notes) or "没有可用候选目录"


def measure(profile, root: Path, frames) -> tuple[dict, dict, list]:
    """逐帧求每个锚点的区域限定最高分，同时统计页面成立情况。

    返回 ``(key -> (最高分, 帧名), 页面 -> 成立帧数, 没有任何页面成立的帧名列表)``。

    第三个返回值是**分辨「渲染差异」与「这一页没拍到」的关键**：
    帧名本身就说明它拍的是哪个页面（`03_filter_open.png`、`team_select.png`），
    所以「这一帧上没有任何页面成立」而帧名又明显是目标页 ⇒ 真的是认不出来；
    帧名根本不是那一页 ⇒ 只是没采集。
    """
    best: dict[str, tuple[float, str]] = {}
    page_hits: dict[str, int] = {}
    without_page: list[str] = []
    for path, canvas in frames:
        inspection = inspect_profile(canvas, profile, root)
        for key, observation in inspection.atoms.items():
            if observation.score is None:
                continue
            current = best.get(key)
            if current is None or observation.score > current[0]:
                best[key] = (observation.score, path.name)
        safe = [key for key, state in inspection.pages.items() if state is SAFE_STATE]
        for key in safe:
            page_hits[key] = page_hits.get(key, 0) + 1
        if not safe:
            without_page.append(path.name)
    return best, page_hits, without_page


def atom_pages(profile) -> dict[str, tuple[str, ...]]:
    """反查每个锚点被哪些页面引用。

    只取页面的 ``required`` / ``any_of`` / ``forbidden`` 集合。竞技场用的是自定义
    ``page_evaluator``，这里读到的仍是它的 ``_PAGES`` 声明集合 —— 够用来判断
    「这个锚点的页面在 PC 上成立过没有」，不追求与求值函数逐字等价。
    """
    mapping: dict[str, list[str]] = {key: [] for key in profile.atoms}
    for page in profile.pages:
        references = set(page.required) | set(page.forbidden)
        for group in page.any_of:
            references |= set(group)
        for key in references:
            if key in mapping and page.key not in mapping[key]:
                mapping[key].append(page.key)
    return {key: tuple(pages) for key, pages in mapping.items()}


def classify(emu_max: float | None, pc_max: float | None, threshold: float) -> str:
    if pc_max is None:
        return "PC 帧上未算出分数"
    if pc_max < threshold:
        if emu_max is not None and emu_max >= threshold:
            return VERDICT_NEEDS_PC_IMAGE
        return VERDICT_BOTH_LOW
    if pc_max - threshold < FRAGILE_MARGIN:
        return VERDICT_FRAGILE
    return VERDICT_SHARED_OK


def measure_route(plan: RoutePlan) -> dict:
    root, profile, note = resolve_profile(plan)
    record = {
        "route": plan.name,
        "template_root": str(root) if root else "",
        "error": note if root is None else "",
        "atoms": [],
        "emulator_frames": 0,
        "review_frames": 0,
        "pc_frames": 0,
        "skipped": [],
        "emu_pages": {},
        "pc_pages": {},
        "pc_frames_without_page": [],
    }
    if root is None or profile is None:
        return record

    emulator_frames: list[tuple[Path, object]] = []
    for name in plan.emulator_fixtures:
        frames, skipped = collect_frames(FIXTURES_ROOT / name)
        emulator_frames.extend(frames)
        if skipped:
            record["skipped"].append(f"{name}: {skipped}")
    review_name = REVIEW_SUBDIR_ALIASES.get(plan.name, plan.name)
    review_frames, review_skipped = collect_frames(MANUAL_REVIEW_ROOT / review_name)
    emulator_frames.extend(review_frames)
    record["review_frames"] = len(review_frames)
    if review_skipped:
        record["skipped"].append(f"manual_review/{review_name}: {review_skipped}")
    pc_frames: list[tuple[Path, object]] = []
    for name in plan.pc_fixtures:
        frames, skipped = collect_frames(FIXTURES_ROOT / name)
        pc_frames.extend(frames)
        if skipped:
            record["skipped"].append(f"{name}: {skipped}")

    record["emulator_frames"] = len(emulator_frames)
    record["pc_frames"] = len(pc_frames)

    emu_scores, emu_pages, _ = measure(profile, root, emulator_frames)
    if pc_frames:
        pc_scores, pc_pages, pc_frames_without_page = measure(profile, root, pc_frames)
    else:
        pc_scores, pc_pages, pc_frames_without_page = {}, {}, []
    record["emu_pages"] = emu_pages
    record["pc_pages"] = pc_pages
    record["pc_frames_without_page"] = pc_frames_without_page

    pages_of_atom = atom_pages(profile)
    rows = []
    for key, atom in profile.atoms.items():
        emu_max = emu_scores.get(key, (None, ""))[0]
        pc_max, pc_frame = pc_scores.get(key, (None, ""))
        owner_pages = pages_of_atom.get(key, ())
        # 这个锚点所属的页面，有没有在 PC 帧上成功成立过？
        # 成立过 ⇒ 页面本身能认出来，同页其它锚点的问题就是真的。
        # ``None`` = 这个锚点不被任何页面引用（被状态机直接读），页面口径对它不适用。
        if owner_pages:
            page_covered: bool | None = any(
                pc_pages.get(page, 0) > 0 for page in owner_pages
            )
        else:
            page_covered = None
        # ⚠️ 2026-09-28：原来这里还有「PC 专用阈值补丁救不救得了」一列。
        # 门槛分叉已经从代码里删干净了（平台差异只存在于图片），那一列永远等于
        # 模拟器基线 ⇒ 留着只会让人以为「还有一层补丁在干活」。要看够不够，
        # 看「余量」列就行（余量 = pc_max - 模拟器阈值）。
        rows.append(
            {
                "key": key,
                "template_path": atom.template_path,
                "region": list(atom.region),
                "required": atom.required,
                "pages": list(owner_pages),
                "page_covered": page_covered,
                "emu_threshold": atom.threshold,
                "emu_max": emu_max,
                "pc_max": pc_max,
                "pc_frame": pc_frame,
                "verdict": classify(emu_max, pc_max, atom.threshold),
            }
        )

    order = {
        VERDICT_NEEDS_PC_IMAGE: 0,
        VERDICT_FRAGILE: 1,
        VERDICT_BOTH_LOW: 2,
        VERDICT_SHARED_OK: 3,
        "PC 帧上未算出分数": 4,
    }
    covered_rank = {True: 0, None: 1, False: 2}
    rows.sort(
        key=lambda row: (
            order.get(row["verdict"], 9),
            covered_rank.get(row["page_covered"], 3),
            row["key"],
        )
    )
    record["atoms"] = rows
    return record


def _cell(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _covered_cell(value) -> str:
    """``page_covered`` 的三态显示。``None`` 不是「否」，是「页面口径不适用」。"""
    if value is None:
        return "不适用"
    return "是" if value else "**否**"


def render_markdown(records: list[dict], top: int) -> str:
    lines: list[str] = []
    lines.append("# PC 共享模板适用性测量")
    lines.append("")
    lines.append(
        "只读报告，由 `tools/report_pc_template_scores.py` 生成。"
        "判据与生产诊断同一套（`inspect_profile` + 区域限定 `TM_CCOEFF_NORMED`）。"
    )
    lines.append("")

    measurable = [r for r in records if r["atoms"] and r["pc_frames"]]
    unmeasurable = [r for r in records if not (r["atoms"] and r["pc_frames"])]
    needs = [
        (r["route"], a)
        for r in measurable
        for a in r["atoms"]
        if a["verdict"] == VERDICT_NEEDS_PC_IMAGE
    ]
    fragile = [
        (r["route"], a)
        for r in measurable
        for a in r["atoms"]
        if a["verdict"] == VERDICT_FRAGILE
    ]
    weak = [
        (r["route"], a)
        for r in measurable
        for a in r["atoms"]
        if a["verdict"] == VERDICT_BOTH_LOW
    ]
    ok = [
        (r["route"], a)
        for r in measurable
        for a in r["atoms"]
        if a["verdict"] == VERDICT_SHARED_OK
    ]

    trusted_count = sum(1 for _, atom in needs + fragile if atom["page_covered"] is True)
    pending_count = sum(1 for _, atom in needs + fragile if atom["page_covered"] is False)
    direct_count = sum(1 for _, atom in needs + fragile if atom["page_covered"] is None)
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"- 可测量路线 **{len(measurable)}** 条 / 无 PC 帧无法测量 **{len(unmeasurable)}** 条")
    lines.append(
        f"- 模拟器过阈但 PC 一次没过阈的锚点：**{len(needs) + len(fragile)}** 个"
        f"（其中余量偏小 {len(fragile)} 个）"
    )
    lines.append(f"  - 所属页面在 PC 上成立过 ⇒ **可信**：**{trusted_count}** 个")
    lines.append(f"  - 所属页面在 PC 上从没成立 ⇒ 待确认：**{pending_count}** 个")
    lines.append(f"  - 不被任何页面引用（状态机直接读）⇒ 只能实跑验证：**{direct_count}** 个")
    lines.append(f"- {VERDICT_BOTH_LOW}：{len(weak)} 个锚点")
    lines.append(f"- {VERDICT_SHARED_OK}：{len(ok)} 个锚点")
    lines.append("")

    if needs or fragile:
        trusted = [
            (route, atom)
            for route, atom in needs + fragile
            if atom["page_covered"] is True
        ]
        pending = [
            (route, atom)
            for route, atom in needs + fragile
            if atom["page_covered"] is False
        ]
        direct = [
            (route, atom)
            for route, atom in needs + fragile
            if atom["page_covered"] is None
        ]

        def _table(title: str, rows_in: list, note: str) -> None:
            if not rows_in:
                return
            lines.append(f"### {title}")
            lines.append("")
            lines.append(note)
            lines.append("")
            lines.append(
                "| 路线 | 锚点 | 所属页面 | 模板文件 | 模拟器阈值 | emu_max | pc_max "
                "| 余量 | pc_max 所在帧 |"
            )
            lines.append(
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |"
            )
            for route, atom in rows_in:
                margin = atom["pc_max"] - atom["emu_threshold"]
                pages = "、".join(f"`{page}`" for page in atom["pages"]) or "-"
                lines.append(
                    f"| {route} | `{atom['key']}` | {pages} | `{atom['template_path']}` "
                    f"| {_cell(atom['emu_threshold'])} "
                    f"| {_cell(atom['emu_max'])} | {_cell(atom['pc_max'])} "
                    f"| {margin:+.3f} | `{atom['pc_frame']}` |"
                )
            lines.append("")

        _table(
            f"清单 A1：可信 —— 所属页面在 PC 上成功成立过（{len(trusted)} 个锚点）",
            trusted,
            "这些锚点的页面**已经能在 PC 上认出来**，说明该页的 PC 帧是有的；"
            "同页里这几个锚点却过不了阈 ⇒ **就是跨客户端渲染差异，补一张 PC 专属图即可。**",
        )
        _table(
            f"清单 A2：待确认 —— 所属页面在 PC 上从未成立（{len(pending)} 个锚点）",
            pending,
            "⚠️ **不要直接当成「需要换图」。**这一档里混着两种情况："
            "① 该页拍到了但整体认不出来（真问题）；② 该页压根没有 PC 帧（缺数据）。"
            "**回去看该路线那一节的「一个页面都没成立的 PC 帧」清单**："
            "帧名明显就是这一页 ⇒ 情况 ①；看不到该页的帧名 ⇒ 情况 ②。",
        )
        _table(
            f"清单 A3：页面口径不适用 —— 锚点被状态机直接读（{len(direct)} 个锚点）",
            direct,
            "这些锚点不属于任何 `PageEvidence`，是状态机在业务动作里直接读的。"
            "它们的 `pc_max` 只能做为参考，**唯一有效的验证是干跑与实跑**。",
        )

    if weak:
        lines.append(f"### 清单 B：{VERDICT_BOTH_LOW}（**不是**换图的问题）")
        lines.append("")
        lines.append(
            "模拟器侧最高分也没到阈值。最常见的原因是**手里没有该锚点的正例帧**"
            "（模板的裁切来源不在 `tests/fixtures/` 与 `docs/manual_review/` 里），"
            "其次是判据确实没有安全间隔。**先补覆盖，再谈换图。**"
        )
        lines.append("")
        lines.append("| 路线 | 锚点 | 模拟器阈值 | emu_max | pc_max | 两侧差距 |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
        for route, atom in weak:
            gap = (
                f"{atom['pc_max'] - atom['emu_max']:+.3f}"
                if atom["pc_max"] is not None
                else "-"
            )
            lines.append(
                f"| {route} | `{atom['key']}` | {_cell(atom['emu_threshold'])} "
                f"| {_cell(atom['emu_max'])} | {_cell(atom['pc_max'])} | {gap} |"
            )
        lines.append("")

    for record in records:
        lines.append(f"## {record['route']}")
        lines.append("")
        if record["error"]:
            lines.append(f"⚠️ 无法测量：{record['error']}")
            lines.append("")
            continue
        lines.append(
            f"模板目录 `{record['template_root']}`；"
            f"模拟器整帧 {record['emulator_frames']}"
            f"（其中人工复核帧 {record['review_frames']}），PC 整帧 {record['pc_frames']}，"
            f"锚点 {len(record['atoms'])} 个。"
        )
        if record["skipped"]:
            lines.append("")
            lines.append(f"跳过的非整帧素材：{'、'.join(record['skipped'])}")
        lines.append("")
        if not record["pc_frames"]:
            lines.append("**没有 PC 实拍帧 ⇒ 一个锚点也量不了。**需要先在该路线的 PC 页面上采集整帧。")
            lines.append("")
            continue

        lines.append("### 页面在两侧的成立情况（**先看这张表再读下面的锚点表**）")
        lines.append("")
        lines.append("| 页面 | 模拟器成立帧数 | PC 成立帧数 |")
        lines.append("| --- | ---: | ---: |")
        page_keys = sorted(set(record["emu_pages"]) | set(record["pc_pages"]))
        for page in page_keys:
            lines.append(
                f"| `{page}` | {record['emu_pages'].get(page, 0)} "
                f"| {record['pc_pages'].get(page, 0)} |"
            )
        covered = sum(1 for page in page_keys if record["pc_pages"].get(page, 0))
        lines.append("")
        lines.append(
            f"PC 侧成立过的页面：**{covered} / {len(page_keys)}**。"
            "没成立的页面，下面的锚点分数**分不清是「渲染差异」还是「这一页压根没拍到」**。"
        )
        lines.append("")
        if record["pc_frames_without_page"]:
            # 有意义的帧名（`team_select.png`）排在纯序号连拍（`07.jpg`）前面 ——
            # 这一段的用途就是「看帧名认页面」，被连拍号刷屏等于没用。
            named = [
                name
                for name in record["pc_frames_without_page"]
                if not NUMERIC_BURST_RE.match(name)
            ]
            numbered = [
                name
                for name in record["pc_frames_without_page"]
                if NUMERIC_BURST_RE.match(name)
            ]
            ordered = named + numbered
            shown = ordered[:20]
            more = len(ordered) - len(shown)
            lines.append(
                f"**一个页面都没成立的 PC 帧（{len(ordered)} 张，共 "
                f"{len(named)} 张带描述性帧名）**"
                "：看帧名判断该页是否拍到了 —— 帧名就是那一页却认不出来，才是真问题。"
            )
            lines.append("")
            for name in shown:
                lines.append(f"- `{name}`")
            if more > 0:
                lines.append(f"- …另有 {more} 张（多为连拍序号帧）")
            lines.append("")

        lines.append(
            "| 锚点 | 所属页面 | 页面 PC 成立过？ | 模拟器阈值 | emu_max | pc_max | 余量 | 判定 | pc_max 所在帧 |"
        )
        lines.append(
            "| --- | --- | :---: | ---: | ---: | ---: | ---: | --- | --- |"
        )
        for atom in record["atoms"]:
            margin = (
                f"{atom['pc_max'] - atom['emu_threshold']:+.3f}"
                if atom["pc_max"] is not None
                else "-"
            )
            pages = "、".join(f"`{page}`" for page in atom["pages"]) or "-"
            lines.append(
                f"| `{atom['key']}` | {pages} | {_covered_cell(atom['page_covered'])} "
                f"| {_cell(atom['emu_threshold'])} "
                f"| {_cell(atom['emu_max'])} "
                f"| {_cell(atom['pc_max'])} | {margin} "
                f"| {atom['verdict']} | `{atom['pc_frame']}` |"
            )
        lines.append("")

    lines.append("## 未纳入测量的对象")
    lines.append("")
    lines.append("| 对象 | 原因 |")
    lines.append("| --- | --- |")
    for name, reason in NO_PROFILE_TARGETS:
        lines.append(f"| {name} | {reason} |")
    lines.append("")

    lines.append("## 读法提醒")
    lines.append("")
    lines.append(
        "- `pc_max` 是**所有 PC 整帧里最高的那一分**。取不到高分只说明「手里这些帧都认不出来」，"
        "不等于该锚点在真机上一定坏 —— 但足以说明**现在这些帧覆盖不到它**。"
    )
    lines.append(
        "- `emu_max ≈ 1.000` 是预期内的：模板就是从某个夹具裁出来的。"
        "**不要**把它当成「阈值标定良好」的证据，它只说明该锚点不是死的。"
    )
    lines.append(
        "- 「余量」= `pc_max - 模拟器阈值`。**负得越多，越需要一张该锚点的 PC 图**。"
        "2026-09-28 起代码里已经没有 PC 门槛表了（平台差异只允许存在于图片），"
        "所以不再有「降阈值救得回」这一列 —— 阈值就是唯一那套模拟器基线。"
    )
    lines.append(
        "- 本报告只回答「哪里需要一张 PC 图」，不代表任何路线已完成 PC 迁移；"
        "迁移门槛仍是 dry-run、1 轮、2 轮实跑逐项过。"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="只读测量共享模板在 PC 画面上的适用性")
    parser.add_argument("--out", type=Path, help="把 markdown 报告写到该路径")
    parser.add_argument("--json", type=Path, help="把原始测量数据写成 JSON")
    parser.add_argument("--route", action="append", help="只测指定路线，可重复")
    parser.add_argument("--top", type=int, default=0, help="保留参数，仅用于排序调试")
    args = parser.parse_args(argv)

    plans = [
        plan
        for plan in ROUTES
        if not args.route or plan.name in args.route
    ]
    if not plans:
        print(f"没有匹配的路线：{args.route}", file=sys.stderr)
        return 2

    records: list[dict] = []
    for plan in plans:
        print(f"[测量] {plan.name} ...", file=sys.stderr, flush=True)
        try:
            records.append(measure_route(plan))
        except Exception as error:
            # 诊断工具的价值在于「把能量的都量出来」：一条路线炸了不该让整份报告消失。
            print(f"[跳过] {plan.name} 测量失败：{error}", file=sys.stderr, flush=True)
            records.append(
                {
                    "route": plan.name,
                    "template_root": "",
                    "error": f"测量中断：{error}",
                    "atoms": [],
                    "emulator_frames": 0,
                    "review_frames": 0,
                    "pc_frames": 0,
                    "skipped": [],
                    "emu_pages": {},
                    "pc_pages": {},
                    "pc_frames_without_page": [],
                }
            )

    report = render_markdown(records, args.top)
    print(report)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"已写出报告 {args.out}", file=sys.stderr)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已写出原始数据 {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
