"""模板路径解析：PC 与模拟器的**唯一**差异点必须只有图片。

背景（2026-09-28 这次重构）：以前平台差异散在业务代码里 —— 7 个证据模块各有一张
``PC_THRESHOLD_OVERRIDES``，竞技场 / 导航 / 英雄合成还有就地写死的
``0.85 if backend == "pc" else 0.90``。结果是「改 PC」= 到处找这些分叉，
改一处漏一处不会报错。现在全部收敛到 ``template_paths.TemplateDir``：
平台只决定**去哪个目录取图**，别的什么都不决定。

这组用例守三件事：
1. 覆盖 / 回落规则本身（``pc/`` 里有图就用它，没有就用共享图）；
2. ``.name`` / ``.parent`` 必须还原到共享目录 —— 业务代码靠 ``.name`` 认路线，
   靠 ``.parent`` 跨路线取图，退化成纯 ``Path`` 或变成 ``"pc"`` 都会出真错；
3. 业务代码里不许再长出门槛分叉（``PC_THRESHOLD_OVERRIDES`` / ``thresholds_for``）。
"""

from pathlib import Path

from auto_game_unified.games.epic7.template_paths import (
    PC_SUBDIR,
    TemplateDir,
    resolve_template,
    resolve_template_dir,
)


GAMES = Path(__file__).resolve().parents[1] / "games"
REAL_ROOT = GAMES / "epic7" / "templates"


def _story_layout(root: Path) -> Path:
    """``<root>/story/{skip.png, pc/skip.png, select_team.png}`` 的最小布局。"""
    story = root / "story"
    (story / PC_SUBDIR).mkdir(parents=True)
    (story / "skip.png").write_bytes(b"shared")
    (story / PC_SUBDIR / "skip.png").write_bytes(b"pc")
    (story / "select_team.png").write_bytes(b"shared")
    return story


def test_emulator_never_reads_the_pc_subdir(tmp_path):
    story = _story_layout(tmp_path)
    directory = resolve_template_dir(story)

    assert (directory / "skip.png").read_bytes() == b"shared"
    assert (directory / "select_team.png").read_bytes() == b"shared"
    assert directory.backend == "emulator"


def test_pc_prefers_the_override_and_falls_back_per_file(tmp_path):
    story = _story_layout(tmp_path)
    directory = resolve_template_dir(story, "pc")

    # 有 PC 图 ⇒ 用 PC 图。
    assert (directory / "skip.png") == story / PC_SUBDIR / "skip.png"
    assert (directory / "skip.png").read_bytes() == b"pc"
    # 没 PC 图 ⇒ 自动回落共享图（不是「找不到就报错」）。
    assert (directory / "select_team.png") == story / "select_team.png"
    assert (directory / "select_team.png").read_bytes() == b"shared"


def test_name_and_parent_stay_on_the_shared_directory(tmp_path):
    """``.name`` / ``.parent`` 必须还原到共享目录，不许变成 ``"pc"``。

    ⚠️ 这两条都是**真踩过的坑**：
    - ``pre_battle.py`` 靠 ``template_dir.name in {"story", "fodder", ...}``
      认路线，``.name`` 一旦变成 ``"pc"``，战前页会认错路线；
    - 远征 / 世界首领战会 ``template_dir.parent`` 之后跨到 ``story`` 取图，
      ``.parent`` 退回纯 ``Path`` 就把覆盖能力断在这一跳上。
    """
    (tmp_path / "arena").mkdir()
    story = _story_layout(tmp_path)
    directory = resolve_template_dir(story, "pc")
    overridden = directory / "skip.png"

    assert directory.name == "story"
    assert str(directory) == str(story)
    # 覆盖只发生在「取图」这一步：解析出的文件路径确实在 pc/ 下 …
    assert str(overridden.parent) == str(story / PC_SUBDIR)
    # … 但目录对象自己仍然代表共享目录。
    assert str(directory.parent) == str(tmp_path)

    sibling = directory.parent / "arena"
    assert isinstance(sibling, TemplateDir)
    assert sibling.backend == "pc"
    assert sibling.name == "arena"


def test_subdirectories_keep_the_override_alive(tmp_path):
    """``root / "hero"`` 之后再拼文件名，覆盖能力不能断（英雄合成走这条路）。"""
    (tmp_path / "hero" / PC_SUBDIR).mkdir(parents=True)
    (tmp_path / "hero" / "filter_button.png").write_bytes(b"shared")
    (tmp_path / "hero" / PC_SUBDIR / "filter_button.png").write_bytes(b"pc")

    hero = resolve_template_dir(tmp_path, "pc") / "hero"

    assert isinstance(hero, TemplateDir)
    assert hero.name == "hero"
    assert (hero / "filter_button.png").read_bytes() == b"pc"

    # 子目录里没放的图照样回落。
    (tmp_path / "hero" / "rating_sss.png").write_bytes(b"shared")
    assert (hero / "rating_sss.png").read_bytes() == b"shared"


def test_resolve_template_agrees_with_the_directory_rule(tmp_path):
    story = _story_layout(tmp_path)

    assert resolve_template(story, "skip.png", "pc") == (
        story / PC_SUBDIR / "skip.png"
    )
    assert resolve_template(story, "select_team.png", "pc") == (
        story / "select_team.png"
    )
    assert resolve_template(story, "skip.png", "emulator") == story / "skip.png"


def test_real_template_root_currently_has_no_pc_override():
    """今天仓库里**一张 PC 专属图都没有** —— 所以两个后端解析出的路径完全相同。

    这条是「删掉 PC 门槛分叉不改变模拟器行为」的旁证：既然没有覆盖图，
    PC 与模拟器拿到的就是同一张图，删掉分叉前 PC 只是**额外放低了门槛**。
    哪天往 ``templates/**/pc/`` 放了图，这条会红 ⇒ 改成断言「只覆盖指定锚点」。
    """
    assert not any(REAL_ROOT.rglob(PC_SUBDIR)), "出现了 PC 专属图，本条用例该改了"

    shared = resolve_template_dir(REAL_ROOT)
    pc = resolve_template_dir(REAL_ROOT, "pc")

    assert shared / "story" / "skip.png" == pc / "story" / "skip.png"
    assert shared / "arena" / "battle_start.png" == pc / "arena" / "battle_start.png"


def test_no_platform_threshold_table_is_left_in_the_business_code():
    """平台门槛表不许复活。

    以前 7 个证据模块各有一张 ``PC_THRESHOLD_OVERRIDES`` 加一个 ``thresholds_for()``，
    另有就地写死的 ``if backend == "pc"``。它们让「改 PC」变成满仓库找分叉，
    而且实测（``runtime_logs/pc_template_scores.md``）那些放宽几乎救不回任何锚点 ——
    只是把「认不出」推迟成「认错」。这里扫源码把它们钉死在门外。

    ⚠️ 只扫**真代码**：``evidence/arena.py`` 等处的 docstring 里会点名
    ``PC_THRESHOLD_OVERRIDES`` 解释「为什么删掉它」，那是说明不是复活。
    所以先把注释和字符串 token 剔掉再扫（同 ``route_metadata`` 用 AST 而不是
    文本匹配的道理一样：文本匹配会把文档里的话当成真代码）。
    """
    banned = (
        "PC_THRESHOLD_OVERRIDES",
        "PC_DEFAULT_THRESHOLD",
        "thresholds_for",
        'backend == "pc"',
        "supported_backends",
        "validate_backend",
    )
    offenders = []
    for path in sorted(GAMES.rglob("*.py")):
        if path.name == "template_paths.py":
            # 唯一「认识 pc 这个概念」的模块，它的文档里会点名这些历史名字。
            continue
        code = _code_only(path.read_text(encoding="utf-8"))
        for token in banned:
            if token in code:
                offenders.append(f"{path.relative_to(GAMES.parent)}: {token}")

    assert [] == offenders


def _code_only(source: str) -> str:
    """去掉注释与所有字符串字面量，只留真正的代码文本。"""
    import io
    import tokenize

    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return "\n".join(kept)
