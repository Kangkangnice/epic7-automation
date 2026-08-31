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


def test_invalid_values_are_reprompted_in_chinese():
    inputs = iter(["x", "1", "7", "2", "0", "abc", "3"])
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
    assert output.count("请输入 1 到 6 之间的功能编号。") == 1
    assert output.count("运行次数必须是正整数。") == 2
