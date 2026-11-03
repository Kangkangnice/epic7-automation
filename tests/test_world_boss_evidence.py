"""世界首领战证据档案的回归测试。

守两件事：
1. **六个锚点在本路线 9 张夹具上真的分得开**（不是「像」就行，是互斥）。
2. **两个串页坑不会复发**：``worldboss_title`` 不能判主页、``result_title`` 不能单独判结算页。
   这两条是 2026-09-21 实机走查时踩出来的，写死在这里。
"""

from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.evidence.common import (
    EvidenceState,
    validate_profile,
)
from auto_game_unified.games.epic7.evidence.world_boss import (
    DEFAULT_THRESHOLD,
    REFERENCE_SIZE,
    REGIONS,
    build_world_boss_evidence,
)
from auto_game_unified.games.epic7.world_boss import (
    WorldBossState,
    WorldBossStateMachine,
)


ROOT = Path(__file__).resolve().parents[1]
# 档案的 template_root 是「本路线子目录」，与 expedition / fodder 一致。
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "world_boss"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_world_boss"


def _screen(name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"读不到夹具 {name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def test_profile_declares_existing_current_client_templates():
    profile = build_world_boss_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("knights_title").reference_size == REFERENCE_SIZE
    assert profile.atom("result_title").threshold == DEFAULT_THRESHOLD


def test_knights_home_and_world_boss_home_are_distinguishable():
    """骑士团主页与世界首领战主页标题栏同处左上角，不能混判。"""

    profile = build_world_boss_evidence(TEMPLATES)

    knights = profile.evaluate_pages(
        _observations(profile, _screen("knights_home"))
    )
    worldboss = profile.evaluate_pages(
        _observations(profile, _screen("worldboss_home"))
    )

    assert knights["world_boss.knights_home"] is EvidenceState.SAFE
    assert knights["world_boss.home"] is EvidenceState.UNKNOWN
    assert worldboss["world_boss.knights_home"] is EvidenceState.UNKNOWN
    assert worldboss["world_boss.home"] is EvidenceState.SAFE


def test_worldboss_title_is_persistent_so_it_cannot_identify_the_home_page():
    """「世界首领战」标题栏在队伍页/体力弹窗上常驻（0.99+），故主页必须用别的锚点。

    这一条是防回归的核心：如果谁把 ``world_boss.home`` 的判据改回 ``worldboss_title``，
    队伍页就会被当成主页，状态机会在上面反复点「选择队伍」，白等到超时。
    """

    profile = build_world_boss_evidence(TEMPLATES)
    home = profile.page("world_boss.home")

    assert home.required == ("select_team_button",)
    assert "worldboss_title" not in home.required

    for name in ("team_select", "team_config", "stamina_popup"):
        observations = _observations(profile, _screen(name))
        # 标题栏确实还在（说明这个锚点本身没问题，只是不能独占）
        assert observations["worldboss_title"].observed, (
            f"{name}: 预期 worldboss_title 仍然命中（它是常驻标题栏）"
        )
        states = profile.evaluate_pages(observations)
        assert states["world_boss.home"] is EvidenceState.UNKNOWN, (
            f"{name}: 被误判成世界首领战主页，会把队伍页当主页点「选择队伍」"
        )


def test_level_reward_popup_dims_the_result_page_so_result_needs_exclusion():
    """奖励弹窗是压暗的结算页，「战斗结果」还在（0.7103），必须靠奖励标题排他。"""

    profile = build_world_boss_evidence(TEMPLATES)
    result = profile.page("world_boss.result")

    assert result.required == ("result_title",)
    assert "level_reward_title" in result.forbidden

    reward = profile.evaluate_pages(_observations(profile, _screen("level_reward")))
    assert reward["world_boss.result"] is EvidenceState.UNSAFE
    assert reward["world_boss.level_reward"] is EvidenceState.SAFE


def test_every_route_fixture_maps_to_its_own_page_or_is_intentionally_unmapped():
    """九张夹具逐张过一遍，每张要么判到预期页面，要么是明确「本就不判页」的那种。"""

    profile = build_world_boss_evidence(TEMPLATES)
    expected = {
        "knights_home": "world_boss.knights_home",
        "worldboss_home": "world_boss.home",
        # 次数耗尽页与可打页是同一页，只有按钮亮度不同（模板匹配对亮度不敏感）。
        "worldboss_home_exhausted": "world_boss.home",
        "team_select": "world_boss.team_select",
        "team_config": "world_boss.team_config",
        "battle_result": "world_boss.result",
        "level_reward": "world_boss.level_reward",
    }

    for fixture, page_key in expected.items():
        states = profile.evaluate_pages(_observations(profile, _screen(fixture)))
        safe = {key for key, state in states.items() if state is EvidenceState.SAFE}
        assert safe == {page_key}, (
            f"{fixture}: 预期只判 {page_key}，实际 {sorted(safe)}"
        )

    # 大厅（骑士团入口所在页）与体力弹窗都不该被判成任何世界首领战页面：
    # 前者还没进来；后者是全局弹窗，由 stamina.py 负责，判成配置队伍页的话
    # 状态机会在弹窗上点「战斗开始」（= 弹窗背后那颗按钮）。
    for fixture in (
        "lobby_with_knights",
        "stamina_popup",
    ):
        states = profile.evaluate_pages(_observations(profile, _screen(fixture)))
        safe = {key for key, state in states.items() if state is EvidenceState.SAFE}
        assert not safe, f"{fixture}: 不该有任何世界首领战页面成立，实际 {sorted(safe)}"


def test_stamina_popup_is_excluded_from_team_config():
    """体力弹窗盖在配置队伍页上时，本页锚点仍有 0.9995，必须靠 forbidden 排除。"""

    profile = build_world_boss_evidence(TEMPLATES)
    page = profile.page("world_boss.team_config")

    assert page.required == ("team_config_auto",)
    assert page.forbidden == ("stamina_popup",)

    observations = _observations(profile, _screen("stamina_popup"))
    assert observations["team_config_auto"].observed, (
        "预期 team_config_auto 在弹窗帧上仍命中（弹窗是压暗覆盖，不是换页）"
    )
    states = profile.evaluate_pages(observations)
    assert states["world_boss.team_config"] is EvidenceState.UNSAFE


def test_regions_and_thresholds_align_with_measured_scores():
    """阈值必须落在「本路线分」与「跨路线最高分」之间，别拍脑袋。"""

    # 2026-09-21 全库 185 张 1982×1132 夹具扫描的跨路线最高分。
    # ``team_config_auto`` 是新加的锚点（原先靠常驻标题栏猜配置队伍页，会不自愈），
    # ``stamina_popup`` 复用 story 的模板、不做跨路线排他扫描（它本来就是全局弹窗）。
    cross_route_best = {
        "knights_title": 0.6337,
        "worldboss_title": 0.6223,
        "select_team_button": 0.5861,
        "team_select_title": 0.3693,
        "level_reward_title": 0.4432,
        "result_title": 0.3612,
    }

    assert set(cross_route_best) <= set(REGIONS)
    for key, best in cross_route_best.items():
        assert DEFAULT_THRESHOLD > best, (
            f"{key}: 阈值 {DEFAULT_THRESHOLD} 不高于跨路线最高分 {best}，会串页"
        )


def _observations(profile, screen: np.ndarray):
    """按档案对一帧做全锚点定位，返回 ``AtomObservation`` 映射。

    这里刻意不复用 runner 里的定位实现：测试要独立于被测对象，
    自己调一次 ``find_best_template`` 才能真的验到「阈值 + 区域」。
    """

    from auto_game_unified.core.matcher import find_best_template, load_template

    observations = {}
    for key, atom in profile.atoms.items():
        template = load_template(str(profile.template_root / atom.template_path))
        match = find_best_template(
            screen,
            template,
            region=atom.region,
            reference_size=atom.reference_size,
        )
        score = None if match is None else match.score
        observations[key] = _atom_observation(
            atom, match, score
        )
    return observations


def _atom_observation(atom, match, score):
    from auto_game_unified.games.epic7.evidence.common import AtomObservation

    return AtomObservation(
        key=atom.key,
        template=atom.template_path,
        config=atom.key,
        region=atom.region,
        reference_size=atom.reference_size,
        threshold=atom.threshold,
        observed=score is not None and score >= atom.threshold,
        score=score,
        center=None if match is None else match.center,
    )


# ---------------------------------------------------------------------------
# PC 客户端（2026-11-03 移植）
# ---------------------------------------------------------------------------
#
# PC 移植实测定案：**PC 压低的是「文字」类锚点，图形类不受影响**。同一条路线上
# 的对照足够硬 —— ``navigation/worldboss_entry``（骷髅盾牌图形）在 PC 帧上
# 0.9936~0.9940，分文不动；文字锚点则整片塌到 0.66~0.79，一律过不了 0.80：
#
# | 锚点 | 模拟器夹具 | PC 原样 | PC + ``pc/`` 覆盖图 |
# |---|---|---|---|
# | ``knights_title`` | 1.0000 | 0.7858 | **1.0000** |
# | ``select_team_button`` | 1.0000 | 0.6648 | **1.0000** |
# | ``team_select_title`` | 1.0000 | 未见（整页 unknown） | **1.0000** |
# | ``team_config_auto`` | 1.0000 | 未见（整页 unknown） | **1.0000** |
# | ``battle_skip`` | 1.0000 | 0.6997 | **0.88~1.00** |
# | ``result_title`` | 1.0000 | 未见（整页 unknown） | **1.0000** |
#
# 所以修法**只补图、不动口径**。低通 σ=2.0 也能把分数抬到 0.86 左右，但全库审计
# 显示它把跨页分一并抬高约 0.2（``result_title`` 在奖励弹窗上 0.7103→0.9305），
# 等于拿判据余量换分数 —— 那是「看起来修好了、下次换个页面就串页」的做法。

PC_FIXTURES = {
    "worldboss_home_pc_live_20261103": WorldBossState.HOME,
    "team_select_pc_live_20261103": WorldBossState.TEAM_SELECT,
    "team_config_pc_live_20261103": WorldBossState.TEAM_CONFIG,
    "battle_result_pc_live_20261103": WorldBossState.RESULT,
}


def _pc_machine(backend: str):
    from auto_game_unified.games.epic7.template_paths import resolve_template_dir


    root = resolve_template_dir(TEMPLATES.parent, backend)
    return WorldBossStateMachine(root / "world_boss", initial_state=WorldBossState.HOME)


def test_pc_overrides_make_the_whole_route_recognizable():
    """PC 专属图就位后，PC 实跑的每一页都要判回它自己那一页。

    这四张是 2026-11-03 实跑现场帧（不是按矩形裁的），分别对应挡路的那一颗锚点：
    ``select_team_button`` / ``team_select_title`` / ``team_config_auto`` /
    ``result_title``。路线当时就是在这四处逐一卡死的。
    """

    machine = _pc_machine("pc")

    for name, expected in PC_FIXTURES.items():
        with_subtest = f"{name}: 期望判成 {expected}"
        assert machine.observe_page(_screen(name)) is expected, with_subtest


def test_pc_knights_home_is_recognized_as_the_navigation_midpoint():
    """骑士团主页不进 ``observe_page``（那页没有本路线的决策），只由 ``at_knights_home`` 判。

    它必须能认出来：接力与「已在骑士团主页」的短路都挂在这条上，认不出就会把
    已经站在门口的进度当成「还在大厅」重新导航一遍。
    """

    machine = _pc_machine("pc")

    assert machine.at_knights_home(_screen("knights_home_pc_live_20261103"))


def test_pc_battle_page_is_recognized_and_the_story_page_is_not():
    """战斗页靠右上角「跳过」认，而**剧情播放页也有同一张图**（位置不同）。

    ``BATTLE_SKIP_REGION`` 收到 x<1760 就是为了把剧情页排除在外。PC 的覆盖图必须
    保持这条分野：战斗帧过阈、剧情帧远低于阈。反例帧 ``battle_pc_live_20261103``
    同一目录下没有剧情帧，所以这里同时验「战斗帧=True / 非战斗帧=False」。
    """

    machine = _pc_machine("pc")

    assert machine.battle_visible(_screen("battle_pc_live_20261103"))
    for name in PC_FIXTURES:
        assert not machine.battle_visible(_screen(name)), (
            f"{name}: 不是战斗画面却判成战斗中，会把结算页当成战斗页反复点「跳过」"
        )


def test_shared_templates_cannot_recognize_the_pc_frames():
    """反向锁定：**共享图（模拟器那一套）认不出 PC 帧**，这正是要补 PC 图的原因。

    没有这一条，将来谁把 ``pc/`` 里的图删了，上面的用例会红、但没人知道为什么；
    有了它，「删掉 PC 图 ⇒ 退回共享图 ⇒ 整条路线在 PC 上进不去」这条因果就是自证的。
    """

    machine = _pc_machine("emulator")

    for name in PC_FIXTURES:
        assert machine.observe_page(_screen(name)) is None, (
            f"{name}: 共享图居然认出了 PC 帧 —— 说明这张 PC 图是多余的，"
            "或者共享图被换成了 PC 图"
        )
    assert not machine.at_knights_home(_screen("knights_home_pc_live_20261103"))
    assert not machine.battle_visible(_screen("battle_pc_live_20261103"))
