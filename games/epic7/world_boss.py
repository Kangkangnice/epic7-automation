"""骑士团「世界首领战」自动循环。

## 一轮循环（2026-09-21 实机走通，坐标均为画布坐标 1982×1132）

```
HOME            世界首领战主页 →「选择队伍」(1781,1052)
TEAM_SELECT     选择辅助队伍页 →「组成战斗队伍」(1631,1038)
TEAM_CONFIG     配置队伍页（**分两阶段，靠「自动配置」按钮色相区分**）
                  ├ 按钮橙 = 尚未配置 →「自动配置」(246,1034)
                  └ 按钮蓝 = 已配置   →「战斗开始」(1376,1036)
  ↓（体力不足 → stamina.py：点生命之叶 → 点购买）
BATTLE          已承诺战斗，移交战斗监督
                  └ 认到战斗画面 ⇒ 点右上角「跳过」(1631,97)，很快衔接到结算
  ↓
RESULT          结算页 →「确认」(1730,1036) → 弹出「战斗级别奖励」
LEVEL_REWARD    「全部开启」(961,994) → 同一按钮变「确认」(959,994)
  ↓
RESULT_CONFIRM  回结算页 →「确认」(1730,1036)
  ↓
HOME            回主页 → **先看「每周贡献度」宝箱**（发光=可领 ⇒ 点掉）
                  ├ 还有宝箱可领 ⇒ 先领（领完才算这一轮收尾）
                  └ 没有 ⇒ 看次数：>0 进下一把；0/2 ⇒ 正常结束（退出码 2）
```

## ⚠️ 每个动作都必须声明出处与去处（2026-09-22 修正）

这个模块原先的 ``WorldBossAction`` 只有 ``name`` + ``point``，主循环**点完不回头验收**，
于是 2026-09-22 首次实跑出现「进配置队伍页的同一秒直接点战斗开始」——
漏掉了「自动配置」这一步，队伍是空的就开打，一路蒙到战斗画面认不出才被兜住。

现在对齐 story / expedition 的转场契约：

- ``WorldBossAction`` 带 ``source_page``（我现在站在哪一页）/ ``target_pages``（点完该到哪一页）。
- 所有动作统一经 ``_action()`` 构造，它会 ``_confirm_page(source_page)`` 写 ``_confirmed_page``
  —— 这个字段之前**从未被赋值过**，导致 ``runner_base._transition_completed`` 全程空转。
- 「点自动配置」这类**不换页**的动作 ``target_pages`` **留空**。⚠️ 别写 ``(本页,)``：
  本页永远在集合里 ⇒ 验收永远通过 ⇒ 又退化成秒点。同页动作改填 ``in_page_evidence``
  （页面内的什么变化能证明它生效了），实际判定仍由「下一帧重判画面」承担。
- **2026-09-24：``WorldBossRunner`` 打开 ``_REQUIRE_TRANSITION_CONTRACT``**，动作两个判据
  都空会在**发出去之前**报错。⚠️ 开之前踩过一个坑：``WorldBossAction`` 当时**没有
  ``in_page_evidence`` 字段**，而校验规则是「``target_pages`` **或** ``in_page_evidence``」
  ⇒ 规则里的备选项根本不存在，5 个同页动作一开全被拦。教训写在字段的注释里。

## 页面识别（模板匹配）与点击点（实测固定坐标）分开

- **页面识别**用 ``evidence/world_boss.py`` 的六个锚点（已做全库 185 张排他性扫描）。
- **点击点**用上表这几个实机走查时验证过的固定坐标，不再为按钮单独裁模板：
  这些按钮在页内位置固定，且实机帧上逐个点过、确认有效（见 ``docs/WORLD_BOSS_DESIGN.md`` 第二节）。
  少裁 6 个模板 = 少 6 处会随版本漂移的东西。

## ⚠️ 战斗页面：`battle_scene_visible` **认不出这一屏**（2026-09-22 实跑报错的根因）

世界首领战的战斗画面**不是**竞技场/远征那套「右下 4 格底座 + 左侧行动顺序」布局，
而是「左上 boss 名 + 血条、右上 跳过/聊天/暂停、右侧 12 人分数列」的团本布局。
实测 `battle_scene_visible` 在它上面**恒为 False**（圆只检到 2 个、行动顺序白占比 0.0466）
⇒ 监督的 `recognized` 连续 45 秒为假 ⇒ `battle_unrecognized` 安全停止。
2026-09-22 20:57 那次实跑就是这么停的（报错帧其实已经是结算页在淡入，只差一两秒）。

### 修法：右上角「跳过 」既是识别锚点，也是推进动作

用户实拍确认：战斗画面右上角有「跳过 」，**点它才衔接到结算页**。
画布实测（用户 1920×1080 截图按 `window.py::_legacy_canvas` 的 (0,+52) 偏移还原）：

| 项 | 值 |
|---|---|
| 亮像素包围盒 | x=[1581,1682] y=[81,113]（102×33） |
| 点击中心 | **(1631, 97)** |
| 模板 | `templates/world_boss/battle_skip.png`（117×48，含 8px 余量） |
| 搜索区 | `BATTLE_SKIP_REGION=(1500,55,260,110)` |
| 阈值 | **0.80** |

- **识别**：`battle_scene_visible` **或**「跳过」命中 ⇒ 判定「在战斗中」。
- **推进**：命中时把 `("skip-battle", match.center)` 放进
  `BattleObservation.allowed_action`，由监督点掉；点完进结算页。

⚠️ 两个必读要点：

1. **boss 技能演出会整块隐藏 UI**（「跳过」也一起消失，顶部血条、右侧分数列全没）。
   那种帧认不出来是正常的 —— 一次演出只有几秒，下一帧 UI 回来就重新认到，
   45 秒看门狗靠这个复位。所以不要试图给演出帧单独做锚点。
2. **搜索窗口宽度就是锚点的一部分**：同一张「跳过 」图形在剧情播放页也有，
   但两页里它出现的位置不同（本路线 x≈1581~1682，剧情页 x≈1769~1886）。
   窗口收到 `x < 1760` 之后，剧情页从 0.8585 掉到 0.2803，而真实战斗帧仍有 0.9086。
   把窗口放宽回整条右上角，间距就只剩 0.05 —— 那时锚点会变成「在不在剧情页」的赌注。
   实测表见 `runtime_logs/_wb_battle_anchor_probe.py` 的输出。

⚠️ 骑士团入口图标热区小：点图标**中心** (1235,1020) 才进得去，点边缘或文字都没反应。
导航层用模板匹配取中心点，天然满足这条。

## 次数判据：看「选择队伍」按钮亮/灰（**不用 OCR**）

2026-09-21 用户确认用按钮亮/灰，不在运行期引入 OCR。实测按钮底板那条绿色高亮带：

| 状态 | 显示 | 绿像素占比 |
|---|---|---|
| 还能打 | `1/2` | **59.2%** |
| 打完了 | `0/2` | **0.0%** |

阈值 10% 落在两者之间，离两边都很远。口径仍是「看游戏给的次数」而不是「看进程跑了几轮」，
且**不硬编码上限 2** —— 本判据只回答「按钮还亮不亮」。

⚠️ 判据有两道、**取或**（见 `select_team_enabled`）：第二道是「绿条亮度 ÷ 整幅画面亮度」，
用来挡住**页面淡入的暗帧** —— 绝对亮度判据在整屏压暗到 50% 时会自己塌掉，
而页面识别用的 `TM_CCOEFF_NORMED` 对亮度缩放不敏感，两边一凑会把「还有次数」误判成
「次数用完」。实测表见 `docs/WORLD_BOSS_DESIGN.md` 第十二节。

## 每周贡献度宝箱（#1 = 2026-09-23、#2 = 2026-09-25 用户实拍补充）

主页右上角「每周贡献度」进度条上有两档宝箱，按累计贡献解锁：

| 档位 | 位置 | 画布坐标 | 模板 |
|---|---|---|---|
| 宝箱 #1 | `27,500,000`，进度条**左侧** | 包围盒 (1594,308,126,128)，中心 **(1657,372)** | `weekly_chest_lit.png` |
| 宝箱 #2 | `44,000,000`，进度条**右侧** | 包围盒 (1761,463,126,128)，中心 **(1824,527)** | `weekly_chest2_lit.png` |

两档**必须各用一份模板 + 各管一段搜索区**：#2 发光态对 #1 的模板只有 **0.5161**，
外观不是同一个东西；而 #1 的搜索区右边界收在 1785 本来就是为了避开 #2。

「够量了」的宝箱会**发光**（金色边框 + 亮青白箱体 + 四角星芒），没有的只是普通暗色箱子；
**领过之后**箱子原地变成**绿色对勾**（2026-09-23 用户补图确认，**不弹任何窗口**）。
三种状态可以用同一个「可领」模板分开：

| 画面 | 面板内最高分 |
|---|---|
| 可领（`worldboss_home_chest_claimable.png`） | **1.0000** |
| **已领 = 绿勾**（`worldboss_home_chest_claimed.png`） | 0.7085 |
| 未点亮 1/2（`worldboss_home.png`） | 0.6559 |
| 未点亮 0/2（`worldboss_home_exhausted.png`） | 0.6559 |
| **全库 194 张**里其它路线最高 | 0.4878 |

⇒ 阈值 `WEEKLY_CHEST_THRESHOLD = 0.80`：对「已领」下方余量 0.09，对「未点亮」下方余量 0.14。
⚠️ 「已领」的余量比「未点亮」薄 —— 因为绿勾底下还架着宝箱本体。**改阈值前重跑
`runtime_logs/_wb_chest_build_assets.py`**（阈值 0.80 下全库只命中「可领」那 1 张）。

⚠️ **不要拿「暖金色」颜色掩膜做这件事**（试过，`runtime_logs/_wb_chest_gold_probe.py`）：
**没点亮**的宝箱本身也带暖色内容，而且 `team_config` / `lobby_with_knights` 等页面
同一区域有面积大得多的金色块 ⇒ 颜色判据完全不排他。模板匹配能分开，是因为
「亮箱体 / 暗箱体」的**明暗结构**差异，不是「有没有金色」。

✅ **宝箱 #2（44,000,000）已做**（2026-09-25）：那条「没样本就没做」的欠账已补齐，
采样窗口是「#1 已领（绿勾）/ #2 可领（发光）」的主页实拍（只读截图，见模块常量的注释）。
全库 234 张实测（`runtime_logs/_wb_chest2_assets.py`）：

| 画面 | #2 模板在 #2 搜索区内的最高分 |
|---|---|
| 可领（`worldboss_home_chest2_claimable.png`） | **1.0000** |
| #1 已领的暗帧（`worldboss_home_chest_claimed_dark.png`） | 0.4928 |
| #1 的三种态 | 0.4873 |
| **未点亮主页两版（= #2 未到档）** | **0.2593** |

⇒ #2 沿用同一个阈值 `WEEKLY_CHEST_THRESHOLD = 0.80` 时，下方余量 0.31、上方余量 0.20，
比 #1 干净（#1 真机「已领」态会顶到 0.80 以上，得靠亮度比第二道挡）。
旧的「#2 未到档对 #1 模板得 0.7833、靠搜索区右边界兜住」那条结论**仍然成立且仍要守**：
它说的是 #1 的搜索区，与 #2 自己的模板无关。⇒ **#1 搜索区的右边界仍是承重的**。

⚠️ **「没找到宝箱」也要留结论**（2026-09-26 用户要求）：停在主页、两个槽位都没命中时，
``_chest_scan_report()`` 会把**实测数字**（形状最高分 + 亮度比 + 门槛）写进后面那一步的
理由里 —— 2026-09-25 23:01 那次实跑就是**哑判**：直接「次数用完」收摊，日志里一句宝箱的话
都没有，事后分不清「当时没有」和「判据漏了」。**不许只写「没有宝箱」，更不许写「多半是…」。**

✅ **点完宝箱之后是什么画面：已确认** —— 原地变绿勾，**不弹窗、不换页**。
所以这一步的验收仍然是「**宝箱不再发光**」= 模板不再命中，与「自动配置」按钮橙→蓝同构；
绿勾那一态本身不会命中（0.7085 < 0.80），因此**不会出现「领完还一直点」**。
真正收场的地方在下一轮：次数已经是 0/2 ⇒ `HOME` 分支抛 `AttemptsExhausted`（退出码 2）。

## 体力：零改动复用 ``stamina.py``

行动力不足弹窗的三个模板在本路线实测 0.9999 / 0.9895 / 1.0000，与 story 同一套控件。
只用**生命之叶**买（1 片 → 80 体力），**绝不用钻石**；树叶耗尽 ``StaminaExhausted`` → 退出码 2。
"""

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.matcher import (
    Match,
    find_best_template,
    find_template,
    load_template,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import (
    ResourceExhausted,
    Runtime,
    StaminaExhausted,
)
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.world_boss import (
    REFERENCE_SIZE as WORLD_BOSS_REFERENCE_SIZE,
    build_world_boss_evidence,
)
from auto_game_unified.games.epic7.knights_donation import KNIGHTS_GUILD_HOME_PAGE
from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.stamina import (
    STAMINA_REGIONS,
    load_stamina_templates,
    next_stamina_decision,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.template_paths import is_template_root


class AttemptsExhausted(ResourceExhausted):
    """今天的挑战次数打完了：主页「选择队伍」已经变灰。

    ⚠️ **这条判据写好了很久、却一直没接上**（2026-09-23 实跑暴露）：
    ``select_team_enabled`` 只在单元测试和设计文档里出现过，``next_action`` 从来不问它，
    于是主页在 ``0/2`` 时照样返回 ``open-team-select`` —— 点一颗灰按钮点不动，
    45 秒转场超时 → 重试 4 次 → 回大厅恢复 → 再点，**看起来就是「一直在点」**。
    口径从第一天就是「看游戏给的次数、不看进程跑了几轮」（见模块 docstring），
    这里把它接到实际的决策路径上。

    走 ``ResourceExhausted``（与竞技场「门票耗尽」同一条通道）：还能干、但没本钱了
    —— 不是故障，但也不能装作跑满了要求的轮数，所以给退出码 2。
    """

    stop_label = "今日次数已用完"


class WorldBossState(Enum):
    HOME = "home"
    TEAM_SELECT = "team_select"
    TEAM_CONFIG = "team_config"
    BATTLE = "battle"
    RESULT = "result"
    LEVEL_REWARD = "level_reward"
    RESULT_CONFIRM = "result_confirm"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    WorldBossState.HOME: "世界首领战主页",
    WorldBossState.TEAM_SELECT: "选择辅助队伍",
    WorldBossState.TEAM_CONFIG: "配置队伍",
    WorldBossState.BATTLE: "战斗中",
    WorldBossState.RESULT: "战斗结算",
    WorldBossState.LEVEL_REWARD: "战斗级别奖励",
    WorldBossState.RESULT_CONFIRM: "结算确认",
}


def state_label(state: WorldBossState) -> str:
    return STATE_LABELS.get(state, state.value)


# 实机走查验证过的点击点（画布坐标），随步骤推进逐个使用。
CLICK_POINTS = {
    "open-team-select": (1781, 1052),   # 主页「选择队伍」
    "build-team": (1631, 1038),         # 选择辅助队伍页「组成战斗队伍」
    "auto-configure": (246, 1034),      # 配置队伍页「自动配置」
    "battle-start": (1376, 1036),       # 配置队伍页「战斗开始」
    "open-level-reward": (1730, 1036),  # 结算页「确认」→ 弹奖励
    "open-all-chests": (961, 994),      # 奖励弹窗「全部开启」
    "confirm-level-reward": (959, 994), # 奖励弹窗「确认」（同一按钮换字）
    "confirm-result": (1730, 1036),     # 结算页「确认」→ 回主页
}

# 「选择队伍」按钮底板那条绿色高亮带（基准画布坐标）。
# 2026-09-21 自 worldboss_home.png 的绿色连通块实测：(1550,1066)-(1894,1099)。
SELECT_TEAM_BAR = (1550, 1066, 344, 33)

# 绿条判据（第一道）：绿色像素占比达到此值即认为按钮可点。
SELECT_TEAM_ENABLED_GREEN_RATIO = 0.10

# 绿条判据（第二道）：绿条区域亮度 ÷ 整幅画面亮度。
#
# ⚠️ **为什么第一道不够**（2026-09-23 用 `runtime_logs/_wb_fade_probe.py` 实测钉死）：
# 第一道是 HSV 的绝对亮度（`V >= 90`），**页面淡入时整幅画面一起压暗，它跟着塌**；
# 而页面识别用的 `TM_CCOEFF_NORMED` 对亮度缩放**不敏感** —— 于是「淡入暗帧」会同时
# 满足「认得出是主页」+「绿条判灰」，把**还有次数**误判成「次数用完」⇒ 提前退出。
# 实测 `worldboss_home.png`（1/2）压到 50% 亮度：绿占比 0.5924 → **0.0102**（低于 0.10），
# 而这一刻页面**仍被识别成主页**。这比原来的「一直点」更伤，所以必须堵上。
#
# 相对亮度对整屏压暗免疫（实测，亮度系数 1.0 → 0.1 全程）：
# - 1/2 可点：**1.900 ~ 1.952**（几乎不动）
# - 0/2 真灰：**0.568 ~ 0.615**
# 两侧差 3 倍，阈值 1.2 取在中间。**改阈值前先重跑那个探针。**
SELECT_TEAM_BAR_RELATIVE_V = 1.2

# HSV 绿色范围，与 fodder 判「亮色按钮」用的是同一套。
_GREEN_LOWER = np.array([35, 80, 90])
_GREEN_UPPER = np.array([90, 255, 255])


def select_team_green_ratio(screen: np.ndarray, *, reference_size=WORLD_BOSS_REFERENCE_SIZE) -> float:
    """量「选择队伍」按钮底板的绿色像素占比（0.0~1.0）。"""
    x, y, width, height = SELECT_TEAM_BAR
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    x, y = round(x * scale_x), round(y * scale_y)
    width, height = round(width * scale_x), round(height * scale_y)
    patch = screen[y : y + height, x : x + width]
    if patch.size == 0:
        return 0.0
    mask = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_RGB2HSV), _GREEN_LOWER, _GREEN_UPPER)
    return float(mask.mean()) / 255.0


def select_team_bar_relative_v(
    screen: np.ndarray, *, reference_size=WORLD_BOSS_REFERENCE_SIZE
) -> float:
    """量「选择队伍」高亮带**相对整幅画面**的亮度比（对整屏压暗免疫）。

    淡入会把高亮带和背景**一起**压暗，比值几乎不变；按钮真变灰则是
    「背景照旧、高亮带塌掉」，比值掉到 0.6 上下。实测数据见
    ``SELECT_TEAM_BAR_RELATIVE_V`` 的注释与 ``runtime_logs/_wb_fade_probe.py``。
    """
    x, y, width, height = SELECT_TEAM_BAR
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    patch = screen[
        round(y * scale_y) : round(y * scale_y) + round(height * scale_y),
        round(x * scale_x) : round(x * scale_x) + round(width * scale_x),
    ]
    if patch.size == 0:
        return 0.0
    frame_v = float(cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)[:, :, 2].mean())
    if frame_v <= 0.0:
        return 0.0
    band_v = float(cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)[:, :, 2].mean())
    return band_v / frame_v


# 「每周贡献度」宝箱 #1（`27,500,000` 那一档）在画布上的位置与搜索区。
# 包围盒由用户 1920×1080 实拍截图按 (0,+52) 还原成画布后实测。
WEEKLY_CHEST_BOX = (1594, 308, 126, 128)
# 搜索区套住宝箱 #1，且右边界收在 1785 —— **不盖到进度条右侧的宝箱 #2**（x≈1755 起）。
# 搜索窗口的宽度就是锚点的一部分：放宽会把「是不是宝箱 #1 可领」变成赌注。
WEEKLY_CHEST_REGION = (1535, 250, 250, 250)

# 可领 / 未点亮的阈值。全库 193 张夹具实测（`runtime_logs/_wb_chest_build_assets.py`）：
# 可领 1.0000、未点亮的主页两版都是 0.6559、其它路线最高 0.4878。
# ⇒ 0.80 下方余量 0.14、上方余量 0.31。**改这个数前先重跑那个探针。**
WEEKLY_CHEST_THRESHOLD = 0.80

# 「有没有在发光」这道判据：宝箱区亮度 ÷ 整幅画面亮度。
#
# 2026-09-25 实跑暴露：**光靠模板得分守不住**。真机上「已领（绿勾）」那一态对模板得
# **0.8069**，越过了 0.80 的阈值 ⇒ 程序把已领的箱子当成可领，点 4 次不生效、回大厅重来、
# 再点 4 次，把整条路线拖死；而局内 0/2 本该收场，因为宝箱分支在前，永远走不到次数判断。
# 夹具上同一个「已领」态只有 0.7085 —— 当初按它算出的「下方余量 0.09」在真机上并不存在。
#
# 改用**两道取「与」**（用户的话：「外面有一圈光环才代表可以点」）：
#   ① 形状像不像那个发光宝箱（模板得分 ≥ ``WEEKLY_CHEST_THRESHOLD``）
#   ② 那一块在不在发光（亮度比 ≥ 本常量）
# 全库 227 张实测（`runtime_logs/_wb_chest_brightness_scan.py`）：
#   可领发光 **2.013**、真机已领 **1.081**；
#   别的页面也有很亮的（最高 1.760），但它们形状分只有 0.10~0.31，被 ① 挡掉。
# ⇒ 这两个数**必须成对使用**：单独放宽任一个都会误判（只放亮度 ⇒ 别的明亮页面中招；
#   只放形状 ⇒ 真机已领中招）。
WEEKLY_CHEST_BRIGHTNESS_RATIO = 1.5

# 宝箱是「同页动作」：点完不换页，只能靠它自己不再发光来判断生效。
# 有界收场 —— **真的点了**这么多次还在发光就不再点它（计数在 ``WorldBossRunner``
# 的点击后钩子里，不在状态机里，理由见 ``WorldBossStateMachine._chest_given_up``），
# 让流程继续走到「选择队伍」那一步正常收尾（次数用完 ⇒ 退出码 2），
# 而不是靠「回大厅重来」把整条路线拖住。
#
# ⚠️ 两个槽位**共用**这把尺子（谁先发光就先点谁，总共最多点这么多次）：
# 磨不动通常意味着判据本身出了偏差，此时两个槽位一起撒手是更保守的选择。
WEEKLY_CHEST_MAX_CLICKS = 3

# ── 宝箱 #2（`44,000,000`，进度条右侧那一档）────────────────────────────────
#
# 2026-09-25 晚上补上了这条一直挂着的欠账所需的样本：用户把游戏停在
# 「#1 已领（绿勾）/ #2 可领（发光）」的主页上，用 `tools/capture_fixture.py`
# **只读**截下整幅画布（没有点击、没有改游戏状态）。
#
# 包围盒由**亮度峰值**定位（不是拿 #1 的模板去套）：发光箱体 + 金色光环是这块
# 最亮的东西 —— 在候选区里滑一个 126x128 窗口找平均 V 最大的位置，峰值中心
# **(1824, 527)**，与「#1 模板在 #2 处的最佳匹配」只差几个像素，互为佐证。
#
# ⚠️ **#2 不能复用 #1 的模板**：实测 #2 发光态对 `weekly_chest_lit.png` 只有
# **0.5161**（#1 对它是 1.0000）—— 两档宝箱的外观不是同一个东西。当初 #1 的
# 搜索区右边界收在 1785，本来也就是为了避开 #2；两个槽位必须各管一段。
#
# 全库 234 张 1982x1132 夹具实测（`runtime_logs/_wb_chest2_assets.py`）：
#   正例（#2 可领）**1.0000**；次高 0.4928（#1 已领的暗帧）、#1 的三种态 0.4873；
#   **两版未点亮主页 0.2593（= #2 未到档）** ⇒ 阈值 0.80 下方余量 0.31、上方余量 0.20。
# 比 #1 还干净（#1 的真机「已领」态会顶到 0.80 以上，得靠亮度比第二道挡）。
WEEKLY_CHEST2_BOX = (1761, 463, 126, 128)
# 搜索区只套住 #2：x 上界 1920 就是模拟器渲染区的右边界，不再往外扩到画布黑边
# （黑边是固定内容，扩进去只会让搜索窗口失去「只框这一个槽位」的意义）。
WEEKLY_CHEST2_REGION = (1700, 440, 220, 320)


def weekly_chest_brightness_ratio(
    screen: np.ndarray,
    reference_size=WORLD_BOSS_REFERENCE_SIZE,
    *,
    box: tuple[int, int, int, int] = WEEKLY_CHEST_BOX,
) -> float:
    """宝箱区亮度 ÷ 整幅画面亮度。发光时 ≈2.0，不发光时 ≤1.1。

    用比值而不是绝对亮度：整幅画面被压暗（淡入淡出）时两边一起降，比值不变
    —— 与 ``select_team_bar_relative_v`` 同一个思路。

    ``box`` 默认宝箱 #1；宝箱 #2 传 ``WEEKLY_CHEST2_BOX``（两档位置不同，
    这块区域必须跟着槽位走，否则量的是隔壁箱子）。
    """
    x, y, width, height = box
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    patch = screen[
        round(y * scale_y) : round(y * scale_y) + round(height * scale_y),
        round(x * scale_x) : round(x * scale_x) + round(width * scale_x),
    ]
    if patch.size == 0:
        return 0.0
    frame_v = float(cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)[:, :, 2].mean())
    if frame_v <= 0.0:
        return 0.0
    box_v = float(cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)[:, :, 2].mean())
    return box_v / frame_v


def find_weekly_chest(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    region: tuple[int, int, int, int] = WEEKLY_CHEST_REGION,
    box: tuple[int, int, int, int] = WEEKLY_CHEST_BOX,
    reference_size=WORLD_BOSS_REFERENCE_SIZE,
) -> Optional[Match]:
    """在主页「每周贡献度」面板里找**发光（可领）**的宝箱。命中返回 Match。

    两道取「与」：**形状像**（模板）**且在发光**（亮度比）。理由与实测数据见
    ``WEEKLY_CHEST_BRIGHTNESS_RATIO``。

    默认量的是宝箱 #1（`27,500,000`）；宝箱 #2（`44,000,000`）传自己的模板
    加 ``region=WEEKLY_CHEST2_REGION, box=WEEKLY_CHEST2_BOX`` ——
    两档的外观与位置都不同，**不能混用**（理由见 ``WEEKLY_CHEST2_BOX``）。
    """
    if (
        weekly_chest_brightness_ratio(screen, reference_size, box=box)
        < WEEKLY_CHEST_BRIGHTNESS_RATIO
    ):
        return None
    return find_template(
        screen,
        template,
        WEEKLY_CHEST_THRESHOLD,
        region=region,
        reference_size=reference_size,
    )


def select_team_enabled(screen: np.ndarray) -> bool:
    """主页「选择队伍」按钮是否还可点（= 今天还有次数）。

    ⚠️ **必须是「或」，不能改成「且」**：两道判据分别对付两种情形 ——
    ① 绿得明显（含轻微压暗）⇒ 第一道直接放行，省掉整幅 HSV 的开销；
    ② 不够绿 ⇒ 第二道区分「真变灰」和「只是整屏在淡入变暗」。
    用「且」的话，淡入暗帧仍然会掉在第一道外面 ⇒ 误判「次数用完」⇒ 提前退出。
    """
    if select_team_green_ratio(screen) >= SELECT_TEAM_ENABLED_GREEN_RATIO:
        return True
    return select_team_bar_relative_v(screen) >= SELECT_TEAM_BAR_RELATIVE_V


# 配置队伍页的「三队槽位区」（基准画布坐标）：1/2/3 队的底座与战斗力数字。
TEAM_SLOTS_ROI = (30, 660, 1450, 900)

# 三队**是否真的配好了**，靠槽位区的**画面细节量**（拉普拉斯方差）判断：
# 空槽位只有暗背景 + 一组细描边，画面平滑；配好后是英雄头像，细节密集。
#
# 2026-09-22 实测（画布 1982x1132）：
# | 画面 | 细节量 |
# |---|---|
# | 空队伍（`team_config.png`、实跑失败帧） | 347 ~ 451 |
# | 点过「自动配置」后（`team_config_configured.png`，三队各 5 人，战斗力 58~67 万） | **1181** |
#
# ⇒ 阈值 700 落在两簇正中，两侧余量 249 / 481，非常宽。
#
# ⚠️⚠️ **别再拿「自动配置」按钮的颜色当判据**（2026-09-22 实跑踩过）：
# 那颗按钮（连同三个队伍底座的描边）会在**橙 / 蓝之间整体翻转**
# （同一块区域橙色像素 784 对蓝色像素 16767，两帧完全对称互换），
# 但**与「队伍配没配」毫无关系** —— 同一个「三队全空、战斗力 0」的页面，
# 15:04 抓到的是蓝色、15:11 抓到的是橙色；9 秒内连抓 9 帧颜色不变，
# 说明也不是动画。
# 之前误把「蓝色」读成「已配置」（还把实跑失败帧当成了正样本），
# 于是**跳过了自动配置**，直接去点一个打不起来的「战斗开始」，
# 白等 45 秒后安全停止。**判据要落在「队伍真的被填上了」这件事上。**
TEAM_CONFIGURED_DETAIL = 700.0


def team_detail(
    screen: np.ndarray, *, reference_size=WORLD_BOSS_REFERENCE_SIZE
) -> float:
    """量队伍槽位区的画面细节量（拉普拉斯方差；越大越像「有头像」）。"""
    x0, y0, x1, y1 = TEAM_SLOTS_ROI
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    patch = screen[
        round(y0 * scale_y) : round(y1 * scale_y),
        round(x0 * scale_x) : round(x1 * scale_x),
    ]
    if patch.size == 0:
        return 0.0
    gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def team_configured(screen: np.ndarray) -> bool:
    """三队是否**真的**已经配好（槽位里有英雄，而不是空描边）。

    这是配置队伍页的**验收依据**：点了「自动配置」之后，只有当它变 True
    才允许推进到「战斗开始」—— 也就是「按一次、验收一次」。
    """
    return team_detail(screen) >= TEAM_CONFIGURED_DETAIL


# 战斗画面右上角「跳过 」的搜索区（画布坐标）。
# ⚠️ 这个**窗口宽度就是锚点的一部分**，别放大成整条右上角：
# 「跳过」这个图形与剧情播放页的跳过是同一个，但两页里它出现的位置不同
# （世界首领战 x≈1581~1682，剧情播放页 x≈1769~1886）。窗口收到 x<1760 之后，
# 剧情页从 0.8585 掉到 0.2803，而真实战斗帧仍是 0.9086 —— 间距 0.63。
BATTLE_SKIP_REGION = (1500, 55, 260, 110)

# 「跳过」阈值。全库 192 张夹具实测（`runtime_logs/_wb_battle_anchor_probe.py`）：
# 真实战斗帧 0.9086、boss 技能演出帧 0.2529（UI 整块隐藏，预期不命中）、
# 本路线其它页最高 0.3607（knights_signin_popup）、跨路线最高 0.3815。
# ⇒ 0.80 下方余量 0.44，上方余量 0.11。
BATTLE_SKIP_THRESHOLD = 0.80


def find_world_boss_skip(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    reference_size=WORLD_BOSS_REFERENCE_SIZE,
) -> Optional[Match]:
    """在战斗画面右上角找「跳过 」。命中返回 Match（中心即点击点），否则 None。"""
    return find_template(
        screen,
        template,
        BATTLE_SKIP_THRESHOLD,
        region=BATTLE_SKIP_REGION,
        reference_size=reference_size,
    )


def world_boss_battle_visible(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    reference_size=WORLD_BOSS_REFERENCE_SIZE,
) -> bool:
    """这一帧是不是「世界首领战的战斗画面」。

    两条独立判据取或：

    - ``battle_scene_visible``：竞技场/远征那套「4 格底座 + 左侧行动顺序」布局
      （世界首领战的某种演出帧会命中这里）；
    - 右上角「跳过 」命中：世界首领战团本布局的**唯一稳定锚点**
      （`battle_scene_visible` 在这种帧上恒为 False，见模块 docstring）。
    技能演出帧两条都不命中是**预期行为**：那种帧 UI 整块隐藏，靠下一帧复位看门狗。
    """
    if battle_scene_visible(screen):
        return True
    return find_world_boss_skip(screen, template) is not None

@dataclass(frozen=True)
class WorldBossAction(RouteAction):
    """世界首领战的一个动作，**必须声明出处与去处**。

    ``source_page`` / ``target_pages`` 是主循环的转场契约（见
    ``runner_base.ModeRunnerBase._transition_completed``）：发出动作 = 声明
    「我现在确认站在 source_page，点完之后应该到 target_pages」，
    下一帧主循环拿 ``machine._confirmed_page`` 与它对账。

    ⚠️ 2026-09-22 之前这个类只有 ``name`` + ``point``，于是主循环**点完不回头验收**，
    表现就是「进入配置队伍页的同一秒直接点战斗开始」——中间该不该先点自动配置、
    点了到底生效没有，程序毫无概念，一路蒙到战斗画面认不出才被兜住。
    ``in_page_evidence`` 那条更细的教训（它 2026-09-24 才补上）记在
    ``route_action`` 的模块 docstring 里 —— 那里是字段的唯一出处，以后只改那一处。
    """
    in_page_evidence: str = ""


@dataclass(frozen=True)
class WorldBossTemplates:
    knights_title: np.ndarray
    worldboss_title: np.ndarray
    select_team_button: np.ndarray
    team_select_title: np.ndarray
    team_config_auto: np.ndarray
    level_reward_title: np.ndarray
    result_title: np.ndarray
    # 战斗画面右上角的「跳过 」（点它衔接到结算页，也是战斗画面的识别锚点）。
    battle_skip: np.ndarray
    # 主页「每周贡献度」宝箱 #1 的**可领（发光）**外观。未点亮时同位置得分掉到 0.66。
    weekly_chest: np.ndarray
    # 宝箱 #2 的**可领（发光）**外观。与 #1 不是同一个形状（#2 对 #1 的模板只有
    # 0.5161），所以必须是各自一份模板与各自的搜索区。未到档时得分 0.2593。
    weekly_chest2: np.ndarray
    stamina_popup: np.ndarray
    stamina_material: np.ndarray
    stamina_confirm: np.ndarray
    threshold: float = 0.80
    evidence: object = None


def build_world_boss_templates(template_dir: Path) -> WorldBossTemplates:
    template_root = template_dir.parent

    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return WorldBossTemplates(
        knights_title=load("knights_title"),
        worldboss_title=load("worldboss_title"),
        select_team_button=load("select_team_button"),
        team_select_title=load("team_select_title"),
        team_config_auto=load("team_config_auto"),
        level_reward_title=load("level_reward_title"),
        result_title=load("result_title"),
        battle_skip=load("battle_skip"),
        weekly_chest=load("weekly_chest_lit"),
        weekly_chest2=load("weekly_chest2_lit"),
        **asdict(load_stamina_templates(template_root / "story")),
        evidence=build_world_boss_evidence(template_dir),
    )


# evidence 页面键 -> 状态机状态。判定顺序就是这个元组的顺序。
_PAGE_STATES = (
    ("world_boss.level_reward", WorldBossState.LEVEL_REWARD),
    ("world_boss.result", WorldBossState.RESULT),
    ("world_boss.team_select", WorldBossState.TEAM_SELECT),
    ("world_boss.team_config", WorldBossState.TEAM_CONFIG),
    ("world_boss.home", WorldBossState.HOME),
)


class WorldBossStateMachine:
    """世界首领战一轮循环的纯视觉决策。

    页面识别统一走 ``evidence/world_boss.py`` 的页面组合（六个锚点已做过全库排他性
    扫描），状态机不再自己写「靠上下文猜这是哪一页」的判据 —— 那种判据在
    「状态拨错」时不会自愈，只会卡到超时。
    """

    _REFERENCE_SIZE = WORLD_BOSS_REFERENCE_SIZE
    _THRESHOLD = 0.80
    _REGIONS = {
        "knights_title": (0, 30, 500, 180),
        "worldboss_title": (0, 30, 500, 180),
        "select_team_button": (1450, 990, 532, 130),
        "team_select_title": (0, 140, 520, 140),
        "team_config_auto": (100, 1000, 300, 110),
        "level_reward_title": (600, 120, 800, 160),
        "result_title": (1400, 50, 400, 110),
        **STAMINA_REGIONS,
    }

    def __init__(
        self,
        templates: WorldBossTemplates | Path,
        *,
        initial_state: WorldBossState = WorldBossState.HOME,
    ) -> None:
        self.templates = (
            build_world_boss_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = initial_state
        if self.templates.evidence is not None:
            self._REGIONS = {
                key: atom.region for key, atom in self.templates.evidence.atoms.items()
            }
            self._REGIONS.update(STAMINA_REGIONS)
            self._THRESHOLD = min(
                atom.threshold for atom in self.templates.evidence.atoms.values()
            )
        self.completed_cycles = 0
        self.stamina_replenished = 0
        self.auto_click_attempted = False
        self._confirmed_page = ""
        self._stamina_material_clicked = False
        # 「本轮别再碰那个宝箱了」的标记，由 Runner 在**点够次数仍不消失**后置位
        # （见 ``WorldBossRunner._WEEKLY_CHEST_MAX_CLICKS``）。
        # ⚠️ 计数不能做在状态机里：主循环在等重试窗口的那几秒里会反复调用
        # ``next_action``，状态机数的是「被问了几次」而不是「点了几次」，
        # 上限值对不上真实点击（实测 3 次上限会在第 2 次点击后就撒手）。
        self._chest_given_up = False
        # 本次停在主页时「宝箱扫描」的一句话结论（**只用于写日志**，见
        # ``_chest_scan_report``）。离开主页要去别处时清空，下次回主页重新量。
        self._chest_scan_note = ""
        # 「接力」进来的落点；None = 本轮是正常从主页开始的。Runner 靠它认出
        # 「这一局不是本进程点开的，但已经打起来了」⇒ 跳过状态机直接交战斗监督。
        self.resumed_from: Optional[WorldBossState] = None

    def resume_from(self, state: WorldBossState) -> None:
        """拨到用户停下的那一步，原样接管进度继续往下跑。

        与「从头再来」的区别：接力是「保留当前进度」—— 停在奖励弹窗就接着领，
        而不是退回大厅把这一局的结算丢掉。（2026-09-26 之前另有一条「恢复导航」通道
        专门做「退回主页重开一轮」，随用户「回家就是结束」的拍板整段删除。）

        ⚠️ 本状态机**几乎不需要**拨状态：``next_action`` 每一页都用 ``observe_page``
        现判并覆盖 ``self.state``（唯一例外是 ``RESULT`` 那一支 —— 它靠
        ``state is LEVEL_REWARD`` 分岔，接力刻意走「未领奖励」那一支，见
        ``detect_resume_point``）。这个方法真正的作用是**留下 ``resumed_from`` 记号**。
        """
        self.state = state
        self.resumed_from = state
        self._confirmed_page = ""

    def _confirm_page(self, page: str) -> None:
        """记下「我发出这个动作时确认站在哪一页」。

        主循环 ``runner_base`` 靠这个字段对账转场契约：``_transition_completed``
        要求 ``_confirmed_page ∈ action.target_pages``。不写这个字段，
        所有 ``target_pages`` 都是空转（2026-09-22 之前就是这个状态）。
        """
        self._confirmed_page = page

    def _action(
        self,
        name: str,
        *,
        source_page: str,
        reason: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
        point: tuple[int, int] | None = None,
    ) -> WorldBossAction:
        """构造动作并登记出处，确保转场契约有对账依据。

        ``target_pages`` 默认空 = 「这个动作不换页」。⚠️ 同页动作**不要**写
        ``target_pages=(本页,)``：那样 ``_transition_completed`` 永远返回 True，
        验收形同虚设，分不出「点了没生效」和「点了生效了」。

        **同页动作必须填 ``in_page_evidence``** —— 填「点完这一页会有什么变化能证明它生效了」。
        它和 ``target_pages`` 二选一，本路线的 Runner 已打开机器强制
        （``_REQUIRE_TRANSITION_CONTRACT``），**两个都空会在发动作前报错**。

        ``point`` 为 None 时按 ``CLICK_POINTS`` 查表；调用方也可显式传坐标
        （体力弹窗的两个步骤的坐标是运行期算出来的，不在表里）。
        """
        self._confirm_page(source_page)
        return WorldBossAction(
            name=name,
            point=point if point is not None else CLICK_POINTS[name],
            source_page=source_page,
            target_pages=target_pages,
            reason=reason,
            in_page_evidence=in_page_evidence,
        )

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        template = getattr(self.templates, name, None)
        if template is None:
            return None
        return find_template(
            screen,
            template,
            self._THRESHOLD,
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def battle_visible(self, screen: np.ndarray) -> bool:
        """这一帧是不是世界首领战的战斗画面（含右上角「跳过」锚点）。"""
        return world_boss_battle_visible(screen, self.templates.battle_skip)

    def observe_page(self, screen: np.ndarray) -> Optional[WorldBossState]:
        """按 evidence 页面组合认出当前是哪一页，认不出返回 None。

        判定顺序即 ``_PAGE_STATES`` 的顺序：先判弹窗（奖励 / 结算，它们会盖住底页），
        再判业务页。页面组合之间已经实测互斥（见 ``evidence/world_boss.py``）。

        ⚠️ **战斗页不是模板页，是算出来的**：战斗演出没有稳定标题可裁模板，靠
        ``battle_controls.battle_scene_visible``（右上控制区 + 左侧行动顺序两条
        独立锚点）判断。它必须排在最前 —— 战斗画面上残留的上一页 UI 不该赢过它。
        没有这一步，「战斗开始」的转场契约（target=战斗中）**永远等不到目标**，
        主循环只能靠 45 秒超时收场，表现就是「点完不看结果、盲目重试」。

        ⚠️ 2026-09-22 起再加一条判据：右上角「跳过」。世界首领战的战斗画面是团本
        布局，``battle_scene_visible`` 在它上面恒为 False —— 只靠它的话，整场战斗
        都认不出来，监督会以「战斗画面持续无法识别 45 秒」安全停止（实跑踩过）。
        """
        if self.battle_visible(screen):
            return WorldBossState.BATTLE

        profile = getattr(self.templates, "evidence", None)
        if profile is None:
            return None
        flags = {
            key: self._locate(screen, key) is not None for key in profile.atoms
        }
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    def at_knights_home(self, screen: np.ndarray) -> bool:
        """这一帧是不是**骑士团主页**（导航链的中间站，不是本路线的业务页）。

        判据就是 ``evidence/world_boss.py`` 的 ``world_boss.knights_home`` 页面组合
        （``knights_title``）—— 与导航层认这一页用的是同一条。全库 226 张实测
        只命中 4 张，全部是骑士团主页本身（本路线 2 张 + 骑士团捐赠 2 张），零误命中。

        它不进 ``observe_page``：那一页没有「世界首领战要做什么」的决策，
        只有接力用得上（停在这一页就跳过「回大厅 → 进骑士团」那两级）。
        """
        profile = getattr(self.templates, "evidence", None)
        if profile is None:
            return False
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        return (
            profile.page("world_boss.knights_home").evaluate(flags)
            is EvidenceState.SAFE
        )

    def _handle_stamina(self, screen: np.ndarray) -> Optional[WorldBossAction]:
        decision = next_stamina_decision(
            screen, self._locate, material_clicked=self._stamina_material_clicked
        )
        if decision.status == "idle":
            if self._stamina_material_clicked:
                self.stamina_replenished += 1
                self._stamina_material_clicked = False
            return None
        # 体力弹窗的两个步骤都在弹窗内完成、**不换页**，所以不声明 target_pages
        # （同页写本页会让验收永远通过，见 TEAM_CONFIG 分支的说明）。
        # 验收依据写进 ``in_page_evidence``；实际判定仍由「下一帧重判画面」承担：
        # 弹窗还在 ⇒ next_action 继续返回该动作，按 45 秒窗口有界重试；
        # 弹窗消失 ⇒ 自然回到原页继续。
        if decision.status == "material":
            self._stamina_material_clicked = True
            return self._action(
                "stamina_material",
                point=decision.point,
                source_page="行动力不足弹窗",
                reason="选生命之叶卡片",
                in_page_evidence=(
                    "同一弹窗仍在，但阶段由「选材料」前进到「待确认」——"
                    "下一次 next_action 报出的是 stamina_confirm 而不是它"
                ),
            )
        if decision.status == "waiting":
            raise StaminaExhausted("生命之叶购买按钮不可用")
        return self._action(
            "stamina_confirm",
            point=decision.point,
            source_page="行动力不足弹窗",
            reason="点确认购买生命之叶",
            in_page_evidence=(
                "购买完成后弹窗自身的锚点消失（stamina_popup 不再命中），"
                "画面回到弹窗底下的业务页"
            ),
        )

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        controls = observe_battle_controls(screen)
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        # 「这一局的战斗结束了」有两个地面：结算页，以及盖在它上面的
        # 「战斗级别奖励」弹窗 —— 两个都算。
        #
        # ⚠️ 奖励弹窗**必须**算数（2026-09-23 实跑踩坑）：点完「跳过」游戏会**直接**
        # 弹出奖励弹窗，弹窗把结算页压暗，于是 ``result_title`` 掉到 0.7103
        # （够不到 0.80 门槛）、``battle_visible`` 也变 False（跳过按钮已经没了）、
        # ``allowed_action`` 为 None ⇒ 监督的 ``recognized`` 五条判据**全假**
        # ⇒ 45 秒后以 ``battle_unrecognized`` 安全停止，而状态机里
        # ``LEVEL_REWARD → open-all-chests`` 那条分支一直没人来调。
        #
        # 原来写的是 ``result_title and level_reward_title is None``。那个排他是
        # **页面身份**的需求（``evidence/world_boss.py`` 靠 ``forbidden`` 把
        # world_boss.result 与 world_boss.level_reward 分开），不该被搬到
        # 「战斗结束没有」这个判据上 —— 这里要的恰恰是「两页都算结束」。
        result_visible = (
            self._locate(screen, "result_title") is not None
            or self._locate(screen, "level_reward_title") is not None
        )
        # 右上角「跳过」：既是「我在战斗画面」的锚点，也是把这一局推向结算的动作。
        # 交给监督去点（``allowed_action``），而不是在观察函数里直接点 ——
        # 监督有「点 4 次没进展就算失败」的有界重试账本，观察函数没有。
        skip = find_world_boss_skip(screen, self.templates.battle_skip)
        return BattleObservation(
            pre_battle_visible=self._locate(screen, "team_select_title") is not None,
            battle_visible=battle_scene_visible(screen) or skip is not None,
            result_visible=result_visible,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_evidence=f"布局={controls.value} 自动关图标=未使用(世界首领战默认自动)",
            auto_point=None,
            business_progress=(
                auto_state is AutoBattleState.AUTO
                and meaningful_change(previous_screen, screen)
            ),
            allowed_action=None if skip is None else ("skip-battle", skip.center),
            pre_battle_business_visible=self._locate(screen, "stamina_popup") is not None,
        )

    def _find_claimable_chest(
        self, screen: np.ndarray
    ) -> tuple[Optional[Match], str]:
        """找出主页两个槽位里**正发光**的那个，返回 ``(命中, 槽位标签)``。

        #1 排在前面：两档同时可领时先领 #1、下一帧再领 #2，从左到右，日志也好读。
        两个槽位用各自的模板与搜索区（外观不同、位置不同，理由见 ``WEEKLY_CHEST2_BOX``）。
        """
        chest = find_weekly_chest(screen, self.templates.weekly_chest)
        if chest is not None:
            return chest, "#1"
        chest = find_weekly_chest(
            screen,
            self.templates.weekly_chest2,
            region=WEEKLY_CHEST2_REGION,
            box=WEEKLY_CHEST2_BOX,
        )
        if chest is not None:
            return chest, "#2"
        return None, ""

    def _chest_scan_report(self, screen: np.ndarray) -> str:
        """主页上「没有可领宝箱」时的一句话结论，**只用于写日志**。

        ⚠️ 2026-09-26：这一步以前是**哑判** —— 没找到宝箱就什么都不说，直接往下判
        次数。2026-09-25 23:01 那次实跑就是这么收的场：日志里一句关于宝箱的话都没
        有，事后**根本分不清**「当时确实没有宝箱」和「判据漏了（本来该领没领）」。
        所以现在把两个槽位的**实测数字**写进日志：形状得分、亮度比、以及各自的门槛。

        数字的作用是让人一眼看出「差得远」还是「差一点」—— 后者意味着判据需要修，
        前者说明当时就是没有宝箱。⇒ **不许只写「没有宝箱」四个字**。
        """
        parts = []
        for slot, template, region, box in (
            ("#1", self.templates.weekly_chest, WEEKLY_CHEST_REGION, WEEKLY_CHEST_BOX),
            ("#2", self.templates.weekly_chest2, WEEKLY_CHEST2_REGION, WEEKLY_CHEST2_BOX),
        ):
            best = find_best_template(
                screen, template, region=region, reference_size=self._REFERENCE_SIZE
            )
            shape = best.score if best is not None else 0.0
            lit = weekly_chest_brightness_ratio(
                screen, self._REFERENCE_SIZE, box=box
            )
            parts.append(f"{slot} 形状{shape:.2f}/亮度比{lit:.2f}")
        return (
            "宝箱扫描=" + "，".join(parts)
            + f"（可领门槛：形状≥{WEEKLY_CHEST_THRESHOLD} 且 亮度比≥{WEEKLY_CHEST_BRIGHTNESS_RATIO}）"
            "⇒ 这一屏没有可领的宝箱"
        )

    def next_action(self, screen: np.ndarray) -> Optional[WorldBossAction]:
        stamina = self._handle_stamina(screen)
        if stamina is not None:
            return stamina

        page = self.observe_page(screen)

        if page is WorldBossState.LEVEL_REWARD:
            self.state = WorldBossState.LEVEL_REWARD
            # 「全部开启」点完按钮原地换成「确认」，**不换页** ⇒ 不声明 target_pages
            # （同页契约会永远验收通过）。此处实际由 Runner 的奖励弹窗流程接管
            # 那两次点击，状态机只负责报出「现在是奖励弹窗」。
            return self._action(
                "open-all-chests",
                source_page=state_label(WorldBossState.LEVEL_REWARD),
                reason="奖励弹窗「全部开启」",
                in_page_evidence=(
                    "按钮原地由「全部开启」换成「确认」——两下点击的坐标只差 2px，"
                    "所以 Runner 给它单独配了 5 秒短重试窗口"
                ),
            )

        if page is WorldBossState.RESULT:
            # 同一个「战斗结果」页，进来一次与从奖励弹窗回来一次要做的事不同：
            # 前者是「点确认弹奖励」，后者是「点确认回主页」。
            if self.state is WorldBossState.LEVEL_REWARD:
                self.state = WorldBossState.RESULT_CONFIRM
                return self._action(
                    "confirm-result",
                    source_page=state_label(WorldBossState.RESULT),
                    target_pages=(state_label(WorldBossState.HOME),),
                    reason="奖励已领完，回结算页点确认回主页",
                )
            self.state = WorldBossState.RESULT
            return self._action(
                "open-level-reward",
                source_page=state_label(WorldBossState.RESULT),
                target_pages=(state_label(WorldBossState.LEVEL_REWARD),),
                reason="结算页点确认弹出奖励",
            )

        if page is WorldBossState.TEAM_SELECT:
            self.state = WorldBossState.TEAM_SELECT
            return self._action(
                "build-team",
                source_page=state_label(WorldBossState.TEAM_SELECT),
                target_pages=(state_label(WorldBossState.TEAM_CONFIG),),
                reason="辅助队伍页点「组成战斗队伍」进配置队伍页",
            )

        if page is WorldBossState.TEAM_CONFIG:
            # 这一页要分两个阶段走，**不能进页就点战斗开始**：
            # ① 三队槽位还是空的 ⇒ 先点「自动配置」；
            # ② 槽位里已经有英雄了 ⇒ 才点「战斗开始」。
            #
            # 为什么只靠「槽位细节量」、不给 auto-configure 声明 target_pages：
            # 这一步**不换页**，目标页写本页的话，主循环的转场验收会永远通过
            # （confirmed_page 一直是「配置队伍」，落在 target_pages 里），
            # 「验收」就形同虚设 —— 分不出「点了没生效」与「点了生效了」。
            # 而**槽位被填上英雄**本身就是最直接的验收证据（画面状态）：
            # 还是空的 ⇒ next_action 仍返回 auto-configure，主循环按
            # ``_ACTION_RETRY_SECONDS``（45 秒）窗口有界重试；填满了就自然推进到
            # battle-start。这正是「按一次、验收一次」的落地方式。
            #
            # ⚠️ **判据必须落在「队伍真的被填上了」**，不能看按钮颜色 ——
            # 那颗按钮的橙/蓝与队伍配没配无关（2026-09-22 实跑踩坑，详见
            # ``TEAM_CONFIGURED_DETAIL`` 的注释）。
            self.state = WorldBossState.TEAM_CONFIG
            if not team_configured(screen):
                return self._action(
                    "auto-configure",
                    source_page=state_label(WorldBossState.TEAM_CONFIG),
                    reason="三队槽位为空=尚未自动配置",
                    in_page_evidence=(
                        "三队槽位被填上英雄（team_configured 由不成立变成成立）"
                    ),
                )
            return self._action(
                "battle-start",
                source_page=state_label(WorldBossState.TEAM_CONFIG),
                target_pages=(state_label(WorldBossState.BATTLE),),
                reason="三队槽位已填满=可以开战",
            )

        if page is WorldBossState.BATTLE:
            # 战斗画面 —— 这是「战斗开始」这个动作的**出口标志**（``target_pages`` 里
            # 写的「战斗中」），主循环 ``_transition_completed`` 靠它验收转场。
            #
            # ⚠️ **必须 ``_confirm_page``**：主循环是在**拍完这一帧、调 next_action
            # 之前**读 ``_confirmed_page`` 的，所以「我现在站在战斗中」这件事要被写下来，
            # 下一帧才能被读成「已到达目标页」。不写的话 target_pages 永远匹配不上
            # （``_confirmed_page`` 一直停在上一个动作的 source_page）⇒ 契约空转、
            # 45 秒后走「转场超时」。这正是 2026-09-22 之前 story 死过的那个坑。
            self.state = WorldBossState.BATTLE
            self._confirm_page(state_label(WorldBossState.BATTLE))
            return None

        if page is WorldBossState.HOME:
            self.state = WorldBossState.HOME
            # ⚠️ **宝箱要排在次数前面**（2026-09-23 用户明确要求：「先领宝箱，再判次数」，
            # 「领完宝箱之后才是一轮结束」）。用户的实拍截图正是「0/2 + 有宝箱可领」
            # 这个状态 —— 顺序反了会在次数用完那一刻直接收摊，宝箱就永远领不到。
            # 两个槽位**一帧只处理一个**：#1 优先，领完它下一帧再领 #2
            # （#1 领掉之后 #2 该发光还是照样发光，不会被漏掉）。
            chest, chest_slot = self._find_claimable_chest(screen)
            if chest is None and not self._chest_scan_note:
                # ⚠️ 不许哑判（2026-09-26 用户要求）：「没有宝箱」也是一条结论，
                # 必须带着实测数字进日志，理由见 ``_chest_scan_report``。
                self._chest_scan_note = self._chest_scan_report(screen)
            if chest is not None and not self._chest_given_up:
                # 同页动作（点完箱子不发光，页面不变）⇒ ``target_pages`` 留空。
                # 验收靠**页面内状态证据**：宝箱不再发光（同「自动配置」按钮橙→蓝）。
                # 点它多按一次没副作用，所以重试窗口用短尺子（见 ``_action_retry_seconds``）。
                return self._action(
                    "claim-weekly-chest",
                    source_page=state_label(WorldBossState.HOME),
                    point=chest.center,
                    reason=(
                        f"每周贡献度宝箱{chest_slot}发光"
                        f"（得分 {chest.score:.4f}）= 可领"
                    ),
                    in_page_evidence=(
                        "宝箱不再发光（weekly_chest 模板由命中变成不命中）"
                    ),
                )
            # ``_chest_given_up`` 为真 = 已经点够次数、箱子却还亮着 ⇒ **撒手**，
            # 落到下面的次数判断。不让它落进「点 4 次 → 回大厅 → 重新导航 → 再点 4 次」
            # 那个环 —— 那个环在 2026-09-25 的实跑里把整条路线拖死，而当时局内已经 0/2、
            # 本该直接收场。
            # ⚠️ 先看次数，再决定要不要点「选择队伍」（2026-09-23 实跑暴露的漏判）。
            # 少了这一步，主页在 0/2 时会一直报 open-team-select：
            # 灰按钮点不动 ⇒ 45 秒转场超时 ⇒ 重试 4 次 ⇒ 回大厅恢复 ⇒ 再点……
            # 表现就是「明明没次数了还在一直点」。
            #
            # 单帧就敢下结论，是因为 ``select_team_enabled`` 已经对「淡入变暗」免疫
            # （两道判据取或，见它的 docstring）—— 不必再叠一层「连续两帧」的门。
            # ⚠️ 把这个结论带进日志（2026-09-26）：停在「次数用完」时更要带上 ——
            # 那正是 2026-09-25 23:01 那次实跑的路径，日志里一句宝箱的话都没有，
            # 事后无从判断「没领」是没得领还是判据漏了。
            note, self._chest_scan_note = self._chest_scan_note, ""
            if not select_team_enabled(screen):
                raise AttemptsExhausted(
                    "主页「选择队伍」已变灰（今天次数已用完）"
                    + (f"；{note}" if note else "")
                )
            return self._action(
                "open-team-select",
                source_page=state_label(WorldBossState.HOME),
                target_pages=(state_label(WorldBossState.TEAM_SELECT),),
                reason="主页点「选择队伍」进辅助队伍页" + (f"；{note}" if note else ""),
            )

        # 战斗演出/过场：画面既不匹配任何已知页面，也不该乱点，等下一帧。
        if self.state is WorldBossState.BATTLE:
            return None
        # 认不出画面时清空对账依据：下一帧站在哪一页是未知的，拿旧页面去比对
        # 只会产生假契约（story 同样是清空后抛）。
        self._confirmed_page = ""
        raise UnrecognizedScreen(f"世界首领战画面[{state_label(self.state)}]未识别")

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self.stamina_replenished,
            self.auto_click_attempted,
            self._confirmed_page,
            self._stamina_material_clicked,
            self._chest_scan_note,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.stamina_replenished,
                self.auto_click_attempted,
                self._confirmed_page,
                self._stamina_material_clicked,
                self._chest_scan_note,
            ) = snapshot


WORLD_BOSS_ENTRY_PAGE = "worldboss_home"
"""世界首领战主页在导航链上的页面名（``navigation._RESUME_ENTRY_PAGES`` 登记的就是它）。"""





# 可停靠的**业务页** -> 它在导航链上的落点。
#
# 顺序无关紧要：``observe_page`` 的页面组合已做过全库排他扫描，一次最多认出一页。
#
# 三类**刻意不接**：
# - ``RESULT_CONFIRM``：它不是一个画面，是 ``next_action`` 由 ``state is LEVEL_REWARD``
#   转出来的内部记号（不在 ``_PAGE_STATES`` 里）⇒ 探针根本没有判据可用。
# - 行动力不足弹窗：点「确认购买」要**消耗生命之叶**（不可逆）。而且它盖在底页上，
#   回大厅的那一下 Back 会先把弹窗关掉，下一帧探针就在底页接管了 —— 效果一样、更安全。
# - 骑士团主页：**不是**本路线的业务页，是导航链的中间站，单独判（它落 ``entry``）。
_RESUMABLE_ENTRIES: dict[WorldBossState, Optional[str]] = {
    WorldBossState.HOME: WORLD_BOSS_ENTRY_PAGE,
    WorldBossState.TEAM_SELECT: None,
    WorldBossState.TEAM_CONFIG: None,
    WorldBossState.RESULT: None,
    WorldBossState.LEVEL_REWARD: None,
}


def detect_resume_point(
    machine: WorldBossStateMachine,
    screen: np.ndarray,
) -> Optional[ResumePoint]:
    """世界首领战开局接力：认出用户停在哪一页，认不出返回 None。

    判据就是 ``machine.observe_page`` —— **与运行期同源**，不另定阈值、不加新锚点，
    所以不存在「接力认得出、跑起来认不出」的第二种口径。停在大厅 / 别的路线上返回
    None，调用方照旧走「回大厅 → 按路线导航」（失败关闭，与加这个功能之前一致）。

    **局内排第一**：``observe_page`` 内部先判战斗画面（``battle_scene_visible`` 或
    右上角「跳过」），所以「已经在打的那一局」不会被某个残留锚点抢走。落点状态是
    ``BATTLE``，``WorldBossRunner`` 靠 ``resumed_from`` 收到它就跳过状态机、
    直接把这一局交给战斗监督（不按 Back、不重新导航，奖励不丢）。

    ⚠️ **``RESULT`` 页是有歧义的**：同一个「战斗结果」画面，进来一次与从奖励弹窗回来
    一次要做的事不同（``next_action`` 靠 ``state is LEVEL_REWARD`` 分岔），而接力只看
    到一帧、拿不到这个上下文。这里**保守取「奖励还没领」那一支**（拨 ``RESULT``），
    理由是三条：

    1. 两支点的是**同一个按钮**（``open-level-reward`` 与 ``confirm-result`` 都是
       (1730,1036)），所以猜错也不会误触别的功能、更不会点到危险按钮；
    2. 真停在结算页时，最可能的处境就是「刚打完、奖励还没领」；
    3. 万一猜反（奖励早已领完），游戏会直接回主页 ⇒ 下一帧 ``observe_page`` 认出
       ``HOME``，状态机自己拨正、继续往下跑。代价只是一次无效点击与一次「转场未完成」，
       **不丢奖励、不误点**。

    骑士团主页用 ``machine.at_knights_home`` 单独判：它是导航链的中间站，落 ``entry``
    让导航从那一级接着往下走（``navigation`` 里那条分支本来就写好了，此前没有调用方）。
    """
    page = machine.observe_page(screen)
    if page is WorldBossState.BATTLE:
        return ResumePoint("战斗中", WorldBossState.BATTLE)
    if page in _RESUMABLE_ENTRIES:
        return ResumePoint(state_label(page), page, _RESUMABLE_ENTRIES[page])
    if machine.at_knights_home(screen):
        return ResumePoint("骑士团主页", None, KNIGHTS_GUILD_HOME_PAGE)
    return None


class WorldBossRunner(ModeRunnerBase):
    """世界首领战固定循环 Runner（主循环协议见 ModeRunnerBase）。"""

    _MODE_LABEL = "世界首领战"
    # 转场契约机器强制（2026-09-24 打开；本路线是继 knights_donation 之后第二条）。
    #
    # 打开之前，这条路线是「动作看起来都带判据、但机器问不出来」的状态：换页动作带
    # ``target_pages``，同页动作的验收依据写在 ``next_action`` 的代码里、**没登记成字段**，
    # 于是漏写一个判据不会有任何报错。打开后每个动作在**发出去之前**逐个校验：
    # 缺 ``source_page``，或 ``target_pages`` 与 ``in_page_evidence`` 两者皆空，直接抛错；
    # **空跑同样会拦**（校验点在两个战斗入口之前，任何分支发出的动作都跑不掉）。
    #
    # ⚠️ 别把这个开关直接抄到别的老路线上：不同路线用的判据载体不一样
    # （``arena`` 用 ``source_state`` / ``target_states``，一个动作都不带
    # ``target_pages``），抄过去会每个动作都抛错。详见 docs/TRANSITION_CONTRACTS.md。
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        WorldBossState.HOME: 45,
        WorldBossState.TEAM_SELECT: 45,
        WorldBossState.TEAM_CONFIG: 45,
        WorldBossState.BATTLE: 120,
        WorldBossState.RESULT: 45,
        WorldBossState.LEVEL_REWARD: 45,
        WorldBossState.RESULT_CONFIRM: 45,
    }
    # 战斗入口与竞技场同构（``ArenaRunner`` 也是 ``_BATTLE_ENTRY_ACTION="battle-start"``
    # + ``_CLICK_BEFORE_BATTLE`` 默认 True）：
    # 主循环点「战斗开始」→ 立刻把这一局交给战斗监督，由监督一路跟到结算页。
    # 监督内部用 ``observe_battle`` 判「战斗已进入 / 已到结算」，不需要主循环
    # 再额外报一个「我看到战斗画面了」的动作 —— 那会把控制权在**战斗已开打之后**
    # 才交给监督，而监督要靠结算页才能正常退出，等于让它在一个看不到终点的
    # 画面上空转到超时（2026-09-22 实测）。
    _BATTLE_ENTRY_ACTION = "battle-start"
    _CLICK_BEFORE_BATTLE = True
    _SETTLED_BATTLE_STATE = None  # 战斗入口靠上面两条，不走「无动作直接移交」
    # 同一个配置队伍页上，打不起来的战斗**最多重来这么多次**，超过就安全停止。
    # 2 次足够覆盖真实场景（体力弹窗交还一次后，补叶、再点就能开打）。
    _MAX_BATTLE_ATTEMPTS = 2
    # 「全部开启」这一步的同名重试窗口（默认 ``_ACTION_RETRY_SECONDS`` 是 45 秒）。
    #
    # 奖励弹窗点完「全部开启」后按钮**原地**换成「确认」、页面**不换**（仍是
    # ``LEVEL_REWARD``），所以 ``next_action`` 会再返回一次同名动作。用默认的 45 秒
    # 窗口，就等于领奖时白等 45 秒 —— 2026-09-23 用户反馈的「干等 40 多秒」正是这一类。
    # 两下点击的坐标只差 2px（``open-all-chests`` (961,994) / ``confirm-level-reward``
    # (959,994)），第二下正好落在「确认」上，所以只要允许它早点再点一次就够了。
    _OPEN_ALL_CHESTS_RETRY_SECONDS = 5.0
    # 「每周贡献度宝箱」的同名重试窗口。宝箱是**同页动作**：点完它就不发光了、页面不变，
    # 所以「还亮着」= 这一下没生效，该早一点再点 —— 用默认 45 秒会把领宝箱拖成两三分钟。
    # 点一个宝箱多按几次没有副作用（不是购买/确认类按钮），窗口短一点是安全的。
    _WEEKLY_CHEST_RETRY_SECONDS = 3.0

    def __init__(
        self,
        machine: WorldBossStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(
                mode="world_boss",
                mode_label="世界首领战",
                # 「跳过」是**战斗内**动作，用的是 ``allowed_action`` 这条通道。
                # 默认那把尺子（3 秒重试 / 15 秒判失败）是给战前弹窗定的：真点下去
                # 一次没用就 15 秒收场，会把一场好端端的战斗判成失败。
                # 这里给足时间 —— 战斗本来就要几十秒，结算页才是真正的终点，
                # 跳过只是加速；即使跳过一直不生效，也要能自然等到结算页。
                allowed_action_retry_seconds=5,
                allowed_action_failure_seconds=90,
            ),
            now=self.now,
            sleep=sleep,
        )
        self._battle_attempts = 0
        # 「宝箱真的点了几次」，见 ``WEEKLY_CHEST_MAX_CLICKS`` 与 ``_after_action_click``。
        self._chest_clicks = 0

    def _state_label(self, state: WorldBossState) -> str:
        return state_label(state)

    def _after_action_click(self, action) -> None:
        """宝箱连点够次数还在发光 ⇒ 撒手，别再原地磨。

        ⚠️ 计数必须挂在这里而不是状态机里：状态机数的是「被问了几次 next_action」，
        而主循环在等重试窗口的那几秒里每帧都会问一次，两者差着好几倍
        （实测按状态机数 3 次，第 2 次点击后就撒手了）。
        """
        if getattr(action, "name", "") != "claim-weekly-chest":
            return
        self._chest_clicks += 1
        if self._chest_clicks >= WEEKLY_CHEST_MAX_CLICKS:
            self.machine._chest_given_up = True
            self.runtime.log(
                f"模式=世界首领战 宝箱=连点 {self._chest_clicks} 次仍在发光 "
                "-> 放弃领取，转去判次数（不再回大厅重来）"
            )

    def _action_retry_seconds(self, action_name: str) -> float:
        """给「全部开启」单独一把短尺子，别让领奖白等 45 秒。

        理由见 ``_OPEN_ALL_CHESTS_RETRY_SECONDS`` 的注释：这一步的「两下」是
        「全部开启」→「确认」，同一个页面、同一个坐标附近，默认 45 秒窗口纯属白等。
        """
        if action_name == "open-all-chests":
            return self._OPEN_ALL_CHESTS_RETRY_SECONDS
        if action_name == "claim-weekly-chest":
            return self._WEEKLY_CHEST_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def run(self, max_cycles: int | None = None) -> int:
        # 接力落在局内：先把这一局监督完再进主循环。空跑不碰战斗监督（干跑只观察）。
        # 用 getattr 而不是直接取属性：主循环协议里的状态机是鸭子类型
        # （测试里的 FakeMachine 只实现 preview/next_action），缺这个标记时按「没接力」处理。
        if (
            not self.runtime.dry_run
            and getattr(self.machine, "resumed_from", None) is WorldBossState.BATTLE
        ):
            self._resume_into_committed_battle()
        return super().run(max_cycles=max_cycles)

    def _resume_into_committed_battle(self) -> None:
        """接力直接落在局内：这一局不是本进程点开的，但已经打起来了。

        不能走 ``next_action`` 那条路：``BATTLE`` 分支只是「记下页面、返回 None」，
        那是给「刚点完战斗开始」用的；而开局就停在局内时**绝不能按 Back 回大厅** ——
        那是「已承诺战斗」的禁区，会把这一局白打。所以直接交给战斗监督等结算，
        跟点完「战斗开始」之后一样。

        ⚠️ 判据分不出「这是哪条路线的战斗」：``world_boss_battle_visible`` 里的
        ``battle_scene_visible`` 那一条在竞技场/远征/主线的战斗帧上同样成立
        （全库 17 张跨路线战斗夹具实测全部返回「战斗中」）。停在别的路线战斗里启动
        世界首领战，会先把这一局监督完再回大厅重新导航。这仍比老流程好：老流程在局内
        会一直卡在「未知画面等待唤醒」，直到返回大厅预算耗尽然后退出码 1。
        """
        self.runtime.log(
            "模式=世界首领战 开局=接力 页面=战斗中 "
            "动作=交由战斗监督等待结算 状态=不按Back不重新导航"
        )
        self._run_committed_battle(cycle=self.machine.completed_cycles + 1)

    def _run_committed_battle(self, *, cycle: int) -> BattleOutcome:
        """把已确认开打的这一局交给战斗监督，直到结算。

        返回 ``BattleOutcome`` 供主循环判断：``PRE_BATTLE_BUSINESS`` 表示战斗
        **没打起来**（又冒出战前业务弹窗，通常是体力不足），主循环会走有界重试。
        """
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = WorldBossState.TEAM_CONFIG
            return outcome
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"世界首领战战斗出现意外结果：{outcome.value}")
        self.machine.state = WorldBossState.RESULT
        return outcome

    def _on_battle_handoff_failed(self, action: WorldBossAction, screen) -> bool:
        """「战斗开始」点了却没进战斗 ⇒ 有界重试，超限则安全停止。

        与竞技场 / 主线一致：打不起来**不是**「页面没认出来」，而是一个明确的
        业务失败 —— 记日志、留诊断、正常停止，绝不无限重交。
        """
        self._battle_attempts += 1
        if self._battle_attempts <= self._MAX_BATTLE_ATTEMPTS:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 战斗未开启 "
                f"尝试={self._battle_attempts}/{self._MAX_BATTLE_ATTEMPTS} "
                "判断依据=点「战斗开始」后战斗画面未出现 "
                "动作=回配置队伍页重新确认队伍"
            )
            # 回到配置队伍页重新走一遍（两阶段判定会再验一次按钮颜色）。
            self.machine.state = WorldBossState.TEAM_CONFIG
            self.machine._confirmed_page = ""
            return False
        diagnostic = self.runtime.save_diagnostic("battle_start_never_entered", screen)
        self._save_failure_diagnostic(
            diagnostic,
            screen,
            action=action,
            attempt=self._battle_attempts,
            conclusion="多次点击战斗开始后战斗画面始终未出现",
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} 停止=战斗始终未开启 "
            f"尝试={self._battle_attempts}次 现场={diagnostic}"
        )
        raise RuntimeError(
            f"点「战斗开始」{self._battle_attempts} 次仍未进入战斗；"
            f"已安全停止并保存诊断 {diagnostic}"
        )

    def _on_battle_started(self) -> None:
        """这一局真的打起来了 ⇒ 重试账本清零（下一局重新计数）。"""
        self._battle_attempts = 0

    def _on_action_exhausted(self, action: WorldBossAction, screen) -> bool:
        if action.name == "stamina_confirm":
            self.resource_exhausted = True
            self.runtime.log("模式=世界首领战 停止=生命之叶确认多次未生效")
            return True
        return False
