"""界面文案的表述规范护栏（2026-11-13 用户定：统一为说明 / 指南体）。

用户原话：「助手各个界面的文案都保持这种说明的这种指南的这种风格，不要说得这么
通俗易懂，讲白话一样的，就保持那种指南说明的，把事情讲清楚，且和代码匹配，
不要过期，注重业务逻辑，不要说技术细节」。

表述基准取自参考项目的**实际界面字符串**（不是印象）：
- 绝区零一条龙：`应用完成后发送通知` / `只在节点失败时立即通知` /
  `需确保使用时没有启用输入法` / `执行颜色过滤` / `图像加载`；
- 竞品 REA：`定时竞技场` / `商店提示` / `助手提示` / `定时任务`。
⇒ 陈述行为与条件，不与使用者对话；标签是名词短语，说明是短句。

规范全文见 `docs/UI_COPY_STYLE.md`。本文件只钉「能被机器判定的那几条」：

1. 面向用户的固定文案里，不许出现口语 / 第二人称 / 语气词；
2. 分组说明必须把该组里**每一条**路线列全（漏一条就是文案过期）；
3. 启动提示里**不许写死已放行的路线名单**（历史上正是这样过期的）；
4. 路线说明里不许出现单向的平台限制句（放行范围由 ``PC_READY_ROUTES`` 与
   ``STARTUP_HINTS`` 统一承担）；
5. 「这条路线在当前后端跑不了」由 ``catalog.unavailable_note()`` 按名单算，
   与 ``resolve_plan()`` 必须是同一份判据（否则界面与运行计划互相打脸）。

⚠️ 判断依据是**短语**而不是单字：中文没有词边界，「请求」里的「请」、「区别」里的
「别」、「挂机」里的「挂」都是业务词，不能算口语。别为了省事把词表退化成单字。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from auto_game_unified.core import countdown
from auto_game_unified.desktop import catalog, onboarding, run_progress
from auto_game_unified.games.epic7 import daily_tasks
from auto_game_unified.games.epic7.modes import MODE_SPECS


ROOT = Path(__file__).resolve().parents[1]

#: 口语 / 对话式标志。**按短语判**，避免误伤业务复合词（见文件头）。
COLLOQUIAL = (
    "你",
    "您",
    "点一下",
    "点两下",
    "点这里",
    "就行",
    "没必要",
    "顺手",
    "搞定",
    "卡住",
    "这时候",
    "这边",
    "那样",
    "吧",
    "啦",
    "呢",
    "啊",
    "嘛",
    "请",
)

#: 先剔除这些业务复合词，再判口语 —— 否则「请求 / 区别 / 挂机」会整片误报。
NEUTRALIZE = (
    "请求",
    "申请",
    "邀请",
    "聘请",
    "敬请",
    "区别",
    "类别",
    "分别",
    "特别",
    "别的",
    "个别",
    "告别",
    "挂机",
)


def _neutralized(text: str) -> str:
    for word in NEUTRALIZE:
        text = text.replace(word, "〇")
    return text


def _offending(text: str) -> list[str]:
    cleaned = _neutralized(text)
    return [word for word in COLLOQUIAL if word in cleaned]


def _assert_clean(where: str, text: str) -> None:
    hits = _offending(text)
    assert not hits, f"{where} 出现口语表述 {hits}：{text}"


def _route_note_strings() -> list[tuple[str, str]]:
    """各路线 ``route_note()`` 里的字符串字面量（结算里那句话的来源）。

    用 AST 而不是 import 实例：这些话是函数体里的常量，不需要真跑一遍路线。
    跳过 docstring（那是给维护者看的，允许写技术细节）。
    """

    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "games" / "epic7").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "route_note":
                continue
            docstring = ast.get_docstring(node, clean=False)
            for child in ast.walk(node):
                if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                    continue
                if docstring is not None and child.value == docstring:
                    continue
                if any("\u4e00" <= ch <= "\u9fff" for ch in child.value):
                    found.append((f"{path.name}::route_note", child.value))
    return found


def _countdown_strings() -> list[tuple[str, str]]:
    """``core/countdown.py`` 里面向用户的字符串（倒计时那一行）。"""

    path = ROOT / "core" / "countdown.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            docstring = ast.get_docstring(node, clean=False)
            if docstring is not None:
                docstrings.add(docstring)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            if any("\u4e00" <= ch <= "\u9fff" for ch in node.value):
                found.append(("core/countdown.py", node.value))
    return found


def _all_user_facing_texts() -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    texts += [(f"路线 {r.mode}", r.description) for r in catalog.ROUTES]
    texts += [(f"分组 {g}", catalog.group_description(g)) for g in catalog.GROUPS]
    texts += [(f"启动提示 {b}", hint) for b, hint in catalog.STARTUP_HINTS.items()]
    texts += [
        (f"后端说明 {b}", note) for b, note in catalog.BACKEND_UNAVAILABLE_NOTES.items()
    ]
    texts += [(f"后端名 {b}", label) for b, label in catalog.BACKEND_LABELS.items()]
    texts += [("使用须知·风险", t) for t in onboarding.RISK_POINTS]
    texts += [("使用须知·条件", t) for t in onboarding.SETUP_POINTS]
    texts += [(f"进度状态 {k}", v) for k, v in run_progress.STATUS_LABELS.items()]
    texts += [(f"结算状态 {k}", v) for k, v in daily_tasks.STATUS_WORDS.items()]
    texts += _countdown_strings()
    texts += _route_note_strings()
    return texts


# --------------------------------------------------------------------------
# ① 口语 / 对话式表述
# --------------------------------------------------------------------------


def test_no_colloquial_wording_in_user_facing_copy():
    """面向用户的固定文案不许出现口语、第二人称与语气词。"""

    texts = _all_user_facing_texts()
    assert len(texts) >= 40, f"待检文案只有 {len(texts)} 条，收集逻辑可能断了"

    problems = []
    for where, text in texts:
        hits = _offending(text)
        if hits:
            problems.append(f"{where}: {hits} -> {text[:60]}")
    assert not problems, "以下文案仍是口语：\n" + "\n".join(problems)


def test_result_line_status_words_are_the_explanation_style():
    """结算状态词必须是说明式短词，不能是「没得做了 / 本环境跑不了」这类口语。"""

    expected = {
        "completed": "完成",
        "resource": "无剩余内容",
        "failed": "失败",
        "skipped": "未执行",
        "not_supported": "当前环境不支持",
    }
    assert daily_tasks.STATUS_WORDS == expected


def test_progress_labels_use_the_same_status_words_as_the_result_card():
    """悬浮便签的状态词与结果卡不能各说一套。"""

    assert run_progress.STATUS_LABELS == {
        run_progress.PENDING: "待执行",
        run_progress.RUNNING: "进行中",
        run_progress.DONE: "已完成",
    }


#: 弹窗 / 报错里给人看的话所在的模块。
#:
#: 为什么只挑这些：路线与窗口层的**运行日志**按规范是不受约束的（`提示=…` 那些，
#: 排障时要写清「正在做什么、别按哪个键」），而这里列的是**会弹到用户眼前**的
#: 异常与提示 —— 权限不足、截图失败、计划被筛空、次元探查的前置条件。
NOTICE_MODULES = (
    "desktop/controller.py",
    "desktop/catalog.py",
    "desktop/chaos_bridge.py",
    "desktop/onboarding.py",
    "desktop/diagnostics.py",
    "core/elevation.py",
    "core/pc_window.py",
    "core/countdown.py",
    "core/autoclicker.py",
)


def _module_literals(relative: str) -> list[tuple[str, str]]:
    """模块里所有中文字符串常量（跳过 docstring —— 那是写给人维护者看的）。"""

    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                docstrings.add(text)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.value in docstrings:
            continue
        if any("\u4e00" <= ch <= "\u9fff" for ch in node.value):
            found.append((f"{relative}:{node.lineno}", node.value))
    return found


def test_notice_and_error_messages_stay_in_the_explanation_style():
    """弹窗与报错也用陈述句：写「需以管理员身份重新启动」，不写「请你右键它选…」。"""

    modules = list(NOTICE_MODULES)
    modules += [
        f"desktop_qt/{path.name}" for path in sorted((ROOT / "desktop_qt").glob("*.py"))
    ]

    problems = []
    for relative in modules:
        for where, text in _module_literals(relative):
            hits = _offending(text)
            if hits:
                problems.append(f"{where}: {hits} -> {text[:60]}")
    assert not problems, "以下提示仍是口语：\n" + "\n".join(problems)


def test_every_route_description_is_three_paragraphs_and_ends_with_a_note():
    """路线说明固定三段：动作 / 可调整项与「一轮」 / 「注意：」消耗与前提。

    第三段是读者最容易漏看的一段（花不花资源、会不会关掉别的东西），
    所以要求它以「注意：」开头 —— 少了它，说明就退回成「这段是干嘛的」。
    """

    for route in catalog.ROUTES:
        paragraphs = route.description.split("\n")
        assert len(paragraphs) == 3, (
            f"路线 {route.mode} 的说明有 {len(paragraphs)} 段，应为 3 段"
        )
        assert paragraphs[-1].startswith("注意："), (
            f"路线 {route.mode} 的第三段没有以「注意：」开头"
        )
        assert all(p.strip() for p in paragraphs), f"路线 {route.mode} 有空白段落"


# --------------------------------------------------------------------------
# ② 分组说明不许漏项（漏一条 = 文案过期）
# --------------------------------------------------------------------------


def test_every_group_description_lists_all_of_its_routes():
    """分组说明里点名的路线，必须正好覆盖该组实际的每一条。

    漏掉一条就是「说明与代码不一致」—— 历史上「每日」漏过成就领取、
    「按需」漏过主线补星，都是加了路线但没回来改说明。
    """

    for group, routes in catalog.grouped_routes():
        text = catalog.group_description(group)
        missing = [MODE_SPECS[r.mode].label for r in routes if MODE_SPECS[r.mode].label not in text]
        assert not missing, f"分组「{group}」的说明漏了：{'、'.join(missing)}"


# --------------------------------------------------------------------------
# ③ 启动提示不许写死放行名单
# --------------------------------------------------------------------------


def test_startup_hints_never_hardcode_the_released_route_list():
    """启动提示只说「按路线跳过」这条规则，不列具体哪些路线已放行。

    ⚠️ 写死名单是这里历史上反复过期的根因：PC 放行一条新路线后，
    没人会回来改这句提示。名单的唯一出处是 ``PC_READY_ROUTES``。
    """

    for backend, hint in catalog.STARTUP_HINTS.items():
        listed = [r.mode for r in catalog.ROUTES if MODE_SPECS[r.mode].label in hint]
        assert not listed, (
            f"启动提示[{backend}]里写死了路线名 {listed}；"
            "放行范围应由 PC_READY_ROUTES 与运行计划统一说明"
        )


# --------------------------------------------------------------------------
# ④ 路线说明不许写单向平台限制
# --------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", ["只支持模拟器", "仅支持模拟器", "请切回模拟器"])
def test_route_descriptions_do_not_hardcode_platform_limits(phrase):
    """「只支持模拟器」这类句子会随 PC 放行立刻过期，统一移到启动提示。"""

    for route in catalog.ROUTES:
        assert phrase not in route.description, (
            f"路线 {route.mode} 的说明里写死了平台限制「{phrase}」"
        )


# --------------------------------------------------------------------------
# ⑤ 「这条路线在当前后端跑不了」由名单算，不写在说明正文里
# --------------------------------------------------------------------------


def test_unavailable_note_agrees_with_the_plan_filter():
    """看板上的跳过说明必须与 ``resolve_plan()`` 用同一份名单。

    两边各写一套判据时，最坏的结果是「界面说能跑、跑起来却被跳过」——
    用户看到的说明与运行计划互相打脸，而且这种错不会让任何测试变红。
    """

    from auto_game_unified.games.epic7.modes import PC_ONLY_ROUTES

    PC_READY_ROUTES = catalog.PC_READY_ROUTES

    for route in catalog.ROUTES:
        on_pc = catalog.unavailable_note(route.mode, "pc")
        on_emu = catalog.unavailable_note(route.mode, "emulator")
        assert bool(on_pc) == (route.mode not in PC_READY_ROUTES), (
            f"{route.mode} 在 PC 上的说明与实际放行名单不一致"
        )
        assert bool(on_emu) == (route.mode in PC_ONLY_ROUTES), (
            f"{route.mode} 在模拟器上的说明与实际素材名单不一致"
        )
        assert not (on_pc and on_emu), f"{route.mode} 在两个后端都说跑不了"


def test_unavailable_note_never_names_a_route():
    """说明只陈述规则，不点名路线 —— 点名就会随名单变动过期。"""

    for backend, note in catalog.BACKEND_UNAVAILABLE_NOTES.items():
        for route in catalog.ROUTES:
            assert route.label not in note, (
                f"后端说明[{backend}]里写死了路线「{route.label}」"
            )


def test_unknown_backend_has_no_unavailable_note():
    """拼错的后端名要当场炸，不能返回空串让界面以为「能跑」。"""

    with pytest.raises(ValueError):
        catalog.unavailable_note("arena", "模拟器")


# --------------------------------------------------------------------------
# ⑥ 规范文档本身在索引里（防止规范写完没人找得到）
# --------------------------------------------------------------------------


def test_copy_style_doc_is_indexed():
    """规范写在 docs/UI_COPY_STYLE.md，必须在 docs/README.md 的索引里能点到。"""

    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "UI_COPY_STYLE.md" in index, "界面文案规范没有登记进 docs/README.md 的索引"
    assert (ROOT / "docs" / "UI_COPY_STYLE.md").is_file()
