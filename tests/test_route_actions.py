"""路线动作契约（``route_action.RouteAction``）的护栏。

守的是 2026-09-30 的收敛：9 个 ``XxxAction`` 原先各自声明字段，名字与顺序都能自由漂。
实测后果不是「看着乱」，而是**契约静默失效**：

- 世界首领战的 ``in_page_evidence`` 曾经**根本不存在**（规则写「A 或 B」，B 不存在）；
- 英雄合成把同页证据叫 ``source_observation``，机器认的是 ``in_page_evidence``；
- 竞技场按**位置**传 5 个参数，第 3 个是自己的 ``source_state`` —— 而契约里第 3 个位置是
  ``source_page``，字段一重排就会把状态枚举静默当成页面名，**不报错**。

最要紧的是最后一条：所以这里有一条 AST 用例，任何 ``*Action`` 调用超过 2 个位置参数就红。
"""

import ast
from dataclasses import fields
from pathlib import Path

from auto_game_unified.games.epic7 import (
    arena,
    expedition,
    fodder,
    hero_synthesis,
    knights_donation,
    labyrinth_stone,
    sanctuary,
    story,
    world_boss,
)
from auto_game_unified.games.epic7.route_action import RouteAction

PACKAGE = Path(__file__).resolve().parents[1]

#: 全部路线动作类型。新增路线时**必须**加进来 —— 漏了的话它就绕过了这里所有检查。
ACTION_TYPES = (
    arena.Action,
    expedition.ExpeditionAction,
    fodder.FodderAction,
    hero_synthesis.HeroAction,
    knights_donation.KnightsDonationAction,
    labyrinth_stone.LabyrinthStoneAction,
    sanctuary.SanctuaryAction,
    story.StoryAction,
    world_boss.WorldBossAction,
)

#: 带默认值的公共字段 -> 文档里承诺的默认值。
DEFAULTED_FIELDS = {
    "source_page": "",
    "target_pages": (),
    "in_page_evidence": "",
    "reason": "",
}


def test_every_route_action_inherits_the_shared_contract():
    for action_type in ACTION_TYPES:
        assert issubclass(action_type, RouteAction), action_type.__name__


def test_every_route_action_carries_the_contract_field_names():
    for action_type in ACTION_TYPES:
        names = {field.name for field in fields(action_type)}
        assert {"name", "point"} <= names, action_type.__name__
        assert set(DEFAULTED_FIELDS) <= names, action_type.__name__


def test_the_documented_defaults_hold():
    for action_type in ACTION_TYPES:
        action = action_type("x", (1, 2))
        for field_name, expected in DEFAULTED_FIELDS.items():
            assert getattr(action, field_name) == expected, (
                action_type.__name__,
                field_name,
            )


def test_every_route_action_accepts_the_contract_by_keyword():
    for action_type in ACTION_TYPES:
        action = action_type(
            "x",
            (1, 2),
            source_page="来源",
            target_pages=("目标",),
            in_page_evidence="页内证据",
            reason="理由",
        )
        assert action.source_page == "来源"
        assert action.target_pages == ("目标",)
        assert action.in_page_evidence == "页内证据"
        assert action.reason == "理由"


def test_no_action_call_passes_more_than_two_positional_arguments():
    """位置参数只允许 ``name`` 与 ``point``。

    多传的位置参数在字段重排后会**静默绑到别的字段上**（2026-09-30 实测：竞技场的
    ``source_state`` 会落到 ``source_page``，一个枚举被当成页面名，全程不报错）。
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or "runtime_logs" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None) or ""
            if name.endswith("Action") and len(node.args) > 2:
                offenders.append(
                    f"{path.name}:{node.lineno} {name}(...) 位置参数={len(node.args)}"
                )
    assert offenders == [], "\n".join(offenders)


def test_arena_keeps_the_field_names_the_transactional_runner_reads():
    """``TransactionalRunnerBase`` 按名字读这三个字段，改名就等于静默改契约。"""
    names = {field.name for field in fields(arena.Action)}
    assert {"source_state", "target_states", "irreversible"} <= names


def test_hero_synthesis_still_declares_the_known_drift_explicitly():
    """英雄合成的同页证据仍叫 ``source_observation`` —— 这是**登记在册**的例外。

    本用例不是「容忍它」，而是把它钉在明处：哪天字段名对齐了（或又冒出第三种叫法），
    这里必须跟着改，不能悄悄漂。理由见 ``modes.TRANSITION_EXEMPT`` 里 hero_synthesis 那条。
    """
    names = {field.name for field in fields(hero_synthesis.HeroAction)}
    assert "source_observation" in names
    assert names - set(DEFAULTED_FIELDS) - {"name", "point"} == {
        "source_observation",
        "transition_kind",
    }
