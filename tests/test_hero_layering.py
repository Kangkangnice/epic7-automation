"""英雄合成拆层后的结构护栏（``hero_vision`` 与 ``hero_synthesis`` 的关系）。

2026-09-30 把「只看画面、不做决策」的那 50 个方法抽成 ``hero_vision.HeroVisionMixin``
（``hero_synthesis.py`` 2317 -> 1508 行）。这里钉住四件事：

1. **分层方向**：``hero_vision`` 不许反过来 import ``hero_synthesis`` —— 那就是循环；
2. 状态机真的混入了 mixin（不是搬完之后忘了继承）；
3. **对外再导出的名字还在**（``navigation.py`` 按 ``hero_synthesis.xxx`` 取那几个视觉函数，
   再导出断了它会在 import 时就炸）；
4. 那 6 个视觉常量在 ``hero_synthesis`` 里是**别名**、不是复制值（同一控件只留一个来源）。
"""

import ast
from pathlib import Path

from auto_game_unified.games.epic7 import hero_synthesis, hero_vision
from auto_game_unified.games.epic7.hero_synthesis import HeroSynthStateMachine

PACKAGE = Path(__file__).resolve().parents[1]
VISION_SOURCE = (PACKAGE / "games" / "epic7" / "hero_vision.py").read_text(encoding="utf-8")
SYNTH_SOURCE = (PACKAGE / "games" / "epic7" / "hero_synthesis.py").read_text(
    encoding="utf-8"
)

#: ``hero_synthesis`` 里必须继续能取到的名字（navigation.py 与既有测试在用）。
REEXPORTS = (
    "FilterObservation",
    "imprint_button_saturation",
    "hero_tab_blue_pixel_counts",
    "hero_information_tab_selected",
    "hero_equipment_tab_selected",
)

#: ``hero_synthesis`` 里的私有别名 -> ``hero_vision`` 里的唯一定义。
CONSTANT_ALIASES = (
    ("_REFERENCE_SIZE", "REFERENCE_SIZE"),
    ("_BUTTON_CENTER", "BUTTON_CENTER"),
    ("_BUTTON_DISC_RADIUS", "BUTTON_DISC_RADIUS"),
    ("_HERO_INFO_TAB_ZONE", "HERO_INFO_TAB_ZONE"),
    ("_EQUIPMENT_TAB_ZONE", "EQUIPMENT_TAB_ZONE"),
    ("_SELECTED_TAB_BLUE_MIN", "SELECTED_TAB_BLUE_MIN"),
)


def _imported_modules(source: str) -> set[str]:
    """源码里所有 import 的模块全名。"""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_the_vision_layer_never_imports_back_upwards():
    """分层方向：``hero_vision`` 不许 import ``hero_synthesis``（否则就是循环）。

    ⚠️ 判据必须走 AST：**合法的** ``evidence.hero_synthesis`` 导入里也含
    ``hero_synthesis`` 这个子串，按文本查会把自己人当违规 —— 第一版就是这么挂的。
    """
    forbidden = "auto_game_unified.games.epic7.hero_synthesis"
    assert forbidden not in _imported_modules(VISION_SOURCE)


def test_the_state_machine_actually_mixes_the_vision_layer_in():
    assert issubclass(HeroSynthStateMachine, hero_vision.HeroVisionMixin)
    assert hero_vision.HeroVisionMixin in HeroSynthStateMachine.__mro__


def test_the_public_reexports_still_resolve():
    for name in REEXPORTS:
        assert getattr(hero_synthesis, name) is getattr(hero_vision, name), name


def test_the_vision_constants_are_aliases_not_copies():
    """``hero_synthesis`` 里必须写 ``_X = X``：值只能有一处，别在两处各写一遍。"""
    for private, public in CONSTANT_ALIASES:
        assert f"{private} = {public}" in SYNTH_SOURCE, private
        assert getattr(HeroSynthStateMachine, private) == getattr(hero_vision, public)


def test_the_vision_mixin_carries_no_decision_methods():
    """按钮的边界：mixin 里只放「读画面」的方法。

    这里只钉一个最有代表性的反例：``next_action`` / ``preview`` 是决策入口，
    它们必须在 ``hero_synthesis`` 里，不能跟着视觉方法一起搬走。
    """
    assert not hasattr(hero_vision.HeroVisionMixin, "next_action")
    assert not hasattr(hero_vision.HeroVisionMixin, "preview")
    assert hasattr(HeroSynthStateMachine, "next_action")
