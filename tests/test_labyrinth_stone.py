"""迷宫强化石（``labyrinth_stone``）的判据测试。

三条硬要求（都是本项目踩过的坑）：

1. **拿真夹具跑**：判据写反 / 阈值抄错 / 名字拼错，全都表现为「永远认不出」，
   单看代码看不出来。本文件每张断言都建立在 ``tests/fixtures/epic7_labyrinth_stone``
   里那 20 张实拍帧上。
2. **必须有真 Runner 级的用例**：两次事故都发生在**状态机与主循环之间**
   （判据写对了却没接上）。只测 ``next_action`` 是测不出来的 —— 必须让真
   ``ModeRunnerBase.run()`` 把整条链走一遍。
3. **每个动作都要有转场契约**：``_REQUIRE_TRANSITION_CONTRACT`` 只保证「缺声明会抛错」，
   不保证「声明的是对的」；这里逐个动作点名核对。

⚠️ 画面一律转 RGB：``load_template`` 会把模板转成 RGB，用 BGR 读夹具会让蓝色控件的
分数凭空掉一大截（蓝菱形实测 1.0000 → 0.2528）。
"""

import dataclasses
from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_game_unified.games.epic7 import labyrinth_stone
from auto_game_unified.games.epic7.template_paths import resolve_template_dir
from auto_game_unified.games.epic7.labyrinth_stone import (
    LabyrinthStoneRunner,
    LabyrinthStoneState,
    detect_resume_point,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_labyrinth_stone"
REFERENCE_SIZE = (1982, 1132)


def frame(name: str) -> np.ndarray:
    raw = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert raw is not None, f"缺夹具 {name}.png"
    return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)


def build_machine(**flags):
    from auto_game_unified.games.epic7.modes import get_mode

    spec = get_mode("labyrinth_stone")
    machine = spec.build_machine(TEMPLATE_ROOT, spec.default_state)
    for key, value in flags.items():
        setattr(machine, key, value)
    return machine


# ---- ① 每张夹具认得出它该认的那一页 -------------------------------------------

PAGE_CASES = [
    ("battle_menu", LabyrinthStoneState.BATTLE_MENU),
    ("labyrinth_list", LabyrinthStoneState.LABYRINTH_LIST),
    ("labyrinth_detail", LabyrinthStoneState.LABYRINTH_DETAIL),
    ("detail_after_giveup", LabyrinthStoneState.LABYRINTH_DETAIL),
    ("team_ready", LabyrinthStoneState.TEAM),
    ("story", LabyrinthStoneState.STORY),
    ("room", LabyrinthStoneState.ROOM),
    ("room_entering", LabyrinthStoneState.ROOM),
    ("room_west", LabyrinthStoneState.ROOM),
    # ⚠️ 这一张是整套判据里最容易翻车的一组：迷宫房间与真战斗**左上角都挂着士气笑脸**，
    # 唯一的差别是底部那条回合条。顺序排反了这里就会红。
    ("battle", LabyrinthStoneState.BATTLE),
    ("map", LabyrinthStoneState.MAP),
    ("map_pinned", LabyrinthStoneState.MAP),
    ("teleport_confirm", LabyrinthStoneState.TELEPORT_CONFIRM),
    ("unknown_dialog", LabyrinthStoneState.UNKNOWN_DIALOG),
    ("merchant_room", LabyrinthStoneState.MERCHANT_ROOM),
    ("shop", LabyrinthStoneState.SHOP),
    ("shop_mostly_bought", LabyrinthStoneState.SHOP),
    ("buy_confirm", LabyrinthStoneState.BUY_CONFIRM),
    ("pause_menu", LabyrinthStoneState.PAUSE),
    ("giveup_confirm", LabyrinthStoneState.GIVEUP),
    ("quick_menu", LabyrinthStoneState.QUICK_MENU),
    ("lobby", LabyrinthStoneState.LOBBY),
]


@pytest.mark.parametrize("fixture,expected", PAGE_CASES)
def test_fixture_is_recognised_as_its_page(fixture: str, expected: LabyrinthStoneState):
    machine = build_machine()
    assert machine.observe_page(frame(fixture)) is expected


# ---- ② 每一页想点的那一下（含点击坐标来自模板，不是写死的）--------------------

# (夹具, 状态机上的跨帧标记, 期望动作名, 期望出口)
#
# ⚠️ 跨帧标记是这套判据的关键：地图页 / 商人房 / 商店页的画面都和「迷宫房间」长得很像，
# 而「传送过了没」「商店逛完没」这些**画面上看不出来**，只能靠标记。
ACTION_CASES = [
    # ⚠️ 落点必须含「迷宫详情页」：PC 客户端上点「迷宫」卡片**直接进详情页**，
    # 中间的「迷宫列表」只在某些情况下出现（2026-11-03 08:48 实测漏写就报
    # 「迷宫列表未识别」、干等 45 秒）。
    ("battle_menu", {}, "open-labyrinth", ("迷宫列表", "迷宫详情页")),
    ("labyrinth_list", {}, "open-labyrinth-entry", ("迷宫详情页",)),
    ("labyrinth_detail", {}, "open-team", ("准备战斗页",)),
    (
        "team_ready",
        {},
        "start-battle",
        ("迷宫房间", "开场剧情", "迷宫内战斗（本路线不该出现）"),
    ),
    ("story", {"entered": True}, "skip-story", ("迷宫房间",)),
    ("room", {"entered": True}, "open-map", ("地图页",)),
    # 地图页：视口里没有商人 pin ⇒ 先拖；拖出来之后才点那个出口。
    ("map", {"entered": True}, "pan-map", ()),
    ("map_pinned", {"entered": True}, "use-exit-pin", ("传送确认弹窗",)),
    (
        "teleport_confirm",
        {"entered": True, "teleport_armed": True},
        "confirm-teleport",
        ("迷宫房间",),
    ),
    ("room_west", {"entered": True, "teleported": True}, "walk-west", ()),
    (
        "merchant_room",
        {"entered": True, "teleported": True},
        "open-shop",
        ("商店页",),
    ),
    ("shop", {"entered": True, "teleported": True}, "buy-stone", ("购买确认弹窗",)),
    # ⚠️ 购买确认框只有**本路线刚点过「购买」**才允许确认（``buy_armed``）。
    (
        "buy_confirm",
        {"entered": True, "teleported": True, "buy_armed": True},
        "confirm-buy",
        ("商店页",),
    ),
    ("battle", {"entered": True}, "open-pause", ("暂停菜单",)),
    ("pause_menu", {"entered": True}, "give-up", ("放弃战斗确认框",)),
    ("giveup_confirm", {"entered": True}, "confirm-give-up", ("迷宫详情页",)),
    # 详情页来两次，画面一模一样、下一步却相反 ⇒ 只看 ``entered``。
    ("detail_after_giveup", {"entered": True}, "open-quick-menu", ("右上角快捷菜单",)),
    ("quick_menu", {"entered": True}, "go-tavern", ("大厅",)),
    (
        "unknown_dialog",
        {"entered": True},
        "cancel-unknown-dialog",
        ("地图页", "迷宫房间", "商人房", "商店页"),
    ),
]


@pytest.mark.parametrize("fixture,flags,action,targets", ACTION_CASES)
def test_action_and_its_declared_exit(
    fixture: str, flags: dict, action: str, targets: tuple[str, ...]
):
    machine = build_machine(**flags)
    screen = frame(fixture)

    result = machine.next_action(screen)

    assert result is not None, f"{fixture} 上应该有动作，实际收工了"
    assert result.name == action
    assert result.target_pages == targets
    # 契约两半都不能空：从哪来 + 到哪去（同页动作用页内证据）。
    assert result.source_page, f"{action} 没声明来源页面"
    assert result.target_pages or result.in_page_evidence, (
        f"{action} 既没写去处也没写页内验收依据"
    )


def test_lobby_has_no_action_and_closes_the_pass():
    machine = build_machine()
    assert machine.next_action(frame("lobby")) is None
    assert machine.completed_cycles == 1
    assert machine.state is LabyrinthStoneState.FINISHED


# ---- ③ 「选中的不是 1 区域」那一支 ---------------------------------------------
#
# ⚠️ **这条判据只有正例**：勘探那天拍到的详情页上选中的就是 1 区域
# （金色选中框 y 568~709、区域 1 标签中心 y=621、落差 69）。
# 「选中的是 2 区域」那一帧没有拍到 ⇒ 这里用把容差收紧到 5 的办法**模拟**，
# 只能证明「分支接上了、点的是 1 区域那一行的坐标」，证明不了落差阈值本身。
# 真机上第一次撞上会由主循环记日志 + 留诊断。


def test_switches_to_region_one_when_it_is_not_selected(monkeypatch):
    machine = build_machine()
    screen = frame("labyrinth_detail")

    assert machine.next_action(screen).name == "open-team"

    monkeypatch.setattr(labyrinth_stone, "REGION_ROW_TOLERANCE", 5)
    machine.entered = False
    switched = machine.next_action(screen)

    assert switched.name == "select-region-1"
    assert switched.point == (1080, 621)  # 区域 1 标签的中心（模板量出来的）
    assert switched.target_pages == ()
    assert switched.in_page_evidence, "同页动作必须写清页内验收依据"


# ---- ④ 地图：搜 → 拖 → 再搜，认不出就收工 --------------------------------------


def test_map_pans_until_the_merchant_pin_shows_up():
    machine = build_machine(entered=True)

    panned = machine.next_action(frame("map"))
    assert panned.name == "pan-map"
    assert panned.in_page_evidence, "拖动是同页动作，必须写清页内验收依据"

    pinned = machine.next_action(frame("map_pinned"))
    assert pinned.name == "use-exit-pin"
    # 坐标不是写死的：松鼠 pin 量出来在 (528,289)，出口 pin 在它的 (+171,-159) 处。
    assert pinned.point == (699, 130)


def test_map_closes_itself_after_three_pans():
    """拖到上限仍看不到目标 pin ⇒ 关地图收工，绝不在地图上原地打转。"""
    machine = build_machine(entered=True)

    names = [machine.next_action(frame("map")).name for _ in range(4)]

    assert names == ["pan-map"] * 3 + ["close-map"]
    assert machine.map_done is True


def test_teleport_dialog_is_cancelled_when_the_route_did_not_ask_for_it():
    """拖地图那一下是空点，万一戳到别的 pin 弹出传送框 ⇒ 按取消，绝不替它确认。"""
    machine = build_machine(entered=True)

    action = machine.next_action(frame("teleport_confirm"))

    assert action.name == "cancel-teleport"
    assert action.point == (802, 796)  # 弹窗左边的「取消」（模板量出来的）


def test_a_room_that_has_not_settled_yet_waits_instead_of_giving_up():
    """走路 / 淡入期间认不出开地图的按钮 ⇒ **等**，绝不能当成「这一趟做不成」。

    2026-09-25 真机翻车：进迷宫第 0.3 秒那一帧菱形还没淡入完（模板 0.337，
    而当时的阈值是 0.80）⇒ 被判「认不出」⇒ 直接放弃战斗回家。用户原话：

    > 你放弃战斗的这一个理由是什么？你是看到了什么东西才去选择放弃？

    ⚠️ 手上没有「淡入到一半」的真帧（抓到的时候已经站稳了），所以用**把左上角
    那块用房间自己的背景盖住**的办法模拟。它守的是规则本身：**没看见 = 等**，
    不是「没看见 = 放弃」。
    """
    machine = build_machine(entered=True)
    faded = frame("room").copy()
    faded[40:240, 0:260] = faded[600:800, 900:1160]

    assert machine.observe_page(faded) is LabyrinthStoneState.ROOM
    with pytest.raises(UnrecognizedScreen) as caught:
        machine.next_action(faded)

    assert "不放弃" in str(caught.value)
    assert machine.map_done is False, "「还没站稳」绝不能记成「地图这段认输了」"
    assert machine.blocked_reason == "", "没放弃就不该有「做不成」的原因"


def test_the_map_button_is_found_by_its_blue_blob_when_the_template_fades(monkeypatch):
    """菱形是半透明的，走路时会掉分 ⇒ 模板过不了阈时靠「左上角那坨蓝色」兜住。"""
    monkeypatch.setattr(labyrinth_stone, "MAP_BUTTON_MIN_SCORE", 1.01)  # 模板那条彻底失效
    machine = build_machine(entered=True)

    action = machine.next_action(frame("room"))

    assert action.name == "open-map"
    assert "蓝色块" in action.reason


def test_a_real_battle_in_the_labyrinth_is_given_up_with_its_own_reason():
    """撞上真战斗才撤 —— 回合条是**看得见的事实**，不是「没看见某个东西」。

    但要记下自己的原因：回家之后日志得写「撞上了战斗」，而不是「商店没有可买的强化石」。
    """
    machine = build_machine(entered=True)

    action = machine.next_action(frame("battle"))

    assert action.name == "open-pause"
    assert "战斗" in machine.blocked_reason


def test_walking_west_is_bounded():
    """往西走满 3 间房还没到商人 ⇒ 撤出，但**必须记下真实原因**（回家后报错）。"""
    machine = build_machine(entered=True, teleported=True)

    names = [machine.next_action(frame("room_west")).name for _ in range(4)]

    assert names == ["walk-west"] * 3 + ["open-pause"]
    assert "还没走到流浪商人" in machine.blocked_reason


# ---- ⑤ 商店：只买「强化石」，买过的行跳过 ---------------------------------------


def test_shop_buys_friendship_points_first_when_they_sit_on_top():
    """2026-10-31 需求变更：友情点数（18,000）**也买** —— 用户「这个材料我也缺了」。

    ⚠️ 这条用例的前身是 2026-09-25 那次事故的守护：当时「类别 → 按钮」的偏移写反
    （+139，实测应是 −82），每一行都拿**下一行**的类别标签来判断自己，于是友情点数
    被**误**当成强化石真的买了。那时的断言是「第一行是友情点数，绝不能点」。

    现在友情点数**本身就是目标商品**（走图标那一路，不看类别）：这一屏 5 行里
    它排在最上面（友情点数 / 下级装备强化石 / 传说神器强化石 / 下级装备强化石 /
    强化拳套），所以先买它，买完再买下面那两行强化石。

    保留的守护（另有用例）：**仍然不买**强化拳套那种「类别不对、名字里也没石」的行。
    """
    machine = build_machine(entered=True, teleported=True)

    action = machine.next_action(frame("shop"))

    assert action.name == "buy-stone"
    assert action.point == (1792, 299), "最上面那行是友情点数，现在它是目标商品"


def test_shop_refuses_the_glove_row_that_is_the_only_one_still_alive():
    """``shop_mostly_bought`` 上唯一还亮着的那一行是**强化拳套**（18,000）⇒ 不点。

    ⚠️ 这是事故里**真的被买走**的那一行：4 行强化石都已买过（按钮变灰），
    只剩强化拳套亮着；旧判据借下一行「强化石」的类别把它认成了强化石。
    """
    machine = build_machine(entered=True, teleported=True)

    action = machine.next_action(frame("shop_mostly_bought"))

    assert action.name == "scroll-shop", "强化拳套不是强化石，一块都不许买"


def test_the_stone_name_lock_still_holds_when_the_category_pairing_slips(monkeypatch):
    """把类别配对**拨回事故那个错值**：光靠它就会去买强化拳套，石字锁必须兜住。

    这是「两道锁」里第二道存在的全部意义 —— 两条问的是不同的事，不会一起错。
    """
    monkeypatch.setattr(labyrinth_stone, "BUY_TO_CATEGORY_DY", 139)
    machine = build_machine(entered=True, teleported=True)

    assert machine.next_action(frame("shop_mostly_bought")).name == "scroll-shop"


def test_shop_skips_the_rows_that_are_already_bought(monkeypatch):
    """卖完（按钮旁写着「0/1」）的行一律跳过 —— 只能靠**按钮上有没有白字**认出来。

    灰按钮的模板分数照样过阈（0.95+），所以只能靠亮度判 —— 这是本文件
    唯一一条能证明「卖没卖完」判据真的接在决策上的用例。

    ⚠️ 2026-09-25 第二次真机事故：这里原来断言的是**相对亮度**，真机上它把
    「已售罄」判成「还能买」⇒ 对着一行写着 0/1 的行连点 4 次、整条路线卡死。
    ⚠️ 2026-10-19 第三次事故：改判「按钮区域的最亮像素」之后又被**一颗**游离白像素
    骗过（底边被裁那行的按钮块混进邻行白字碎片，239 > 200）。
    现在判「按钮上有多少颗白字像素」：亮行 817~844 颗，售罄行 0~3 颗。
    """
    machine = build_machine(entered=True, teleported=True)

    assert machine.next_action(frame("shop")).name == "buy-stone"

    # 反证：把「有没有白字」这条判据撤掉（门槛设为 0），已经卖完的行就会被当成还能买。
    #
    # ⚠️ 2026-09-26 实测（``runtime_logs/_probe_shop_rows.py``）：门槛归零后它选中的是
    # **(1792, 408)** 那一行，**白字像素只有 0 颗** —— 正是「已售罄」的灰按钮
    # （还能买的按钮是 800 多颗 ⇒ 0 就是事故现场）。
    # 不是早先断言的 (1789,186)：那一行的按钮在这一帧上另有判据挡着，拿它做反证
    # 等于拿一张不存在的后果去吓人 —— 反证必须指着**真会发生的那个后果**。
    monkeypatch.setattr(labyrinth_stone, "BUY_BUTTON_WHITE_PIXELS", 0)
    machine = build_machine(entered=True, teleported=True)
    assert machine.next_action(frame("shop_mostly_bought")).point == (1792, 408)


def test_a_clipped_sold_out_row_is_not_bought(monkeypatch):
    """**钉住 2026-10-19 真机事故**：窗口越界 + 「取最亮一颗」⇒ 对着售罄行连点 4 次。

    现场帧 ``shop_clipped_bottom_row_live_20261019``（= 那次 ``retry_exhausted_buy-stone``
    的诊断图）：商店列表滚到顶上半行被裁，最底下那行「下级装备强化石 0/1」的按钮被
    窗口底边切掉，而它**右边**紧挨着下一行天头被切断的白字碎片（纯白）。

    旧窗口 ``BUY_PAD_HALF`` = ±(80,32) 比按钮模板（116×46）左右各宽 22px ⇒ 把碎片圈了
    进来，一整块 143 的灰按钮被量出 **239**（>200）⇒ 判「还亮着」⇒ 点 (1792,1061)
    四次 ⇒ 重试耗尽 ⇒ 回家流程又在商店页上耗满 120 秒。

    新口径（窗口收进模板 footprint + 数白字像素）在这帧上的读数：
    亮行 **817 / 835 / 844** 颗，售罄行 **0** 颗，被裁的售罄行 **3** 颗（阈 400）。
    """
    from auto_game_unified.games.epic7.evidence import labyrinth_stone as evidence

    screen = frame("shop_clipped_bottom_row_live_20261019")

    # 同时把「旧口径在这帧上确实会翻车」钉住 —— 反证必须指着真会发生的后果。
    half_w, half_h = evidence.BUY_PAD_HALF
    cx, cy = 1792, 1061
    wide_window = screen[cy - half_h : cy + half_h, cx - half_w : cx + half_w]
    assert int(wide_window.max(axis=2).max()) == 239, "旧口径应当被邻行碎片抬到 239"

    assert evidence.button_white_pixels(screen, (cx, cy)) == 3

    machine = build_machine(entered=True, teleported=True)
    action = machine.next_action(screen)

    # 2026-10-31：友情点数（(1792,843) 那行，图标判据）现在是目标商品 ⇒ 会买它；
    # 但**被裁掉的那行 (1792,1061) 仍然不能点** —— 那才是这条用例守的东西。
    assert action.name == "buy-stone"
    assert action.point == (1792, 843)
    assert action.point != (cx, cy), "被裁的售罄行（3 颗白字）居然被点了"


def test_the_white_pixel_floor_and_ceiling_leave_a_wide_gap():
    """真阳性地板 ↔ 必须挡住的天花板：阈值必须两头都留够，不许贴着任何一边。"""
    from auto_game_unified.games.epic7.evidence import labyrinth_stone as evidence

    live = evidence.button_white_pixels(frame("shop"), (1792, 299))
    clipped = evidence.button_white_pixels(
        frame("shop_clipped_bottom_row_live_20261019"), (1792, 1061)
    )

    assert live >= evidence.BUY_BUTTON_WHITE_PIXELS * 2, "真阳性地板离阈值太近"
    assert clipped <= 10, "必须挡住的那类行给出了太多白像素"
    assert evidence.BUY_BUTTON_WHITE_PIXELS > clipped * 40, "离噪声太近"


def test_a_row_with_no_white_text_is_sold_out_even_at_the_old_ratio(
    monkeypatch,
):
    """**钉住这次真机事故**：旧口径（相对亮度）在真机上把售罄行判成还能买。

    真机诊断帧（``20260925_154655_382551_manual_stop.png``）实测：

    | 行 | 按钮旁 | 最亮像素 | 旧口径 平均÷帧均值 |
    |---|---|---|---|
    | 亮 | 1/1 | 255 | 2.93 |
    | 售罄 | 0/1 | 140~146 | **1.26~1.43** |

    旧阈值是 1.20 ⇒ 售罄行**全部**被判成「还能买」。这条用例把那个后果钉住：
    在售罄帧上，无论旧阈值调到哪里，新判据都必须给出 ``scroll-shop``。
    """
    monkeypatch.setattr(labyrinth_stone, "BUY_BUTTON_WHITE_PIXELS", 400)
    machine = build_machine(entered=True, teleported=True)

    action = machine.next_action(frame("shop_mostly_bought"))

    # 上一帧唯一一行「强化石」是第 1789,186 那行（0/1，已售罄）；
    # 剩下唯一亮着的是「强化拳套」（名字里没有「石」）⇒ 必须一路滑到底。
    assert action.name == "scroll-shop"
    assert machine.buy_armed is False


def test_shop_refuses_a_row_whose_category_cannot_be_paired(monkeypatch):
    """类别配不上的**强化石行**不点；但友情点数走图标那一路，不受类别偏移影响。

    2026-10-31：友情点数改由商品**图标**认（它的类别标签在迷宫写「召唤」、
    在秘密商店写「货币」，会变）。所以把 ``BUY_TO_CATEGORY_DY`` 改坏之后，
    仍然只会买友情点数那一行 —— 强化石行反而买不到了，这正是「认不出就不买」。
    """
    machine = build_machine(entered=True, teleported=True)
    assert machine.next_action(frame("shop")).name == "buy-stone"

    monkeypatch.setattr(labyrinth_stone, "BUY_TO_CATEGORY_DY", 0)
    machine = build_machine(entered=True, teleported=True)
    action = machine.next_action(frame("shop"))
    assert action.name == "buy-stone"
    assert action.point == (1792, 299), "类别坏了之后只剩图标那一路：买友情点数"


def test_shop_scrolls_a_few_times_and_then_leaves(monkeypatch):
    """商店里一行都买不了（今天全卖完了）⇒ 下滑几次就走，不磨时间。

    ⚠️ 没有「一行都买不到」的真帧，所以这里用把「有没有白字」的阈值拉到 999
    的办法**模拟**。它证明的是「收尾这条分支接上了」，不是阈值本身。
    """
    monkeypatch.setattr(labyrinth_stone, "BUY_BUTTON_WHITE_PIXELS", 999.0)
    machine = build_machine(entered=True, teleported=True)

    names = [machine.next_action(frame("shop")).name for _ in range(5)]

    assert names == ["scroll-shop"] * 3 + ["leave-shop", "leave-shop"]
    assert machine.shop_done is True


def test_leaving_the_shop_says_how_many_stone_rows_were_sold_out(monkeypatch):
    """收工时要说清「认出来几行是强化石、只是都卖完了」，别让人以为没认出来。"""
    monkeypatch.setattr(labyrinth_stone, "BUY_BUTTON_WHITE_PIXELS", 999.0)
    machine = build_machine(entered=True, teleported=True)

    reasons = [machine.next_action(frame("shop")).reason for _ in range(4)]

    assert "已售罄" in reasons[-1]
    assert "已售罄" in reasons[0] or "卖完" in reasons[0]


def test_a_purchase_dialog_the_route_did_not_ask_for_is_cancelled():
    """不是本路线点出来的购买框 ⇒ 按取消。花的是真金白银，不能替人按「确定」。"""
    machine = build_machine(entered=True, teleported=True)

    action = machine.next_action(frame("buy_confirm"))

    assert action.name == "cancel-buy"
    assert action.point == (722, 815)  # 弹窗左边的「取消」（模板量出来的）


def test_confirming_a_purchase_counts_it_and_says_which_row():
    """确认购买 ⇒ 记进账单（第几块 + 商店哪一行），收尾汇报要用。"""
    machine = build_machine(entered=True, teleported=True, buy_armed=True, pending_row=516)

    assert machine.next_action(frame("buy_confirm")).name == "confirm-buy"

    assert machine.bought == 1
    assert machine.purchase_rows == [516]
    assert "第 516 行" in (machine._purchase_tally() or "")


def test_leaving_the_shop_closes_the_pass_instead_of_reopening_it():
    """逛完商店回到商人房：不能再点蓝松鼠把商店开第二次。"""
    machine = build_machine(entered=True, teleported=True, shop_done=True)

    assert machine.next_action(frame("merchant_room")).name == "open-pause"


# ---- ⑥ 真 Runner：整条链走一遍 -------------------------------------------------


class FakeRuntime:
    """按顺序吐真夹具帧的假 Runtime。

    ⚠️ 时钟**必须走**：主循环对「同名动作连点」有一条「等 8 秒再看」的窗口
    （``_SHORT_RETRY_SECONDS``），而商店要连着下滑三次 —— 时钟停着的话第二次
    永远不会发出去，测试会原地打转。每抓一帧走 10 秒，刚好越过 8 秒的重试窗口，
    又远小于任何一条状态超时。
    """

    diagnostic_dir = None
    dry_run = False

    def __init__(self, frames: list[np.ndarray], step: float = 10.0) -> None:
        self._frames = frames
        self._index = 0
        self._step = step
        self.now_value = 0.0
        self.clicks: list[tuple[tuple[int, int], str]] = []
        self.swipes: list[tuple[tuple[int, int], tuple[int, int], int, str]] = []
        self.messages: list[str] = []

    def now(self) -> float:
        return self.now_value

    def capture(self) -> np.ndarray:
        # 取完就停在最后一帧：让主循环自己收尾，不要越界。
        index = min(self._index, len(self._frames) - 1)
        self._index += 1
        self.now_value += self._step
        return self._frames[index]

    def click(self, point, name) -> None:
        self.clicks.append((point, name))

    def swipe(self, start, end, duration_ms, name) -> None:
        self.swipes.append((start, end, duration_ms, name))

    def log(self, message: str) -> None:
        self.messages.append(message)

    def save_diagnostic(self, label, screen):
        return Path(label)


def _script(*fixtures: str, repeat: int = 2) -> list[np.ndarray]:
    """每一帧重复 repeat 次：主循环要**两帧稳定**才肯发动作。"""
    frames: list[np.ndarray] = []
    for name in fixtures:
        frames.extend([frame(name)] * repeat)
    return frames


# 商店在脚本里出现 4 次：三次下滑 + 一次离开（每次 2 帧才凑够一次稳定动作）。
FULL_CHAIN = (
    "battle_menu",
    "labyrinth_list",
    "labyrinth_detail",
    "team_ready",
    "story",
    "room",
    "map",
    "map_pinned",
    "teleport_confirm",
    "room_west",
    "merchant_room",
    "shop",
    "shop",
    "shop",
    "shop",
    "merchant_room",
    "pause_menu",
    "giveup_confirm",
    "detail_after_giveup",
    "quick_menu",
    "lobby",
)


def test_runner_walks_the_whole_route_and_closes_one_pass(monkeypatch):
    """真主循环跑完整条链 —— 这是唯一能守住「判据真的接进主循环」的用例。

    2026-09-25 骑士团捐赠连出两次事故，都发生在状态机与主循环**之间**：
    判据本身是对的，但主循环压根没用它。只调 ``next_action`` 测不出来。

    ⚠️ 商店这一段把「按钮还亮着」的亮度门槛抬到 **999**（真按钮最亮只有 255）来模拟
    「今天全买过了」，因为手上的真帧每次都还有东西可买。它走的是收尾分支
    （下滑 → 离开），买东西那一支由上面的用例单独钉住。
    """
    monkeypatch.setattr(labyrinth_stone, "BUY_BUTTON_WHITE_PIXELS", 999.0)
    machine = build_machine()
    runtime = FakeRuntime(_script(*FULL_CHAIN))
    runner = LabyrinthStoneRunner(
        machine, runtime, sleep=lambda _: None, poll_seconds=0.0
    )

    completed = runner.run(max_cycles=1)

    assert completed == 1
    assert [name for _, name in runtime.clicks] == [
        "open-labyrinth",
        "open-labyrinth-entry",
        "open-team",
        "start-battle",
        "skip-story",
        "open-map",
        "pan-map",
        "use-exit-pin",
        "confirm-teleport",
        "walk-west",
        "open-shop",
        "scroll-shop",
        "scroll-shop",
        "scroll-shop",
        "leave-shop",
        "open-pause",
        "give-up",
        "confirm-give-up",
        "open-quick-menu",
        "go-tavern",
    ]
    # 手势只能由 Runner 补发：地图拖一次、商店下滑三次。
    assert [name for *_, name in runtime.swipes] == [
        "labyrinth-map-pan",
        "labyrinth-shop-scroll",
        "labyrinth-shop-scroll",
        "labyrinth-shop-scroll",
    ]
    # 「进过迷宫 / 传送过了 / 商店逛完了」这三个跨帧进度必须真的被主循环带着走。
    assert machine.entered is True
    assert machine.teleported is True
    assert machine.shop_done is True
    # 每个动作都得通过机器校验才发得出来（缺契约当场 RuntimeError，跑不到这里）。
    assert LabyrinthStoneRunner._REQUIRE_TRANSITION_CONTRACT is True


# 买东西那一支：商店来两次（第一次买、第二次已经没得买 ⇒ 下滑收尾）。
BUY_CHAIN = (
    "battle_menu",
    "labyrinth_list",
    "labyrinth_detail",
    "team_ready",
    "story",
    "room",
    "map",
    "map_pinned",
    "teleport_confirm",
    "room_west",
    "merchant_room",
    "shop",
    "buy_confirm",
    # 回到商店后：下滑三次仍无可买的 ⇒ 离开（每次下滑也要两帧才凑够一次稳定动作）
    "shop_mostly_bought",
    "shop_mostly_bought",
    "shop_mostly_bought",
    "shop_mostly_bought",
    "merchant_room",
    "pause_menu",
    "giveup_confirm",
    "detail_after_giveup",
    "quick_menu",
    "lobby",
)


def test_runner_buys_a_row_and_comes_back_to_the_shop():
    """买东西那一支：点「购买」→ 二次确认 → 回商店接着逛 → 收工回大厅。

    ⚠️ 全链只有**一处**是模拟的：真机上买完那一行**当场变灰**，夹具不会跟着变。
    所以这里给机器挂一个替身 —— 「已经买过东西之后，这一屏就当作没有可买的了」，
    让它走下滑 → 离开的收尾分支。买东西那一笔本身是**真判据**：相对亮度
    1.84 ≥ 1.2，坐标由模板量出来，二次确认也走真模板。
    """
    machine = build_machine()
    real_buyable_row = machine._buyable_row

    def nothing_left_after_the_first_purchase(screen):
        if machine.bought:
            return None
        return real_buyable_row(screen)

    machine._buyable_row = nothing_left_after_the_first_purchase

    runtime = FakeRuntime(_script(*BUY_CHAIN))
    runner = LabyrinthStoneRunner(
        machine, runtime, sleep=lambda _: None, poll_seconds=0.0
    )

    assert runner.run(max_cycles=1) == 1

    names = [name for _, name in runtime.clicks]
    assert names == [
        "open-labyrinth",
        "open-labyrinth-entry",
        "open-team",
        "start-battle",
        "skip-story",
        "open-map",
        "pan-map",
        "use-exit-pin",
        "confirm-teleport",
        "walk-west",
        "open-shop",
        "buy-stone",
        "confirm-buy",
        "scroll-shop",
        "scroll-shop",
        "scroll-shop",
        "leave-shop",
        "open-pause",
        "give-up",
        "confirm-give-up",
        "open-quick-menu",
        "go-tavern",
    ]
    # 商店那一段的手势由 Runner 补发：地图拖一次、下滑三次。
    assert [name for *_, name in runtime.swipes] == [
        "labyrinth-map-pan",
        "labyrinth-shop-scroll",
        "labyrinth-shop-scroll",
        "labyrinth-shop-scroll",
    ]
    # 买到的块数要真的记下来（收尾日志会说「本轮买了几块」）。
    assert machine.bought == 1


def test_open_shop_uses_short_retry_not_the_45s_transition_window():
    """回归守卫：点蓝松鼠本体开店若被入场过场遮罩吃掉，必须 8 秒就重点。

    ⚠️ 当初的毛病是 open-shop 走默认 45 秒转场重试窗口：遮罩一两秒就散，
    但主循环要等满 45 秒才重新点，体感就是「一直点不到、过好一会又能点到」。
    谁把 open-shop 移出 ``_SHORT_RETRY_ACTIONS``，这条会变红把它拦住。
    """
    runner = LabyrinthStoneRunner(
        build_machine(),
        FakeRuntime([]),
        sleep=lambda _: None,
        poll_seconds=0.0,
    )
    assert "open-shop" in LabyrinthStoneRunner._SHORT_RETRY_ACTIONS
    assert runner._action_retry_seconds("open-shop") == 8.0
    # 顺带确认：真正的转场动作仍是 45 秒（不被短重试带偏）。
    assert runner._action_retry_seconds("confirm-teleport") == 45


def test_runner_refuses_an_action_without_an_exit_declaration():
    """开关打开后，缺「从哪来 / 到哪去」的动作一步都点不出去。"""
    machine = build_machine()
    runtime = FakeRuntime(_script("battle_menu"))
    runner = LabyrinthStoneRunner(
        machine, runtime, sleep=lambda _: None, poll_seconds=0.0
    )

    broken = labyrinth_stone.LabyrinthStoneAction(
        name="open-labyrinth", point=(1, 1)
    )
    with pytest.raises(RuntimeError, match="缺少转场契约"):
        runner._require_transition_contract(broken)


# 中途卡死的那一支：地图拖不动（MAX_MAP_DRAGS=0 模拟）⇒ 关地图 → 撤 → 回家。
BLOCKED_CHAIN = (
    "battle_menu",
    "labyrinth_list",
    "labyrinth_detail",
    "team_ready",
    "story",
    "room",
    "map",
    "room",
    "pause_menu",
    "giveup_confirm",
    "detail_after_giveup",
    "quick_menu",
    "lobby",
)


def test_runner_fails_loudly_when_the_pass_was_blocked(monkeypatch):
    """**回家 ≠ 完成**：带着「没做成」的原因回大厅，必须报错退出（退出码 1）。

    翻车那次的症状正是「刚进迷宫就放弃，日志却写『已完成一遍』」。这条用例钉住
    ``_check_cycle_completed`` 那道闸：只要 ``blocked_reason`` 非空，
    人虽然平安到家，这一趟照样不算完成。
    """
    monkeypatch.setattr(labyrinth_stone, "MAX_MAP_DRAGS", 0)
    machine = build_machine()
    runtime = FakeRuntime(_script(*BLOCKED_CHAIN))
    runner = LabyrinthStoneRunner(
        machine, runtime, sleep=lambda _: None, poll_seconds=0.0
    )

    with pytest.raises(RuntimeError) as caught:
        runner.run(max_cycles=1)

    assert "没做成" in str(caught.value)
    assert "找不到通往流浪商人的出口" in str(caught.value)
    assert any("这一趟没做成" in message for message in runtime.messages)
    # **先回家，随后报错**：人必须真的走完退出链路，不能把人丢在迷宫里。
    assert [name for _, name in runtime.clicks] == [
        "open-labyrinth",
        "open-labyrinth-entry",
        "open-team",
        "start-battle",
        "skip-story",
        "open-map",
        "close-map",
        "open-pause",
        "give-up",
        "confirm-give-up",
        "open-quick-menu",
        "go-tavern",
    ]
    # 人是平安回家的，但这趟的成绩单是「没买到」。
    assert machine.bought == 0
    assert machine.state is LabyrinthStoneState.FINISHED


# ---- ⑦ 开局接力 ---------------------------------------------------------------


def test_resume_takes_over_on_every_business_page():
    machine = build_machine()
    point = detect_resume_point(machine, frame("labyrinth_detail"))
    assert point is not None
    assert point.page == "迷宫详情页"
    assert point.entry is None  # 接力的落点都在业务链上，不再需要导航


@pytest.mark.parametrize(
    "fixture", ["room", "map", "teleport_confirm", "merchant_room", "shop"]
)
def test_resume_marks_entered_when_the_player_is_already_inside(fixture: str):
    """停在迷宫里 ⇒ 详情页的下一步必须是「回大厅」。

    不拨这个标记的话，回到详情页会被当成「还没进场」，又点一次「选择队伍」
    把人再送进迷宫 —— 与接力「就地接着做」的本意正好相反。
    """
    machine = build_machine()
    point = detect_resume_point(machine, frame(fixture))
    assert point is not None
    assert machine.entered is True


def test_resume_ignores_the_lobby_because_it_is_the_finish_line():
    machine = build_machine()
    assert detect_resume_point(machine, frame("lobby")) is None


def test_resume_refuses_to_take_over_a_purchase_dialog():
    """停在「购买确认框」上不接力：认不出这一行买的是什么，就不能替人按确定。

    宁可回大厅重走一遍，也不能替用户花掉一笔钱（万一是他自己点的「强化拳套」）。
    """
    machine = build_machine()
    assert detect_resume_point(machine, frame("buy_confirm")) is None


# ---- ⑧ 1 区域「完成探险」：今天这趟已经打过（2026-11-04 14:18 真机）---------------

PC_LAB_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_labyrinth_stone_pc"


def pc_lab_frame(name: str) -> np.ndarray:
    raw = cv2.imread(str(PC_LAB_FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert raw is not None, f"缺 PC 夹具 {name}.png"
    return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)[:1132, :1982]


def pc_lab_machine(**flags):
    machine = labyrinth_stone.LabyrinthStoneStateMachine(
        resolve_template_dir(TEMPLATE_ROOT, "pc") / "labyrinth_stone"
    )
    for key, value in flags.items():
        setattr(machine, key, value)
    return machine


def test_pc_region1_completed_skips_the_dead_click_and_goes_home():
    """14:18 真机：1 区域写着「完成探险」，金框停在 2 区域。

    旧行为：``select-region-1`` 对 (1080,467) 连点 4 次毫无变化 → 四次点击未转场
    → 整条每日任务记 ✗。这一行**不是没认出来，是它本来就不能点**，所以补
    「1 区域」模板、调阈值、放宽点击次数全都治不了；必须把它认成正常收工。
    """
    machine = pc_lab_machine()
    screen = pc_lab_frame("region1_completed_pc_20261104")

    assert machine.observe_page(screen) is LabyrinthStoneState.LABYRINTH_DETAIL
    assert machine._region1_completed(screen) is True

    action = machine.next_action(screen)

    assert action is not None
    assert action.name == "open-quick-menu"
    assert action.name != "select-region-1"
    assert action.source_page == "迷宫详情页"
    assert action.target_pages == ("右上角快捷菜单",)
    # 右上角蓝色四格网格实测 0.8971 @ (1858,103)，不是屏幕中心、也不是返回箭头
    assert abs(action.point[0] - 1858) <= 12
    assert abs(action.point[1] - 103) <= 12
    # 是「今天不用打了」，不是「中途做不下去」；后者会让 Runner 回家后报错
    assert machine.already_explored is True
    assert machine.blocked_reason == ""
    assert machine.entered is False


def test_region1_completed_label_must_sit_under_row1(monkeypatch):
    """证伪的第二维：光有绿字不够，必须贴在「1 区域」标签正下方。

    真机 dx=+20 / dy=+36；第二行的状态文字在 dy≈224。哪天「2 区域」也写了
    「完成探险」，这颗模板照样会命中，只有位置配对能把它挡回去。
    """
    machine = pc_lab_machine()
    screen = pc_lab_frame("region1_completed_pc_20261104")
    real_locate = machine._locate

    def shifted(screen_arg, name):
        hit = real_locate(screen_arg, name)
        if name == "region1_completed" and hit is not None:
            return dataclasses.replace(
                hit, center=(hit.center[0], hit.center[1] + 224)
            )
        return hit

    monkeypatch.setattr(machine, "_locate", shifted)

    assert machine._region1_completed(screen) is False
    assert machine.next_action(screen).name == "select-region-1"


def test_region1_completed_does_not_fire_when_row1_is_still_selectable():
    """反例方向：同一页、1 区域还可选（状态是「0%探险」）时，绝不能提前收工。

    这张是模拟器基线夹具，所以走 emulator 口径建机器；PC 图在这批旧帧上
    本来就对不上（见 11-03 的 12 张 PC 覆盖图），不能用它来做阴性对照。
    """
    machine = build_machine()
    screen = frame("labyrinth_detail")

    assert machine._region1_completed(screen) is False
    action = machine.next_action(screen)
    assert action is not None
    assert action.name == "open-team"
    assert machine.already_explored is False


def test_region1_completed_does_not_fire_on_another_page_with_green_text():
    """跨页反例：骑士团「每周任务」页也有绿色文字，全库扫描最高才 0.2995。"""
    machine = build_machine()
    raw = cv2.imread(
        str(ROOT / "tests" / "fixtures" / "epic7_knights_donation"
            / "weekly_tasks_claimable.png"),
        cv2.IMREAD_COLOR,
    )
    assert raw is not None
    screen = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)[:1132, :1982]

    assert machine._region1_completed(screen) is False


def test_already_explored_reports_an_honest_finish_reason():
    """回到家后不许套用「商店里没有可买的强化石」——今天压根没进过迷宫。"""
    machine = pc_lab_machine(already_explored=True)
    screen = frame("lobby")

    assert machine.next_action(screen) is None

    assert machine.state is LabyrinthStoneState.FINISHED
    assert machine.completed_cycles == 1
    assert "完成探险" in machine.finish_reason
    assert "强化石" not in machine.finish_reason
    assert machine.blocked_reason == ""

    # 对称：没拨这个标记时，仍是原来那条「买了几块」的收工口径
    ordinary = pc_lab_machine()
    assert ordinary.next_action(screen) is None
    assert "强化石" in ordinary.finish_reason


def test_preview_does_not_leak_the_already_explored_flag():
    """主循环每帧先 ``preview`` 做两帧稳定确认；新增跨帧进度必须一并还原。

    漏了就会在「还没采信」的那一帧把「今天不用打了」记成事实。
    """
    machine = pc_lab_machine()
    screen = pc_lab_frame("region1_completed_pc_20261104")

    action, _ = machine.preview(screen)

    assert action is not None
    assert action.name == "open-quick-menu"
    assert machine.already_explored is False
    assert machine.completed_cycles == 0


# ---- ⑨ 迷宫列表页（2026-11-04 23:53 真机整链卡死）------------------------------

PC_LIST_FIXTURES = {
    # 同一轮的两次现场帧：一张干净、一张右上角叠了「玩家林下老屋召唤了…」Toast。
    "labyrinth_list_pc_20261104": "干净列表页",
    "labyrinth_list_pc_20261104_toast": "列表页 + Toast",
}


def test_pc_list_page_is_recognised_with_and_without_a_toast():
    """跑完一趟回到列表页，``observe_page`` 必须认得出来。

    事故：``labyrinth_entry`` 的旧 PC 覆盖图在 PC 上**原样只有 0.7767**
    （阈 0.85，共享图 0.7657），于是 ``observe_page`` 返回 None ⇒ 主循环报
    ``unknown_screen_unresolved``，44 秒后第二张帧仍是同一页 ⇒ 整条每日任务
    「页面无进展：迷宫强化石画面[战斗菜单·一般页]未识别」✗。

    修法：按 PC 帧里**完整**的标题包围盒重裁（242x39，旧图 232x44 把最后一个
    字切掉了）。重裁后本帧 1.0000；全库 2186 张 PC 帧里只有这两张真·列表页
    过 0.85，392 张模拟器夹具最高 0.7147（隔离成立，PC 图不去顶模拟器页）。

    Toast 那张是**必须留**的反例：提示条压在右栏上方，正是「同一页两种外观」
    最容易把判据做脆的地方。
    """
    machine = pc_lab_machine()

    for name, label in PC_LIST_FIXTURES.items():
        page = machine.observe_page(pc_lab_frame(name))
        assert page is LabyrinthStoneState.LABYRINTH_LIST, (label, page)


def test_pc_list_page_anchor_does_not_leak_onto_the_battle_menu():
    """跨页反例：赛季菜单 / 详情页不能被认成列表页。"""
    machine = pc_lab_machine()

    for name in ("season_menu_pc_20261104", "region1_completed_pc_20261104"):
        page = machine.observe_page(pc_lab_frame(name))
        assert page is not LabyrinthStoneState.LABYRINTH_LIST, name


def test_the_list_page_fix_is_pc_only():
    """隔离铁律：模拟器模板跑同一张 PC 帧，不许被认成列表页。

    PC 覆盖图只在 ``templates/labyrinth_stone/pc/`` 里，模拟器后端根本读不到它；
    这条钉住「别哪天为了省事把 PC 图挪回共享目录」。
    """
    from auto_game_unified.core import matcher

    machine = labyrinth_stone.LabyrinthStoneStateMachine(
        resolve_template_dir(TEMPLATE_ROOT, "emulator") / "labyrinth_stone"
    )
    previous = matcher.ACTIVE_BACKEND
    matcher.set_active_backend("emulator")
    try:
        for name in PC_LIST_FIXTURES:
            assert machine.observe_page(pc_lab_frame(name)) is not (
                LabyrinthStoneState.LABYRINTH_LIST
            ), name
    finally:
        matcher.set_active_backend(previous)


def test_pc_live_list_page_clicks_the_alt_anchor():
    """2026-11-06 17:28 真机：页面认得出、入口找不到。

    ``observe_page`` 已经用 ``any_of(labyrinth_entry, labyrinth_entry_alt)``
    判成「迷宫列表」（备选图 1.0000），可 ``_at_labyrinth_list`` 仍写死
    ``_required("labyrinth_entry")``（主图那一帧为 None）⇒ 抛 UnrecognizedScreen，
    60 秒后报「页面无进展」，整条迷宫 ✗。

    判据与点击点用两把尺子 = 把已认出的页面又判成认不出。改成同组候选。
    两张现场帧（17:28 失败瞬间 / 17:29 超时）都必须点在 (1690,479)。
    """
    machine = pc_lab_machine()

    for name in (
        "labyrinth_list_pc_20261106_live",
        "labyrinth_list_pc_20261106_timeout",
    ):
        screen = pc_lab_frame(name)
        assert machine.observe_page(screen) is (
            LabyrinthStoneState.LABYRINTH_LIST
        ), name
        action = machine.next_action(screen)
        assert action is not None, name
        assert action.name == "open-labyrinth-entry", name
        assert tuple(action.point) == (1690, 479), (name, action.point)
        assert "labyrinth_entry_alt" in action.reason, name


def test_emulator_never_registers_the_pc_alt_anchor():
    """模拟器候选链退化成原来的单图：模板为 None、证据画像也不登记该原子。"""
    machine = labyrinth_stone.LabyrinthStoneStateMachine(
        resolve_template_dir(TEMPLATE_ROOT, "emulator") / "labyrinth_stone"
    )

    assert machine.templates.labyrinth_entry_alt is None
    assert "labyrinth_entry_alt" not in machine.templates.evidence.atoms
