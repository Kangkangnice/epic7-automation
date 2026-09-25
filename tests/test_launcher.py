import pytest

from auto_game_unified import launcher


@pytest.mark.parametrize(
    ("choice", "mode", "label"),
    [
        ("1", "story", "主线"),
        ("2", "arena", "竞技场"),
        ("3", "expedition", "远征"),
        ("4", "fodder", "狗粮"),
        ("6", "shop_refresh", "刷书签"),
    ],
)
def test_selects_mode_then_cycles_and_calls_existing_live_entry(
    choice, mode, label
):
    inputs = iter(["1", choice, "3"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 2,
    )

    assert exit_code == 2
    assert calls == [
        [
            "--mode",
            mode,
            "--window-backend",
            "emulator",
            "--max-cycles",
            "3",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "1. 主线" in output
    assert "2. 竞技场" in output
    assert "3. 远征" in output
    assert "4. 狗粮（特别的时间之书 3-7）" in output
    assert "5. 英雄合成（三星刻印合成，跑完一遍列表自动结束）" in output
    assert "6. 刷书签（实验功能，只支持模拟器）" in output
    assert "7. 世界首领战（骑士团每日任务，每场 20 体力，不够自动用树叶买）" in output
    assert f"即将运行：{label}（平台=模拟器（LDPlayer）），共 3 次" in output


def test_selects_pc_backend_and_passes_it_to_the_live_entry():
    inputs = iter(["2", "1", "1"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--mode",
            "story",
            "--window-backend",
            "pc",
            "--max-cycles",
            "1",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "即将运行：主线（平台=PC 客户端），共 1 次" in output


def test_hero_synthesis_skips_count_prompt_and_runs_once():
    inputs = iter(["1", "5"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--mode",
            "hero_synthesis",
            "--window-backend",
            "emulator",
            "--max-cycles",
            "1",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "请输入运行次数：" not in output
    assert "即将运行：英雄合成（平台=模拟器（LDPlayer）），共 1 次" in output


def test_world_boss_skips_count_prompt_and_runs_twice():
    """每天固定 2 次，用户明确要求「不要让我选择次数」——菜单里不给次数提示。"""
    inputs = iter(["1", "7"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--mode",
            "world_boss",
            "--window-backend",
            "emulator",
            "--max-cycles",
            "2",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "请输入运行次数：" not in output
    assert "7. 世界首领战（骑士团每日任务，每场 20 体力，不够自动用树叶买）" in output
    assert "即将运行：世界首领战（平台=模拟器（LDPlayer）），共 2 次" in output


def test_invalid_values_are_reprompted_in_chinese():
    # "7" 在 2026-09-21 之前是非法编号，加了世界首领战之后变成合法了；
    # 之后菜单又陆续加了新项。这里用一个**大于当前菜单长度**的编号（"11"）
    # 来守住「编号超出范围会被重新询问」这条行为，不依赖具体加到了第几项。
    inputs = iter(["x", "1", "11", "2", "0", "abc", "3"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--mode",
            "arena",
            "--window-backend",
            "emulator",
            "--max-cycles",
            "3",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert output.count("请输入 1 或 2 选择运行平台。") == 1
    assert output.count("请输入 1 到 10 之间的功能编号。") == 1
    assert output.count("运行次数必须是正整数。") == 2


def test_knights_donation_skips_count_prompt_and_runs_once():
    """每天跑一遍就够，用户明确要求「不要让我选择次数」——菜单里不给次数提示。"""
    inputs = iter(["1", "8"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--mode",
            "knights_donation",
            "--window-backend",
            "emulator",
            "--max-cycles",
            "1",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "请输入运行次数：" not in output
    assert "8. 骑士团捐赠（骑士团每日捐赠，请求支援 + 支援团员 + 每周任务，跑一遍结束）" in output
    assert "即将运行：骑士团捐赠（平台=模拟器（LDPlayer）），共 1 次" in output


def test_daily_tasks_menu_entry_runs_without_asking_cycles():
    """菜单第 10 项是「每日任务」：走 --daily、不问次数（各条有自己的每日次数）。"""
    inputs = iter(["1", "10"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--daily",
            "--window-backend",
            "emulator",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "请输入运行次数：" not in output
    assert "10. 每日任务" in "\n".join(output)
    assert "即将运行：每日任务（平台=模拟器（LDPlayer））" in output
