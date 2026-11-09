from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep as default_sleep
from typing import Callable, TYPE_CHECKING

import cv2
import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template

if TYPE_CHECKING:
    from auto_game_unified.core.runtime import Runtime


@dataclass(frozen=True)
class NetworkReconnectTemplates:
    """断线弹窗的**文案**锚点（这层弹窗的文案有两种画法，各存一张）。

    ⚠️ **别当成「新旧版本」**：没有证据表明游戏改过版，「8 月先出甲/后出乙」只是当年
    提交的顺序，不是版本先后。已核实的事实是 —— 文案有两种画法、按钮也有两种画法，
    两者**互不绑定**，四种交叉组合都可能出现（证据见 ``find_network_retry``）。

    判定只用文案。按钮图（``network_retry.png`` / ``network_disconnected_retry.png``）
    曾经也是判定条件，2026-10-04 整层弹窗就是栽在「文案与按钮必须配对」上。
    两张按钮图仍留在 ``templates/global/`` 下存档，但不再读进内存、也不参与判定。

    ``retry_button`` 是后来（2026-11-03）加的**定位用**锚点，只回答「点哪」：
    PC 上这层弹窗是全屏横带，屏幕中心落在文案与按钮之间的空白，点了没反应。
    它**不参与判定** —— 认不认这层弹窗仍然只看上面两张文案图；模板缺失（模拟器）
    时回落原来的「点屏幕中心」，行为与历史完全一致。
    """

    message: np.ndarray
    message_alt: np.ndarray | None = None
    retry_button: np.ndarray | None = None
    # 同一句文案的**第二种尺寸**（「网络连接异常，请重新连接。」，2026-11-05 00:37 真机，
    # PC 主线战斗中掉线）。**不是第三种文案** —— 逐字一样，只是画得小一号。
    #
    # 量化（拿 2026-11-01 那张 PC 模板打这一帧）：原尺寸 0.6882（阈 0.88）；
    # 把它缩到 **0.97** 再打 ⇒ **0.9335** ⇒ 差异是纯缩放，不是换了句话。
    # 字高 26px vs 25px、字宽 361 vs 346（≈96%）：模板是逐像素比的，
    # 差 4% 累积到 12 个字上就有 15px 位移，细笔画直接被拖垮。
    #
    # 为什么不走 `SCALE_FALLBACK_ANCHORS` 扫尺寸：那份白名单有护栏要求锚点必须
    # 出现在「导航与竞技场证据」里（`test_navigation.py`），全局弹窗锚点进不去
    # —— 2026-11-04 迷宫 `labyrinth_entry` 已经在这条护栏上撞过两次，别再撞。
    # 补一张同句、小一号的 PC 图最省事：模拟器侧文件不存在 ⇒ `None` ⇒
    # 判定集合与改动前**逐字节一致**。
    message_reconnect: np.ndarray | None = None


@dataclass(frozen=True)
class IntimacyLevelUpTemplates:
    title: np.ndarray
    dismiss: np.ndarray


@dataclass(frozen=True)
class FriendshipPointsTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class FriendRequestTemplates:
    title: np.ndarray
    cancel: np.ndarray


@dataclass(frozen=True)
class KnightsSigninTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class GiftSupportTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class KnightsWeeklyRewardTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class WorldBossSupportRewardTemplates:
    """「世界首领辅助队伍奖励」弹窗（标题 + 点击关闭，与骑士团那三个同形）。

    ⚠️ 两个锚点**分工不同**，别照抄成「两个判据」：
    - ``title``（「世界首领辅助队伍奖励」）= **排他锚点**，跨页最高只有 0.3320；
    - ``close``（底部「点击关闭」那行灰字）= **点击点**。它单独**完全不排他**
      —— 全库扫下来 `reward_popup` 0.8993、`popup_spring` / `popup_penguin_*`
      都在 0.8991（同一种「底部居中 点击关闭」灰字控件），所以必须靠标题兜住。

    ⚠️ ``close`` 只能用**原样比较**（``MATCH_MODE_RAW``）：那行灰字峰值亮度只有
    **171**，低于白掩膜的 200 下界 —— 走 ``MATCH_MODE_WHITE_MASK`` 会被整片抹成 0，
    常量模板在 CCOEFF 下退化成「处处 1.0000」（实测世界首领主页十几张帧全变 1.0）。
    """

    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class ArenaRankRewardTemplates:
    """「竞技场段位升级奖励」弹窗（标题 + 点击关闭，与骑士团那四个同形）。

    它是**段位提升弹窗的下一层**：点掉「段位提升」之后马上弹出来，
    首次升至各段位时才出现（一次性），所以平时跑不到、也就一直没被发现。

    ``title``（「升级奖励」）= 排他锚点（负样本最高 0.4675）；
    ``close``（底部「点击关闭」）= 点击点，单独**完全不排他**
    （同一行灰字在 `reward_popup.png` 一类领奖弹窗上最高 0.9852），必须靠标题兜住。
    """

    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class BattleRecordTemplates:
    """「战斗记录」弹窗（竞技场防守战绩 / 段位变动通知）。

    标题「战斗记录」下面写着「根据防御队的战斗结果和排名变动，段位变更如下。」，
    中间是段位从 Ⅱ 掉到 Ⅲ 的图示，底部是通用的「点击关闭」。

    ``title`` = 排他锚点（2026-10-30 实测：真帧 1.0000，其余横屏帧最高 0.2388）；
    ``close`` = 点击点，**复用「段位升级奖励」那张**（同一行灰字，不另存第二份）。
    ⚠️ close 单独完全不排他，必须靠标题兜住 —— 与 ``ArenaRankRewardTemplates`` 同一条规矩。

    它和「段位提升」「升级奖励」是**三件不同的事**，别合并：
    那两层是打完一局之后的流程内弹窗（点确认 → 段位提升 → 升级奖励），
    这一层是**进竞技场时就弹**的防守战报，业务上跟「刚才那局」没关系。
    """

    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class WeeklyRankStartTemplates:
    """「新的每周排名开始！」弹窗（每周结算后的段位重置通知）。

    2026-11-09 08:52 模拟器每日任务：点进竞技场后弹出这一层，盖住对手列表；
    它不在任何弹窗清单里 ⇒ 导航「画面已静止但仍认不出是哪一页」⇒ 只等 106 秒
    ⇒ 报「导航转场 竞技场模式选择 → arena_ready 失败」。

    与「战斗记录」「段位升级奖励」是三件不同的事：那两层分别是防守战报和
    打完一局后的奖励，这一层是**每周结算**、进竞技场时一次性弹出的通知。

    ``title`` = 排他锚点（紧裁「新的每周排名开始！」白字 378x51；真帧 1.0000，
    全库 440 张横屏夹具最高 0.3672）；``close`` = 点击点，复用「段位升级奖励」
    那张通用「点击关闭」灰字图（同一控件只存一份，本层实测 0.9847）。
    ⚠️ close 单独不排他，必须靠标题兜住；这一层的关闭按钮比别层**低**
    （中心约 (961, 936)），所以两块 ROI 都要自己定，照抄别层会两边切掉。
    """

    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class WeeklyRankSelectTemplates:
    """「每周排名选择奖励」弹窗（每周结算后二选一：天空石 / 神秘奖牌）。

    2026-11-09 11:41 模拟器每日任务：竞技场在「模式选择 → 竞技场」这一段被它挡住。
    它与第 24 类「新的每周排名开始！」是**前后脚的两道通知**：先出通知层，
    关掉后再出这一层让你选奖励。11:41 那轮已经关掉通知层，卡在这一层
    ⇒ 画面静止仍认不出 ⇒ 30 秒后报「导航转场 竞技场模式选择 → arena_ready 失败」。

    这一层与其它弹窗的根本区别：**点一下关不掉**。必须先选中一个奖励，
    再点「领取选择的奖励」。所以它不返回固定点击点，而是「当前该点哪一个」：

    - 领取按钮**文字还是灰的** ⇒ 还没选中 ⇒ 点 ``sky_stone``
      （用户 2026-11-09 拍板：默认选钻石，即左侧 800 天空石）。
    - 领取按钮**文字变白** ⇒ 已选中 ⇒ 点 ``confirm`` 领取。

    ``title`` = 排他锚点（紧裁「每周排名选择奖励」白字 366x52；真帧 1.0000，
    442 张夹具在同一 ROI 口径下最高 0.5267）；``sky_stone`` = 左侧天空石卡片整块
    127x127（真帧 1.0000，反例最高 0.7357）；``confirm`` = 底部按钮文字 213x38
    （真帧 1.0000，反例最高 0.3730）。

    ⚠️ 三张图都裁自**模拟器**现场帧。PC 端会压低文字类锚点（见
    ``PC_TEMPLATE_MIGRATION.md``），真要在 PC 上跑这条时，先量一次分数再决定是否补
    ``navigation/pc/`` 同名图。
    """

    title: np.ndarray
    sky_stone: np.ndarray
    confirm: np.ndarray


@dataclass(frozen=True)
class KnightsGrowthRankTemplates:
    """「骑士团成长Rank提升」弹窗（标题 + 点击关闭，与骑士团那四个同形）。

    标题「骑士团成长Rank提升」，下面一行「已达到骑士团成长Rank.NN。」，
    中间是段位徽章，底部通用「点击关闭」。

    ``title`` = 排他锚点（2026-10-30 实测：真帧 1.0000，全库 559 张横屏帧里
    次高只有 **0.3210**）；``close`` = 点击点，单独不排他（同一行灰字）。

    ⚠️ 它与「签到 / 领取支援 / 每周点数奖励」是**同一族的第 5 个**，都盖在骑士团相关页上。
    这一层只在**骑士团成长等级提升**时出现（低频，但撞上就必然卡住整条路线）。
    """

    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class PetGiftTemplates:
    """宠物小屋礼物角标（**单锚点**：整个角标就是要点的目标，没有标题/关闭点）。"""

    badge: np.ndarray


@dataclass(frozen=True)
class WebNetworkErrorTemplates:
    """游戏内网页（WebView）报「网络错误」时的两个锚点。

    ⚠️ 这一层**必须双锚点**，而且两个锚点的分工与别的弹窗**反着来**，别照抄：

    - ``message``（那条黑底白字的长条）= **排他锚点**。它出现 = 网页这条路出事了。
    - ``close``（网页容器右上角那颗圆钮 X）= **点击点**。
      ⚠️ 它是**网页本来就有的控件** —— 每一张网页帧上都在（实测正常网页帧上
      0.9739~0.9970），所以它**单独不能当判据**，只能当「点哪儿」。

    与 ``NetworkReconnectTemplates`` 的区别：那片断线弹窗是**模态**的，点画面任何位置都
    能消掉，所以那里「主锚点排他即可、命中点屏幕中央」；而这条长条**只有那个 X 能消**，
    点别处没用 —— 所以它的第二个锚点不是「多余的配对」，而是**必须存在的点击目标**。
    """

    message: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class UncontrollableTemplates:
    """「无法控制」剧情提示弹窗（标题居中 + 底部「✕ 点击关闭」）。

    2026-11-06 主线真机：Episode 3 第 10 章关卡入口页弹出这个剧情说明，**整页被盖住**
    ⇒ 认不出「关卡入口」⇒ 45 秒超时 ⇒ 主线整条失败。
    它是标准的**居中模态弹窗**（不像「骑士团活动」是整屏页面），放全局守卫是安全的。

    ⚠️ 模板只有 PC 版 ⇒ 模拟器加载成 None ⇒ 整段跳过，行为不变。
    """

    title: np.ndarray | None
    close: np.ndarray | None


@dataclass(frozen=True)
class TutorialUnlockTemplates:
    """「轻触后解锁【XX】」教学遮罩（2026-11-06 主线 Episode 4 第 11 关）。

    这层不是普通提示框：它是**全屏模态教学层**，把底下「准备战斗」和 ESC 一起吞掉。
    12:29 真机连点 4 次「准备战斗」不转场、收尾连按 2 次 ESC 页面不动 ⇒ 主线 ✗
    + 每日任务「已中止：月光剧场 之前无法回到首页」，后面 8 条路线一条都没跑。

    判据只裁黑框**左半**（蓝色左框角 +「轻触后解锁」），刻意不含角色名 —— 那是会变
    的内容。4 张正例 0.9999~1.0000，全库 360 张反例最高 0.4323（阈 0.82）。
    点击点两候选：右上角「跳过教学 ✕」（明确退出教学、不触发角色解锁）；找不到
    再点黑框箭头指向的高亮图标（教学本身要求轻触的目标）。两者都定位不到就
    **不动手**，不猜坐标（见 ``web_network_error`` 那颗 ✕ 的教训）。

    ⚠️ 三张图都只在 ``templates/global/pc/`` 下 ⇒ 模拟器加载成 None ⇒ 整段跳过。
    """

    title: np.ndarray | None
    skip: np.ndarray | None
    highlight: np.ndarray | None
    # 「跳过教学」那一整块里的 **✕**：点击点以它为准（用户 2026-11-06 明确
    # 「要点那个叉叉才行」，点文字只是展开/收起说明）。缺失时退回 skip 中心。
    confirm: np.ndarray | None = None


@dataclass(frozen=True)
class TutorialSkipTemplates:
    """大厅右上角常驻的「跳过教学 ✕」（新手账号才有，老账号没有）。

    2026-11-06 22:27 真机：这台 PC 客户端是**新手账号**，大厅右上角多了一整块
    「跳过教学 ✕」，把原来的**快捷菜单蓝四格顶掉了** ⇒ 导航层「打开快捷菜单」
    的锚点找不到，多条路线在这台机器上反复失败。模拟器老账号从来没有这个东西，
    所以这是移植到新账号后才暴露的一类。

    ⚠️ 点击点必须是文字右边那个 **✕**，不是「跳过教学」四个字（用户 2026-11-06
    明确要求：「你要点击跳过教学那个字的旁边有一个叉叉，要点那个叉叉才行」）——
    点文字只是展开/收起说明，点 ✕ 才真正结束教学、这一整块才消失。

    ⚠️ 两张图都只在 ``templates/global/pc/`` 下 ⇒ 模拟器加载成 None ⇒ 整段跳过。
    """

    button: np.ndarray | None
    confirm: np.ndarray | None


@dataclass(frozen=True)
class KnightsActivityTemplates:
    """「骑士团活动」页：左上标题 + 底部「✕ 点击关闭」。

    2026-11-05 批量真机：骑士团捐赠跑完后页面停在**每周任务**标签，收尾连按 2 次 ESC
    毫无反应（这一页是整屏页面，不是弹窗，PC 客户端不响应 ESC）⇒ 报「回首页失败」⇒
    **整条每日任务链中止，后面四条一条都没跑**。

    ⚠️ 模板只有 PC 版（``templates/global/pc/``）—— 模拟器加载不到 ⇒ 两个字段都是
    None ⇒ 这条整段跳过，模拟器行为一键不变。模拟器上 ESC 本来就能退这一页。
    """

    title: np.ndarray | None
    close: np.ndarray | None


@dataclass(frozen=True)
class DateChangeTemplates:
    """「日期变更，将前往大厅。」弹窗：标题排他 + 底部「点击关闭」定位。

    ⚠️ 模板目前只有 PC 版（``templates/global/pc/``）—— 模拟器口径加载不到 ⇒ 两个字段
    都是 ``None`` ⇒ 这条弹窗在模拟器上**整段跳过**，行为与历史完全一致（模拟器那条
    从来没报过这两个弹窗，不改它反而是对的）。
    """

    title: np.ndarray | None
    close: np.ndarray | None


@dataclass(frozen=True)
class LoginRewardTemplates:
    """「获得登录奖励」弹窗：标题排他 + 底部「点击关闭」定位。字段口径同上。"""

    title: np.ndarray | None
    close: np.ndarray | None

_REFERENCE_SIZE = (1982, 1132)

# 同一层弹窗的**点击预算**：点满这么多次仍不消失 ⇒ 判定熔断（存诊断 + 抛错）。
# 对所有全局弹窗通吃，不按弹窗类型区分（见 ``Epic7GlobalPopupGuard.__call__``）。
#
# ⚠️⚠️ 这是本模块**唯一**允许出现「4」的地方 —— 下方 9 条失败文案、
# ``__call__`` 的两处判断、``tests/test_global_popups.py`` 的断言全部从这里取值。
# **别在别处再写死这个数字。** 历史教训：2026-08-21 把它从 2 调到 4 的时候，
# README 那份副本没跟上，一路错到 2026-10-04 才被用户发现。
# 实测节奏（探针 ``runtime_logs/_probe_click_budget.py``）：1/4/7/10 秒各点一次，
# 25.0 秒熔断。改回 2 次只省 6 秒，而 adb 侧「命令送达但界面没消化」至今无法
# 自动检测（见 ``topics/click_channel.md``），多点两次的容错值得留着。
_MAX_POPUP_CLICKS = 4

_MESSAGE_REGION = (700, 450, 600, 180)
# 断线弹窗文案的门槛：沿用原先双锚点时那个 0.88，没有重调。
# 排他余量见 ``find_network_retry`` 的 docstring（跨页最高 0.5543，余量 0.33）。
_NETWORK_THRESHOLD = 0.88
# 「点击重试 ∨」按钮：**只用来定位点击点，不参与判定**。
#
# 判定仍然只看文案（``_NETWORK_THRESHOLD``），这里解决的是另一个问题 ——
# 2026-11-03 PC 实测：这层弹窗在 PC 上是**全屏横带**，文案落在 y≈521，
# 而底下的「点击重试 ∨」在 y≈702~733；旧写法「命中即点屏幕中心」正好点在
# 文案和按钮之间的空白处 ⇒ 连点 4~8 次纹丝不动（竞技场 10:23 / 18:35、
# 主线 15:37 都死在这）。
#
# ⚠️ 别把它读成「按钮参与判定」：文案与按钮的四种交叉组合历史上都出现过
# （见 ``find_network_retry`` 的 docstring），把两者绑成一对就是 2026-10-04
# 那次事故的老路。这里的顺序是**先认文案、再找按钮**，按钮只决定「点哪」。
#
# 模板是三张 PC 真机帧上交出来的同一块（中心 (960,731)，跨帧 0.9434~1.0000）；
# 全库 364 张夹具里没有它之外的 ≥0.80 命中（唯一那张是断线页正例本身）。
_NETWORK_RETRY_BUTTON_THRESHOLD = 0.88
_INTIMACY_TITLE_REGION = (800, 220, 700, 180)
_INTIMACY_DISMISS_REGION = (850, 780, 650, 250)
_FRIENDSHIP_TITLE_REGION = (600, 150, 800, 180)
_FRIENDSHIP_CLOSE_REGION = (750, 840, 450, 190)
_FRIENDSHIP_ANCHOR_THRESHOLD = 0.55
_FRIEND_REQUEST_TITLE_REGION = (650, 240, 700, 160)
_FRIEND_REQUEST_CANCEL_REGION = (550, 720, 500, 230)
# 骑士团签到弹窗：标题在面板上部，「点击关闭」在面板下部（面板会盖住骑士团主页）。
_KNIGHTS_SIGNIN_TITLE_REGION = (700, 260, 600, 90)
_KNIGHTS_SIGNIN_CLOSE_REGION = (860, 810, 280, 70)
# ⚠️ 阈值 0.80 是按「标题锚点」定的，不是按关闭点 —— 关闭点单独不可靠：
# 全库 187 张实测「点击关闭」这四个字在 hero 的 imprint_sss_warning_popup 上能拿
# **0.9986**、imprint_result_popup 0.9908、reward_popup 0.9846、expedition
# victory_popup 0.9355 —— 因为它们用的是同一种「底部居中点击关闭/点击继续」灰字控件。
# 而标题锚点跨页最高只有 **0.3278**（hero/reward_popup），离 0.80 有 0.47 余量。
# ⇒ 必须**双锚点同时命中**才算（见 find_knights_signin_close），
#   只用关闭点会在别的弹窗上乱点。这与项目记忆里「arena/expedition 共用 confirm 锚点」
#   是同一类坑。扫描脚本：runtime_logs/_knights_signin_probe.py。
_KNIGHTS_SIGNIN_THRESHOLD = 0.80
# 「领取支援物品」弹窗（进骑士团时团员赠送的支援资源到账，会盖住骑士团主页）：
# 标题在面板上部（与签到弹窗同一 ROI），「点击关闭」在面板下部。
# 与签到弹窗同理：标题锚点排他、关闭点不排他（hero/reward_popup 上单独 0.9996），
# 必须**双锚点同时命中**。实测弹窗帧 title=1.0000 / close=1.0000；
# 跨页标题最高只有 0.3240，签到弹窗在这张图上标题仅 0.3220 ⇒ 两者互不误触。
_GIFT_SUPPORT_TITLE_REGION = (700, 260, 600, 90)
_GIFT_SUPPORT_CLOSE_REGION = (860, 810, 300, 80)
_GIFT_SUPPORT_THRESHOLD = 0.80
# 「获得每周骑士团点数奖励」弹窗（**每周一结算**时弹出，盖在骑士团主页上）：
# 标题「获得每周骑士团点数奖励」在面板上部（与签到/支援弹窗同一 ROI），
# 「点击关闭」在面板下部。与那两个弹窗同理：标题锚点排他、关闭点单独不排他
# （hero/reward_popup 上「点击关闭」能拿 0.9996），必须**双锚点同时命中**。
# 实测弹窗帧 title=1.0000 / close=1.0000；跨页标题最高只有 **0.3376**
# （恰在签到弹窗上 0.3376、其它都 <0.27），离 0.80 余量极大，互不误触。
# 素材来自 2026-09-28 实跑骑士团捐赠时的原始诊断帧
#（tests/fixtures/epic7_world_boss/knights_weekly_reward_popup.png）。
_KNIGHTS_WEEKLY_REWARD_TITLE_REGION = (700, 260, 600, 90)
_KNIGHTS_WEEKLY_REWARD_CLOSE_REGION = (860, 810, 300, 80)
_KNIGHTS_WEEKLY_REWARD_THRESHOLD = 0.80
# 「世界首领辅助队伍奖励」弹窗（2026-10-19 接）：同僚团员借你的辅助队伍出战并拿到
# 奖励后，**进世界首领战主页时**弹出，盖在主页上（底页被压暗 ⇒ `lobby_worldboss_select_team`
# 认不出来 ⇒ `observe()` 报 unknown）。那天就在它身上失败了：
#   08:11:10 进入世界首领战 → 08:11:12 点击验收=生效 从=骑士团主页 到=无效画面
#   → 08:11:17 unknown_screen_unresolved（诊断帧就是这条弹窗）→ 08:12:44 转场失败。
# 判据与骑士团那三个**同形同理由**：标题排他 + 「点击关闭」当点击点，双锚点同时命中。
# 实测（`runtime_logs/_scratch_wb_popup.py` 的做法，全库 280 张）：
#   | 锚点 | 弹窗帧 | 跨页最高 |
#   | 标题 | 1.0000 | **0.3320**（knights_signin_popup） |
#   | 关闭 | 1.0000 | 0.8993（reward_popup）⇒ 不排他，只能当点击点 |
# 标题区域里非文字像素均值只有 **6.3**（弹窗把底页压到近乎全黑）⇒ 原样比较等价于
# 「只看白字轮廓」，不必上白掩膜。
_WORLDBOSS_SUPPORT_TITLE_REGION = (700, 262, 520, 80)
_WORLDBOSS_SUPPORT_CLOSE_REGION = (860, 770, 300, 90)
_WORLDBOSS_SUPPORT_THRESHOLD = 0.80
# 「竞技场段位升级奖励」：**段位提升弹窗的下一层**（2026-10-20 立）。
#
# 链条：战斗结果 → 点「确认」→「段位提升」（竞技场 `结果确认中` 认的就是它）→ 点掉它
# → 游戏**紧接着**弹「升级奖励」（「已升级为优胜者Ⅳ段位且获得以下奖励。段位升级奖励
# 只会在首次升至各段位时发放1次」）。这一层把底页压暗，而竞技场**一条判据都认不出它**
# ⇒ 2026-10-20 08:02 那次转场一路等到 45 秒上限，整条竞技场记 ✗（当天唯一失败的路线）。
#
# ⚠️ 为什么是全局弹窗而不是竞技场里新加一页：它是**模态通知窗**，点画面任意位置就能关掉，
# 与骑士团那三个「标题 + 点击关闭」弹窗同形；放在守卫里，任何路线撞上都能消掉
# （`runtime.capture` 每帧都会过守卫，竞技场的等待转场循环因此也能自愈）。
#
# ⚠️ 必须双锚点：「点击关闭」是游戏里通用的一条灰字，全库实测最像的有
# **0.9852**（`reward_popup.png` / `knights_weekly_reward_popup.png` /
# `popup_penguin_before_close.png` 等都属于同一行控件），单锚点必然乱点。
# 标题「升级奖励」是排他的（负样本最高 0.4675，还是撞在 `support_confirm.png` 上）。
#
# 全库 305 张 1982x1132 横屏帧实测（`runtime_logs/_probe_arena_rank_reward.py`）：
#   正例（20261020_080245 那张失败帧）title 1.0000 / close 1.0000；
#   **双锚点取 min 后的负样本最高 0.2993**（`battle_guide_warning_live_20260815.png`）
#   ⇒ 阈值 0.88：地板余量 +0.12、天花板余量 +0.58。
_ARENA_RANK_REWARD_TITLE_REGION = (820, 285, 360, 80)
_ARENA_RANK_REWARD_CLOSE_REGION = (860, 795, 280, 110)
_ARENA_RANK_REWARD_THRESHOLD = 0.88
# 「战斗记录」弹窗（竞技场防守战绩 / 段位变动通知，2026-10-30 立）。
#
# 现场：18:27 从大厅点「进入竞技场」，游戏弹出这一层盖住对手列表；它不在任何判据里
# ⇒ 导航判「画面已静止但仍认不出是哪一页」⇒ 只等（"来源已离开、目标未到"）⇒
# **129 秒**后报「导航转场 竞技场模式选择 → arena_ready 失败」。
# 紧接着回家又栽在快捷菜单上（那是另一处，见 ``home_return.return_home_v2``），
# 结果整轮每日任务只跑完竞技场一条就中止，后面 5 条路线一条没跑。
#
# 为什么放全局守卫：它是**进竞技场时必然出现**的模态通知（只要期间有防守战绩/段位变动），
# 跟「打完之后」的段位提升不是一回事；放进守卫后任何路线撞上都能消掉。
#
# 标题区域比「升级奖励」那套**高 59px**：这一层的标题在 y 242~285，而那层在 y 285 以下，
# 两者用同一块区域会互相切掉。close 区域直接沿用那套（同一行灰字、同一高度）。
_BATTLE_RECORD_TITLE_REGION = (820, 226, 360, 80)
_BATTLE_RECORD_CLOSE_REGION = _ARENA_RANK_REWARD_CLOSE_REGION
_BATTLE_RECORD_THRESHOLD = 0.88
# 「新的每周排名开始！」弹窗（2026-11-09 立，第 24 类）。
# 现场：08:52 模拟器每日任务的竞技场 ✗。标题在 y 206~257，比「战斗记录」更高；
# 关闭那行灰字在 y ~900~945，比段位奖励那层（y 795~905）低 ⇒ 两块 ROI 都要自己定。
_WEEKLY_RANK_START_TITLE_REGION = (740, 180, 500, 120)
_WEEKLY_RANK_START_CLOSE_REGION = (820, 850, 340, 130)
_WEEKLY_RANK_START_THRESHOLD = 0.88
# 「每周排名选择奖励」弹窗（2026-11-09 立，第 25 类）。
# 现场：11:41 模拟器每日任务，紧跟在上一类通知之后；标题在 y ~307、两张卡片在
# y 575~702、领取按钮文字在 y ~837。三块 ROI 都按这一层自己定。
_WEEKLY_RANK_SELECT_TITLE_REGION = (740, 275, 460, 110)
_WEEKLY_RANK_SELECT_CARD_REGION = (735, 535, 210, 200)
_WEEKLY_RANK_SELECT_CONFIRM_REGION = (820, 800, 300, 100)
# 亮度判据的区域：正好框住「领取选择的奖励」这六个字（不掺按钮底色）。
_WEEKLY_RANK_SELECT_CONFIRM_TEXT_REGION = (853, 831, 213, 38)
_WEEKLY_RANK_SELECT_THRESHOLD = 0.88
# 未选中时文字是灰的：2026-11-09 11:41 现场帧实测该区域 p99 亮度 153、
# 白像素占比 0.0000；选中后文字转白。阈值取 0.01 = 「只要出现成片白字就算亮」。
# ⚠️ 手上没有「已选中」的真机帧，这条是灰态实测 + 亮态推断；真机跑通后按实测值订正。
_WEEKLY_RANK_SELECT_CONFIRM_LIT_RATIO = 0.01
_WEEKLY_RANK_SELECT_LUMA = 170
_WEEKLY_RANK_SELECT_SPREAD = 60
# 「骑士团成长Rank提升」弹窗（2026-10-30 立，骑士团那一族的第 5 个）。
#
# 现场：19:48 世界首领战从大厅打开快捷菜单 → 点「骑士团」→ 弹出这一层盖住骑士团主页
# ⇒ 导航判「画面已静止但仍认不出是哪一页」⇒ 只等 2 分钟 ⇒
# 「导航转场 快捷菜单 → knights_home 失败」，那条路线整条记 ✗。
#
# 它不是新东西：全库复扫过阈的 5 张里，有一张是 **2026-10-08 骑士团捐赠**那次
# 的 unknown 帧 —— 说明这层弹窗早就出现过，只是当时没登记，撞一次记一次 ✗。
#
# 区域比别的弹窗**宽得多**（标题是「骑士团成长Rank提升」10 个字 + 英文字母，432x54），
# 关闭点也**更低**（y≈1033，而段位奖励那层在 y≈879）—— 因为这一层弹窗更高。
_KNIGHTS_GROWTH_TITLE_REGION = (720, 160, 500, 90)
_KNIGHTS_GROWTH_CLOSE_REGION = (880, 995, 220, 90)
_KNIGHTS_GROWTH_THRESHOLD = 0.88
# 「宠物小屋礼物角标」：**不是盖住页面的模态弹窗**，而是挂在**快捷菜单页**上的一个小角标
# （就是回家流程点那颗「啤酒杯 → 酒馆」的那一页）。宠物送礼时，宠物小屋图标旁边会挂出
# 一个「紫金礼盒 + 对话气泡」的角标；**点它一下才会领取礼物、角标才消失**，
# 不点就一直挂着，每天回家都会看见。
#
# ⚠️ 这条是**单锚点**（与上面几个弹窗不同）：那个角标没有「标题 + 关闭点」这对东西，
# 整个角标本身就是可点的目标 —— 点它（或它上面任意位置）即可，所以「标题排他 + 关闭点」
# 的结构在这里根本不成立，硬凑第二锚点只会引入无谓的脆弱。排他性改由
# 「区域限定 + 图形本身独特」保证，并已实测：
# 2026-09-28 用 `runtime_logs/_pet_badge_scan.py` 扫全库 213 张夹具 ——
# **自身 1.0000，第二名只有 0.5017**（`epic7_labyrinth_stone/labyrinth_detail.png`），
# 阈值 0.80 的余量 0.30+，比骑士团三个弹窗（第二名 0.32）还宽。
# 若将来真出现误触，再补「宠物小屋图标」当第二锚点即可（它一直在这一页上）。
_PET_GIFT_BADGE_REGION = (1500, 300, 300, 220)
_PET_GIFT_THRESHOLD = 0.80

# ── 游戏内网页（WebView）的「网络错误」长条（2026-10-07 接）────────────────────
#
# 用户要求接进来的**第三种网络失败**。用户原话：「网络错误那个右上角是有一个叉的，
# 可以把它给擦掉的，你就按照这个来做，就相当于这是也是一种情况嘛，对吧」。
#
# ⚠️⚠️ **三种网络失败千万别混成一个**（2026-10-07 实测三者互不相同，各有各的判据）：
#
# | # | 长什么样 | 在哪 | 归谁管 |
# | --- | --- | --- | --- |
# | ① | 断线弹窗「与服务器的连接已中断 / 点击重试」 | 任何横屏页 | ``find_network_retry``（判文案、点屏幕中央） |
# | ② | 整页「网络连接异常，下拉刷新」1080x1920 | 社区 H5（竖屏） | ``community`` 那条路线（下加拉活）；本模块竖屏直接放行，够不到 |
# | ③ | 黑底白字「网络错误」长条，**只有文案、没有按钮** | 网页活动列表（横屏） | **本条**；唯一出路是网页容器右上角那颗 X |
#
# ①在③的帧上**完全认不出来**（实测全帧最高 message 0.3147 / message_alt 0.3619，
# 门槛 0.88）—— 两条判据不串味，这就是「不是同一个东西」的直接证据。
#
# 为什么要接③：2026-10-07 四次实跑里**两次**卡在这里。日志形状是
# 「点击验收=无效 → 提前重试 → 转场失败」，现场帧上那个 H5 **其实已经渲染出来了**
# （「RTA战绩查询网站上线啦」+ 侧栏），只是**缺了「游戏社区」那一项** ⇒
# 导航要的 ``web_community`` 锚点拿不到 ⇒ 判失败。长条就是那次请求失败留下的。
#
# 排他余量（2026-10-07 全库扫描，脚本 ``.workbuddy/_probe_web_error_tpl.py``）：
#
# | 样本 | 长条 | 圆钮 X |
# | --- | --- | --- |
# | 真机正例 ×2（相隔 40 分钟、页面内容不同） | **1.0000** | 1.0000 |
# | 「还在转圈」两张 | 0.2455 / 0.2450 | 0.9970 |
# | 正常网页活动列表（10-06 夹具） | 0.2161 | 0.9739 |
# | 全库 227 张横屏帧最高 | **0.4908** | 0.3155（非网页帧）|
#
# ⇒ 长条排他；圆钮 X **不排他**（网页上本来就有）⇒ 必须双锚点。
_WEB_NETWORK_MESSAGE_REGION = (560, 500, 860, 190)
_WEB_ERROR_CLOSE_REGION = (1790, 20, 192, 140)
# 门槛取 0.80，比别的弹窗那两档（0.82 / 0.88）都宽，是**故意的** —— 代价不对称：
#   漏掉长条 ⇒ 网页加载不完整、整条社区路线进不去（就是今天的形状，代价最大）；
#   误命中   ⇒ 在正常网页上点一下 X，把网页关掉，导航重试一次即可恢复。
# 而最近的负例只有 0.4908，0.80 离它仍有 0.31 的余量（正例是纯黑底 + 白字，对比度极高，
# ``TM_CCOEFF_NORMED`` 给的是 1.0000，留 0.20 的抗渲染差异余量）。
_WEB_NETWORK_THRESHOLD = 0.80
# 圆钮 X 只负责**定位**（判据是长条）：正例最低实测 0.9739、非网页帧 0.3155 ⇒ 0.85 够。
_WEB_ERROR_CLOSE_THRESHOLD = 0.85


def load_network_reconnect_templates(
    template_dir: Path,
) -> NetworkReconnectTemplates:
    alt_message = template_dir / "network_disconnected_message.png"
    retry_button = template_dir / "network_retry_button.png"
    reconnect_message = template_dir / "network_reconnect_message.png"
    return NetworkReconnectTemplates(
        message=load_template(str(template_dir / "network_message.png")),
        message_alt=(load_template(str(alt_message)) if alt_message.exists() else None),
        # 只有 PC 侧有这张（``templates/global/pc/network_retry_button.png``）；
        # 模拟器回落共享目录本就没有 → None → 仍然点屏幕中心。
        retry_button=(
            load_template(str(retry_button)) if retry_button.exists() else None
        ),
        # 同上：只有 PC 侧有这张（``templates/global/pc/network_reconnect_message.png``）。
        message_reconnect=(
            load_template(str(reconnect_message))
            if reconnect_message.exists()
            else None
        ),
    )


def load_intimacy_level_up_templates(
    template_dir: Path,
) -> IntimacyLevelUpTemplates:
    return IntimacyLevelUpTemplates(
        title=load_template(str(template_dir / "intimacy_level_up_title.png")),
        dismiss=load_template(str(template_dir / "intimacy_level_up_dismiss.png")),
    )


def load_friendship_points_templates(
    template_dir: Path,
) -> FriendshipPointsTemplates:
    return FriendshipPointsTemplates(
        title=load_template(str(template_dir / "friendship_points_title.png")),
        close=load_template(str(template_dir / "friendship_points_close.png")),
    )


def load_friend_request_templates(
    template_dir: Path,
) -> FriendRequestTemplates:
    return FriendRequestTemplates(
        title=load_template(str(template_dir / "friend_request_title.png")),
        cancel=load_template(str(template_dir / "friend_request_cancel.png")),
    )


def load_knights_signin_templates(
    template_dir: Path,
) -> KnightsSigninTemplates:
    return KnightsSigninTemplates(
        title=load_template(str(template_dir / "knights_signin_title.png")),
        close=load_template(str(template_dir / "knights_signin_close.png")),
    )


def load_gift_support_templates(
    template_dir: Path,
) -> GiftSupportTemplates:
    return GiftSupportTemplates(
        title=load_template(str(template_dir / "gift_support_title.png")),
        close=load_template(str(template_dir / "gift_support_close.png")),
    )


def load_knights_weekly_reward_templates(
    template_dir: Path,
) -> KnightsWeeklyRewardTemplates:
    return KnightsWeeklyRewardTemplates(
        title=load_template(str(template_dir / "knights_weekly_reward_title.png")),
        close=load_template(str(template_dir / "knights_weekly_reward_close.png")),
    )


def load_worldboss_support_reward_templates(
    template_dir: Path,
) -> WorldBossSupportRewardTemplates:
    """读「世界首领辅助队伍奖励」弹窗的两个锚点（``templates/navigation`` 下）。

    与骑士团那三个弹窗同目录（它们说的是同一页上的事：盖在骑士团 / 世界首领战主页上）。
    两张都直接 ``load_template`` —— 缺一张就开跑前抛，不做静默降级。
    """
    return WorldBossSupportRewardTemplates(
        title=load_template(str(template_dir / "worldboss_support_reward_title.png")),
        close=load_template(str(template_dir / "worldboss_support_reward_close.png")),
    )


def load_knights_growth_rank_templates(
    template_dir: Path,
) -> KnightsGrowthRankTemplates:
    """读「骑士团成长Rank提升」弹窗的两个锚点（``templates/navigation`` 下）。

    与骑士团那三个弹窗同目录（它们说的是同一页上的事）。
    两张都直接 ``load_template`` —— 缺一张就开跑前抛，不做静默降级。
    """
    return KnightsGrowthRankTemplates(
        title=load_template(str(template_dir / "knights_growth_rank_title.png")),
        close=load_template(str(template_dir / "knights_growth_rank_close.png")),
    )


def load_battle_record_templates(
    template_dir: Path,
) -> BattleRecordTemplates:
    """读「战斗记录」弹窗的两个锚点（``templates/navigation`` 下）。

    ``close`` **直接读「段位升级奖励」那张**（同一行「点击关闭」灰字）——
    同一个控件只该有一份图，另存第二份迟早漂移。
    两张都直接 ``load_template`` —— 缺一张就开跑前抛，不做静默降级。
    """
    return BattleRecordTemplates(
        title=load_template(str(template_dir / "battle_record_title.png")),
        close=load_template(str(template_dir / "arena_rank_reward_close.png")),
    )


def load_weekly_rank_start_templates(
    template_dir: Path,
) -> WeeklyRankStartTemplates:
    """读「新的每周排名开始！」弹窗的两个锚点（``templates/navigation`` 下）。

    ``close`` 复用「段位升级奖励」那张通用「点击关闭」灰字图 —— 同一个控件只存一份。
    两张都直接 ``load_template``，缺图就开跑前抛，不做静默降级。
    """
    return WeeklyRankStartTemplates(
        title=load_template(str(template_dir / "weekly_rank_start_title.png")),
        close=load_template(str(template_dir / "arena_rank_reward_close.png")),
    )


def load_weekly_rank_select_templates(
    template_dir: Path,
) -> WeeklyRankSelectTemplates:
    """读「每周排名选择奖励」弹窗的三个锚点（``templates/navigation`` 下）。

    三张都是本层专用，缺一张就开跑前抛 —— 尤其 ``sky_stone`` 是「点哪个奖励」的
    唯一依据，缺了不能退回写死坐标，那会点错奖励且一周只能领一次。
    """
    return WeeklyRankSelectTemplates(
        title=load_template(str(template_dir / "weekly_rank_select_title.png")),
        sky_stone=load_template(str(template_dir / "weekly_rank_select_sky_stone.png")),
        confirm=load_template(str(template_dir / "weekly_rank_select_confirm.png")),
    )


def load_arena_rank_reward_templates(
    template_dir: Path,
) -> ArenaRankRewardTemplates:
    """读「竞技场段位升级奖励」弹窗的两个锚点（``templates/navigation`` 下）。

    放 ``navigation/`` 与 ``worldboss_support_reward_*`` 同一目录 —— 它们都是
    「盖在某一页上、压暗底页锚点」的模态弹窗，导航那边的 ``observe()`` 也要报出页名，
    两边读同一份图，别放两处。
    两张都直接 ``load_template`` —— 缺一张就开跑前抛，不做静默降级。
    """
    return ArenaRankRewardTemplates(
        title=load_template(str(template_dir / "arena_rank_reward_title.png")),
        close=load_template(str(template_dir / "arena_rank_reward_close.png")),
    )


def load_pet_gift_templates(template_dir: Path) -> PetGiftTemplates:
    return PetGiftTemplates(
        badge=load_template(str(template_dir / "pet_gift_badge.png")),
    )


def load_web_network_error_templates(
    template_dir: Path,
) -> WebNetworkErrorTemplates:
    """读「网页网络错误」的两个锚点（``templates/navigation`` 下）。

    ⚠️ **fail closed**：两张都直接 ``load_template``，缺一张就当场抛 —— 不做
    ``if exists() else None``。判据型模板静默降级过一次就走了一个月弯路
    （2026-10-03 血泪），这里不再重演。
    """
    return WebNetworkErrorTemplates(
        message=load_template(str(template_dir / "web_network_message.png")),
        close=load_template(str(template_dir / "web_error_close.png")),
    )


def find_intimacy_level_up_dismiss(
    screen: np.ndarray,
    templates: IntimacyLevelUpTemplates,
) -> Match | None:
    lower = np.array([0, 0, 100])
    upper = np.array([179, 100, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        ref_x, ref_y, ref_width, ref_height = region
        scale_x = screen.shape[1] / _REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _REFERENCE_SIZE[1]
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width],
            cv2.COLOR_RGB2HSV,
        )
        template_hsv = cv2.cvtColor(
            template,
            cv2.COLOR_RGB2HSV,
        )
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            0.82,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(templates.title, _INTIMACY_TITLE_REGION)
    if title is None:
        return None
    dismiss = locate(templates.dismiss, _INTIMACY_DISMISS_REGION)
    if dismiss is None:
        return Match((screen.shape[1] // 2, screen.shape[0] // 2), title.score)
    return Match(dismiss.center, min(title.score, dismiss.score))


def find_network_retry(
    screen: np.ndarray,
    templates: NetworkReconnectTemplates,
) -> Match | None:
    """认断线弹窗（文案两版任一命中即可）；命中就返回**屏幕中央**当点击点。

    ⚠️ 先讲清这层弹窗长什么样：**文案有两种画法（甲 / 乙），按钮也有两种画法（甲 / 乙），
    两者并不绑定**。这不是「新旧版本」—— 没有证据表明游戏改过版，「8 月先出甲 / 后出乙」
    只是当年提交顺序。历史样本里出现过三种搭配：甲文案配甲按钮（8/13 两张帧）、
    乙文案配乙按钮（8/23 帧）、**乙文案配甲按钮（2026-10-04 首次撞见）**；
    第四种「甲文案配乙按钮」至今没见过 —— 所以别指望「没见过就不会出现」。

    也**不是两个不同弹窗**（按这个方向查过，结论是否定的）：三张真机帧上文案起点
    都精确落在 ``(780, 510)``、按钮都落在 ``(870~875, 690~695)`` —— 像素级重合，
    两个独立弹窗不可能共用同一套坐标。跨帧互比也能印证「交叉」确有其事
    （``runtime_logs/_probe_cross_frame.py``）：今天那帧的**按钮区对 8/13 帧 0.9854、
    对 8/23 帧只有 0.4183**；**文案区反过来对 8/23 帧 0.9992、对 8/13 帧只有 0.4697**。

    ⚠️ 2026-10-04 事故 —— 这里原先要求**文案与按钮成对**命中：
    ``(message, retry)`` 一组、``(message_alt, retry_alt)`` 一组，组内两个都要中。
    可早上竞技场掉线那帧偏偏是「文案乙 + 按钮甲」的交叉组合，两组各缺一半：

    | 锚点 | 分数 |
    |---|---|
    | message（文案甲） | 0.5001 不过阈 |
    | retry（按钮甲） | 0.9854 命中 |
    | message_alt（文案乙） | 0.9992 命中 |
    | retry_alt（按钮乙） | 0.4196 不过阈 |

    ⇒ 第一组缺文案、第二组缺按钮 ⇒ **两边都不成立 ⇒ 返回 None** ⇒ 守卫压根看不见这层
    弹窗 ⇒ 竞技场在「队伍选择」连点 4 次「战斗开始」都不动，按规矩安全停止、那条任务记 ✗
    （现场帧 ``runtime_diagnostics/epic7_arena/20261004_081019_044061_*``，已存成夹具
    ``epic7_global/network_disconnected_live_20261004.png``）。

    所以判定**只认文案**：文案排他性实测（全库 **218** 张，扫描脚本
    ``runtime_logs/_probe_network_message.py``，2026-10-04 重跑复核过）——
    network_message 自身两帧 1.0000 / 0.9995，跨页最高 0.5254；
    network_disconnected_message 自身 1.0000，跨页最高 0.5543。
    门槛 0.88，余量 0.33+。两张模板各自过阈的都是「自己那两种帧」，互不串味。

    命中即点屏幕中央：这层弹窗是**模态**的，点画面任何位置都会触发重试，
    而底下的页面本来就点不动 ⇒ 不存在「点错地方」的风险。这个兜底写法不是自创的，
    抄自 ``find_intimacy_level_up_dismiss``（它找不到关闭点时同样是点屏幕中央）。

    ``retry`` / ``retry_alt`` 两张按钮模板**保留在仓库里，但不再读进内存、不参与判定**：
    既然已经撞见过「文案乙配按钮甲」，再拿按钮去配文案，就是把两个各自独立的画法
    又硬拧成一组 —— 那是今天事故的老路。

    ⚠️ **2026-11-03 PC 实测：上面那句「点哪都行」不成立**。PC 上这层弹窗是全屏横带，
    文案在 y≈521、按钮在 y≈702~733，而屏幕中心 (991,566) 正落在两者之间的空白里 ——
    竞技场 10:23 / 18:35、主线 15:37 都是连点 4~8 次纹丝不动。
    所以现在多一步：文案命中之后，用 ``retry_button`` 模板去找按钮**真实位置**，
    找到就点它，找不到才回落屏幕中心。顺序必须保持「先认文案、再找按钮」——
    按钮只决定「点哪」，不参与「是不是这层弹窗」。
    """
    for message_template in (
        templates.message,
        templates.message_alt,
        templates.message_reconnect,
    ):
        if message_template is None:
            continue
        message = find_template(
            screen,
            message_template,
            _NETWORK_THRESHOLD,
            region=_MESSAGE_REGION,
            reference_size=_REFERENCE_SIZE,
        )
        if message is not None:
            if templates.retry_button is not None:
                retry = find_template(
                    screen,
                    templates.retry_button,
                    _NETWORK_RETRY_BUTTON_THRESHOLD,
                    reference_size=_REFERENCE_SIZE,
                )
                if retry is not None:
                    return Match(retry.center, message.score)
            return Match(
                (screen.shape[1] // 2, screen.shape[0] // 2), message.score
            )
    return None


def find_friendship_points_popup_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both friendship-popup anchors exist."""
    lower = np.array([0, 0, 120])
    upper = np.array([179, 110, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        scale_x = screen.shape[1] / _REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _REFERENCE_SIZE[1]
        ref_x, ref_y, ref_width, ref_height = region
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
        )
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            _FRIENDSHIP_ANCHOR_THRESHOLD,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(title_template, _FRIENDSHIP_TITLE_REGION)
    close = locate(close_template, _FRIENDSHIP_CLOSE_REGION)
    if title is None or close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_friend_request_cancel(
    screen: np.ndarray,
    title_template: np.ndarray,
    cancel_template: np.ndarray,
) -> Match | None:
    """Return Cancel only when both friend-request popup anchors are present."""
    title = find_template(
        screen,
        title_template,
        0.82,
        region=_FRIEND_REQUEST_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    cancel = find_template(
        screen,
        cancel_template,
        0.82,
        region=_FRIEND_REQUEST_CANCEL_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if cancel is None:
        return None
    return Match(cancel.center, min(title.score, cancel.score))


# ── 「领取支援物品」（骑士团支援资源领取后弹一次）─────────────────────────────
#
# 2026-11-02 10:06 世界首领战 PC 实跑：点「进入骑士团」后它盖住骑士团主页，
# 页面判成「认不出的画面」，路线直接卡在入口（诊断帧 wb_knights.png）。
#
# 已登记的两类都对不上：``gift_support_title`` 0.4572、``worldboss_support_reward_title``
# 0.2150（**文案不同**，不是同一层弹窗）；但两者的 close 锚点位置是对的
# （0.6551 / 0.7082）—— 说明差的是标题这一句，不是坐标。
_GIFT_CLAIM_TITLE_REGION = (760, 250, 460, 120)
_GIFT_CLAIM_CLOSE_REGION = (830, 800, 320, 120)
_GIFT_CLAIM_THRESHOLD = 0.85


@dataclass(frozen=True)
class GiftClaimTemplates:
    title: np.ndarray
    close: np.ndarray


def load_gift_claim_templates(template_dir: Path) -> GiftClaimTemplates | None:
    title = template_dir / "gift_claim_title.png"
    close = template_dir / "gift_claim_close.png"
    if not (title.exists() and close.exists()):
        return None
    return GiftClaimTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def find_gift_claim_close(
    screen: np.ndarray,
    templates: GiftClaimTemplates,
) -> Match | None:
    """Return the close control only when both 领取支援物品 anchors are present."""
    title = find_template(
        screen,
        templates.title,
        _GIFT_CLAIM_THRESHOLD,
        region=_GIFT_CLAIM_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        templates.close,
        _GIFT_CLAIM_THRESHOLD,
        region=_GIFT_CLAIM_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


# ── 「账号 Rank 提升」（账号升级时弹一次）─────────────────────────────────────
#
# 2026-11-02 15:35 主线 PC 实跑：战斗打完弹这一层，战斗画面连续 45 秒认不出
# ⇒「战斗画面持续无法识别超时」；接着回家它又挡着，连按 2 次 ESC 都没反应
# ⇒「返回首页失败」，整轮以退出码 1 收场
# （诊断帧 20261102_153533_607233_battle_unrecognized.png）。
#
# 锚「账号Rank提升」这半句 + 底部向下箭头，理由是**正文含会变的数字**：
# 「已恢复176点行动力」的行动力、徽章里「RANK UP 45」的等级，每次升级都不同
# ⇒ 模板一律只取不含数字的那一段（与「模板不含会变内容」同一条纪律）。
#
# ⚠️ 两张图都是**从 PC 帧裁的** —— 仓库里没有这张弹窗的模拟器样本。模拟器侧
# 取到样本后要重裁共享图；PC 不受影响（有 ``global/pc/`` 同名图时优先用它）。
_ACCOUNT_RANK_UP_TITLE_REGION = (600, 920, 800, 120)
_ACCOUNT_RANK_UP_CLOSE_REGION = (760, 1000, 460, 140)
_ACCOUNT_RANK_UP_THRESHOLD = 0.85


@dataclass(frozen=True)
class AccountRankUpTemplates:
    title: np.ndarray
    close: np.ndarray


def load_account_rank_up_templates(
    template_dir: Path,
) -> AccountRankUpTemplates | None:
    title = template_dir / "account_rank_up_title.png"
    close = template_dir / "account_rank_up_close.png"
    if not (title.exists() and close.exists()):
        return None
    return AccountRankUpTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def find_account_rank_up_close(
    screen: np.ndarray,
    templates: AccountRankUpTemplates,
) -> Match | None:
    """Return the close control only when both 账号 Rank 提升 anchors are present."""
    title = find_template(
        screen,
        templates.title,
        _ACCOUNT_RANK_UP_THRESHOLD,
        region=_ACCOUNT_RANK_UP_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        templates.close,
        _ACCOUNT_RANK_UP_THRESHOLD,
        region=_ACCOUNT_RANK_UP_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


# ── 「支线故事通知」（新支线解锁时弹一次）─────────────────────────────────────
#
# 2026-11-01 22:05 主线 PC 实跑：战斗打完、结算页正要确认时它盖上来，
# `等待结算` 45 秒无进展，最后整条路线以退出码 1 收场
# （诊断帧 20261101_220554_360858_timeout_wait_results.png）。
#
# 为什么锚标题 + 「点击关闭」而不是锚正文：**正文与插画随解锁的支线变化**
# （"支线故事「被选中的女巫」已解锁"），只有标题「支线故事通知」和底部
# 「点击关闭」是固定文案。两锚点同时命中才算，避免「点击关闭」在别处撞车。
_SIDE_STORY_NOTICE_TITLE_REGION = (760, 240, 460, 120)
_SIDE_STORY_NOTICE_CLOSE_REGION = (830, 840, 320, 120)
_SIDE_STORY_NOTICE_THRESHOLD = 0.85


@dataclass(frozen=True)
class SideStoryNoticeTemplates:
    title: np.ndarray
    close: np.ndarray


def load_side_story_notice_templates(
    template_dir: Path,
) -> SideStoryNoticeTemplates | None:
    title = template_dir / "side_story_notice_title.png"
    close = template_dir / "side_story_notice_close.png"
    if not (title.exists() and close.exists()):
        return None
    return SideStoryNoticeTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def find_side_story_notice_close(
    screen: np.ndarray,
    templates: SideStoryNoticeTemplates,
) -> Match | None:
    """Return the close control only when both 支线故事通知 anchors are present."""
    title = find_template(
        screen,
        templates.title,
        _SIDE_STORY_NOTICE_THRESHOLD,
        region=_SIDE_STORY_NOTICE_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        templates.close,
        _SIDE_STORY_NOTICE_THRESHOLD,
        region=_SIDE_STORY_NOTICE_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


# ── 「获得奖励」通知（星星/任务奖励发放后弹一次）─────────────────────────────
#
# 2026-11-01 22:27 主线 PC 实跑：点完「通关提示」回到关卡入口，它盖上来，
# `等待通关` 45 秒无进展（诊断帧 20261101_222757 ..._timeout_wait_complete.png）。
# 同帧上 `bonus_reward` 只有 0.7724（阈 0.80）—— 差 0.028 就整条路线卡住。
#
# 正文（"获得星星奖励已正常发放。"）与奖励图标随奖励类型变化，只锚固定的
# 标题「获得奖励」和底部「点击关闭」，两锚点同时命中才算。
_REWARD_NOTICE_TITLE_REGION = (800, 240, 500, 120)
_REWARD_NOTICE_CLOSE_REGION = (830, 780, 320, 120)
_REWARD_NOTICE_THRESHOLD = 0.85


@dataclass(frozen=True)
class RewardNoticeTemplates:
    title: np.ndarray
    close: np.ndarray


def load_reward_notice_templates(template_dir: Path) -> RewardNoticeTemplates | None:
    title = template_dir / "reward_notice_title.png"
    close = template_dir / "reward_notice_close.png"
    if not (title.exists() and close.exists()):
        return None
    return RewardNoticeTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def find_reward_notice_close(
    screen: np.ndarray,
    templates: RewardNoticeTemplates,
) -> Match | None:
    """Return the close control only when both 获得奖励 anchors are present."""
    title = find_template(
        screen,
        templates.title,
        _REWARD_NOTICE_THRESHOLD,
        region=_REWARD_NOTICE_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        templates.close,
        _REWARD_NOTICE_THRESHOLD,
        region=_REWARD_NOTICE_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_knights_signin_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both knights-signin popup anchors exist.

    这是「每天第一次进骑士团」的签到达成度奖励弹窗。它盖在骑士团主页上，
    把底页的 ``worldboss_entry`` 锚点从 0.9890 压到 0.4477（低于 0.85 门槛），
    所以弹窗期间页面识别必然失败 —— 必须先关掉它再识别，不能指望穿透。

    两个锚点都命中才算，避免「点击关闭」这四个字在别的弹窗上撞车。
    实测弹窗帧上双锚点都是 1.0000，弹窗关闭后标题掉到 0.1799、关闭点掉到 0.3012。
    """
    title = find_template(
        screen,
        title_template,
        _KNIGHTS_SIGNIN_THRESHOLD,
        region=_KNIGHTS_SIGNIN_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _KNIGHTS_SIGNIN_THRESHOLD,
        region=_KNIGHTS_SIGNIN_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_gift_support_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both gift-support popup anchors exist.

    这是「进骑士团时团员赠送的支援资源到账」弹窗（标题「领取支援物品」）。
    它和签到弹窗一样盖在骑士团主页上，会把底页锚点压暗 ⇒ 弹窗期间页面识别必然失败，
    必须先关掉它再识别，不能指望穿透。

    两个锚点都命中才算：标题锚点排他（跨页最高 0.3240），
    但「点击关闭」这四个字单独不排他（hero/reward_popup 上 0.9996），
    所以必须靠标题把「点击关闭」的乱命中挡掉。
    实测弹窗帧双锚点都是 1.0000。
    """
    title = find_template(
        screen,
        title_template,
        _GIFT_SUPPORT_THRESHOLD,
        region=_GIFT_SUPPORT_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _GIFT_SUPPORT_THRESHOLD,
        region=_GIFT_SUPPORT_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_knights_weekly_reward_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both weekly-reward popup anchors exist.

    这是「每周一骑士团点数结算」弹窗（标题「获得每周骑士团点数奖励」）。
    它和签到/支援弹窗一样盖在骑士团主页上，会把底页锚点压暗 ⇒ 弹窗期间页面
    识别必然失败，必须先关掉它再识别，不能指望穿透。

    两个锚点都命中才算：标题锚点排他（跨页最高 0.3376），
    但「点击关闭」这四个字单独不排他（hero/reward_popup 上 0.9996），
    所以必须靠标题把「点击关闭」的乱命中挡掉。实测弹窗帧双锚点都是 1.0000。
    """
    title = find_template(
        screen,
        title_template,
        _KNIGHTS_WEEKLY_REWARD_THRESHOLD,
        region=_KNIGHTS_WEEKLY_REWARD_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _KNIGHTS_WEEKLY_REWARD_THRESHOLD,
        region=_KNIGHTS_WEEKLY_REWARD_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_worldboss_support_reward_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """认「世界首领辅助队伍奖励」弹窗，命中就返回底部「点击关闭」那行灰字的中心。

    这是**每天都会遇到**的一层：同僚团员借你的辅助队伍出战并拿到奖励后，进
    「世界首领战主页」时弹出。它把底页压暗，主页右下角那颗「选择队伍」直接认不出来
    ⇒ ``observe()`` 报 unknown ⇒ 2026-10-19 08:11 那条导航转场一路等到 08:12:44 失败。

    为什么必须双锚点：标题排他（跨页最高 0.3320），但「点击关闭」这四个字在
    ``reward_popup`` 上是 0.8993、``popup_spring`` / ``popup_penguin_*`` 都是 0.8991
    —— 那是游戏里通用的一条灰字控件，**单独用会在别的领奖弹窗上乱点**。
    """
    title = find_template(
        screen,
        title_template,
        _WORLDBOSS_SUPPORT_THRESHOLD,
        region=_WORLDBOSS_SUPPORT_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _WORLDBOSS_SUPPORT_THRESHOLD,
        region=_WORLDBOSS_SUPPORT_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_arena_rank_reward_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """认「竞技场段位升级奖励」弹窗，命中就返回底部「点击关闭」那行字的中心。

    现场（2026-10-20 08:02，`epic7_arena` 记的那次 ✗）：打完第 7 局、点掉
    「段位提升」之后，这一层紧跟着弹出来 —— 它**首次升至各段位才出现**，
    所以此前从没被撞见过，也就没有判据。它把底页压暗，竞技场那边
    `list_ready` 只剩 0.640、`confirm` 只剩 0.103 ⇒ 来源页判「已离开」、
    目标页「对手列表」不出现 ⇒ 一路等到 45 秒上限。

    为什么必须双锚点：标题「升级奖励」排他（全库负样本最高 0.4675），
    而「点击关闭」这四个字是游戏里通用的一条灰字 —— 全库实测最像的到 **0.9852**
    （`reward_popup.png` 一类领奖弹窗），单锚点会在它们上面乱点。
    """
    title = find_template(
        screen,
        title_template,
        _ARENA_RANK_REWARD_THRESHOLD,
        region=_ARENA_RANK_REWARD_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _ARENA_RANK_REWARD_THRESHOLD,
        region=_ARENA_RANK_REWARD_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_knights_growth_rank_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """认「骑士团成长Rank提升」弹窗，命中就返回底部「点击关闭」那行字的中心。

    现场（2026-10-30 19:48，`epic7_world_boss` 记的那次 ✗）：从大厅打开快捷菜单、
    点「骑士团」之后它盖住骑士团主页 ⇒ 那条路线一路"只等"到 2 分钟上限，
    报「导航转场 快捷菜单 → knights_home 失败」。

    与「段位升级奖励」同一条分工：标题排他（全库次高 0.3210）、关闭点给位置。
    """
    title = find_template(
        screen,
        title_template,
        _KNIGHTS_GROWTH_THRESHOLD,
        region=_KNIGHTS_GROWTH_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _KNIGHTS_GROWTH_THRESHOLD,
        region=_KNIGHTS_GROWTH_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_battle_record_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """认「战斗记录」弹窗，命中就返回底部「点击关闭」那行字的中心。

    现场（2026-10-30 18:27，`epic7_arena` 记的那次 ✗）：从大厅点「进入竞技场」后，
    游戏先弹出这一层（防守战绩：优胜者Ⅱ → Ⅲ，段位下降）。它把对手列表压暗 ⇒
    `list_ready` 从 0.8834 掉到 0.7230、竞技场标题却仍有 0.9981（标题在弹窗上方），
    于是**没有任何一页认得出它** ⇒ 导航一路"只等"到 129 秒报「转场失败」。

    为什么必须双锚点：标题「战斗记录」排他（真帧 1.0000 / 其余横屏帧最高 0.2388），
    而「点击关闭」是通用灰字（同一行控件在全库最像的到 0.9852），单锚点会乱点。
    """
    title = find_template(
        screen,
        title_template,
        _BATTLE_RECORD_THRESHOLD,
        region=_BATTLE_RECORD_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _BATTLE_RECORD_THRESHOLD,
        region=_BATTLE_RECORD_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_weekly_rank_start_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """认「新的每周排名开始！」弹窗，命中就返回底部「点击关闭」的中心。

    双锚点：标题排他，关闭点给位置。ROI 与「战斗记录」/「段位奖励」都不同 ——
    这一层的标题更高、关闭按钮更低，照抄别层会两边都切掉。
    """
    title = find_template(
        screen,
        title_template,
        _WEEKLY_RANK_START_THRESHOLD,
        region=_WEEKLY_RANK_START_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _WEEKLY_RANK_START_THRESHOLD,
        region=_WEEKLY_RANK_START_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def _weekly_rank_select_confirm_lit(screen: np.ndarray) -> bool:
    """「领取选择的奖励」按钮文字是否已经变白（等价于「已经选中了某个奖励」）。

    只看这一小块文字区域的白像素占比。未选中时文字是灰的：2026-11-09 11:41
    现场帧实测 p99 亮度只有 153、白像素占比 0.0000；选中后文字转白，占比会成片出现。
    """
    x, y, w, h = _WEEKLY_RANK_SELECT_CONFIRM_TEXT_REGION
    scale_x = screen.shape[1] / _REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _REFERENCE_SIZE[1]
    if abs(scale_x - scale_y) > 0.02:
        raise RuntimeError("画面宽高比与模板基准不一致")
    x, y = round(x * scale_x), round(y * scale_y)
    w, h = round(w * scale_x), round(h * scale_y)
    patch = screen[y : y + h, x : x + w].astype(np.int16)
    luma = patch.mean(axis=2)
    spread = patch.max(axis=2) - patch.min(axis=2)
    lit = (luma > _WEEKLY_RANK_SELECT_LUMA) & (spread < _WEEKLY_RANK_SELECT_SPREAD)
    return float(lit.mean()) > _WEEKLY_RANK_SELECT_CONFIRM_LIT_RATIO


def find_weekly_rank_select_action(
    screen: np.ndarray,
    templates: WeeklyRankSelectTemplates,
) -> tuple[Match, str] | None:
    """认「每周排名选择奖励」弹窗，返回**这一次该点哪里**和动作名。

    这层弹窗要两次点击才能过：先选钻石，再点领取。守卫每轮都会重新判画面，
    所以这里靠「领取按钮亮没亮」决定这一步点哪，不需要跨帧记忆，也不写死坐标：

    - 按钮文字还灰 ⇒ 返回天空石卡片中心，动作 ``select-weekly-rank-diamond``；
    - 按钮文字已白 ⇒ 返回领取按钮中心，动作 ``claim-weekly-rank-select``。
    """
    title = find_template(
        screen,
        templates.title,
        _WEEKLY_RANK_SELECT_THRESHOLD,
        region=_WEEKLY_RANK_SELECT_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    confirm = find_template(
        screen,
        templates.confirm,
        _WEEKLY_RANK_SELECT_THRESHOLD,
        region=_WEEKLY_RANK_SELECT_CONFIRM_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if confirm is None:
        return None
    if _weekly_rank_select_confirm_lit(screen):
        return Match(confirm.center, min(title.score, confirm.score)), "claim-weekly-rank-select"
    stone = find_template(
        screen,
        templates.sky_stone,
        _WEEKLY_RANK_SELECT_THRESHOLD,
        region=_WEEKLY_RANK_SELECT_CARD_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if stone is None:
        return None
    return Match(stone.center, min(title.score, stone.score)), "select-weekly-rank-diamond"


def find_web_network_error_close(
    screen: np.ndarray,
    templates: WebNetworkErrorTemplates,
) -> Match | None:
    """认网页的「网络错误」长条，命中就返回**网页容器右上角那颗 X** 当点击点。

    ## 为什么点击点不是「屏幕中央」（与断线弹窗的关键区别）

    断线弹窗是**模态**的：点画面任何位置都会触发重试，所以那边命中就点中央。
    这条长条**没有按钮**，点别处什么都不发生 —— 实测证据就是旧写法：
    社区那条路线原先遇到整页版时点的是 ``FEED_CLOSE``，而点位实测落在空白上。

    ⇒ 唯一能消掉它的就是右上角那颗圆钮 X。它同时**会关掉整个网页**，
    于是导航会重新点一次「前往活动页」把网页再打开一遍 —— 这正是我们要的重试。

    ## 为什么两个锚点都要，而不是只用长条 + 一个钉死的坐标

    长条出现的位置固定（实测两张真机帧逐像素相同，都在 ``(624,550,672,84)``），
    但「X 在哪」这件事**应当由画面说了算**：网页面板将来挪一寸，钉死的坐标就点到别处去，
    而长条仍旧会命中。所以第二个锚点是**定位**用的，不是多余的配对。

    ⚠️ 与 ``find_network_retry`` 那边「文案甲/乙与按钮甲/乙互不绑定」的教训不冲突：
    那边的问题是「两个各自独立换皮肤的画法被硬拧成一组」。这里两个锚点分工不同 ——
    长条是**判据**（认事），X 是**定位**（认点），X 换皮肤只会让定位失败（返回 None，
    保守不动手），不会让判据失真。
    """
    message = find_template(
        screen,
        templates.message,
        _WEB_NETWORK_THRESHOLD,
        region=_WEB_NETWORK_MESSAGE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if message is None:
        return None
    close = find_template(
        screen,
        templates.close,
        _WEB_ERROR_CLOSE_THRESHOLD,
        region=_WEB_ERROR_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        # 长条在、X 却定位不到 ⇒ **不动手**（返回 None 让上层照旧失败并留诊断），
        # 而不是退回一个猜的坐标：这一点旁边就是屏幕右边缘，点偏了没有第二次机会。
        return None
    return Match(close.center, min(message.score, close.score))


def find_pet_gift_badge(
    screen: np.ndarray,
    badge_template: np.ndarray,
) -> Match | None:
    """认「宠物小屋礼物角标」，返回点击点（角标中心）。

    与上面几个弹窗不同，这是**单锚点**：那个角标没有「标题 + 关闭点」，
    整个角标本身就是要点掉的目标（理由与实测余量见
    ``_PET_GIFT_BADGE_REGION`` 上方的注释）。
    点它一下 → 礼物领取、角标消失；不点则一直挂着，每天回家都会看见。
    """
    return find_template(
        screen,
        badge_template,
        _PET_GIFT_THRESHOLD,
        region=_PET_GIFT_BADGE_REGION,
        reference_size=_REFERENCE_SIZE,
    )


class Epic7GlobalPopupGuard:
    """Consume known system popups before business state machines see them."""

    def __init__(
        self,
        templates: NetworkReconnectTemplates,
        *,
        intimacy_templates: IntimacyLevelUpTemplates | None = None,
        friendship_templates: FriendshipPointsTemplates | None = None,
        friend_request_templates: FriendRequestTemplates | None = None,
        side_story_notice_templates: SideStoryNoticeTemplates | None = None,
        reward_notice_templates: RewardNoticeTemplates | None = None,
        gift_claim_templates: GiftClaimTemplates | None = None,
        account_rank_up_templates: AccountRankUpTemplates | None = None,
        knights_signin_templates: KnightsSigninTemplates | None = None,
        gift_support_templates: GiftSupportTemplates | None = None,
        knights_weekly_reward_templates: KnightsWeeklyRewardTemplates | None = None,
        worldboss_support_reward_templates: WorldBossSupportRewardTemplates
        | None = None,
        arena_rank_reward_templates: ArenaRankRewardTemplates | None = None,
        battle_record_templates: BattleRecordTemplates | None = None,
        weekly_rank_start_templates: WeeklyRankStartTemplates | None = None,
        weekly_rank_select_templates: WeeklyRankSelectTemplates | None = None,
        knights_growth_rank_templates: KnightsGrowthRankTemplates | None = None,
        pet_gift_templates: PetGiftTemplates | None = None,
        web_network_error_templates: WebNetworkErrorTemplates | None = None,
        # 2026-11-03：游戏自己按时间弹的两条（变更日期 / 获得登录奖励）。
        # 模板只有 PC 版 ⇒ 模拟器口径下 load 成 None ⇒ 整段跳过，行为不变。
        date_change_templates: DateChangeTemplates | None = None,
        knights_activity_templates: KnightsActivityTemplates | None = None,
        uncontrollable_templates: UncontrollableTemplates | None = None,
        tutorial_unlock_templates: TutorialUnlockTemplates | None = None,
        # 2026-11-06：新手账号大厅右上角的「跳过教学 ✕」（顶掉快捷菜单的那块）。
        tutorial_skip_templates: TutorialSkipTemplates | None = None,
        login_reward_templates: LoginRewardTemplates | None = None,
        sleep: Callable[[float], None] = default_sleep,
        now: Callable[[], float] = monotonic,
        poll_seconds: float = 1.0,
        retry_interval_seconds: float = 3.0,
        failure_seconds: float = 15.0,
    ) -> None:
        self.templates = templates
        self.intimacy_templates = intimacy_templates
        self.friendship_templates = friendship_templates
        self.friend_request_templates = friend_request_templates
        self.side_story_notice_templates = side_story_notice_templates
        self.reward_notice_templates = reward_notice_templates
        self.gift_claim_templates = gift_claim_templates
        self.account_rank_up_templates = account_rank_up_templates
        self.knights_signin_templates = knights_signin_templates
        self.gift_support_templates = gift_support_templates
        self.knights_weekly_reward_templates = knights_weekly_reward_templates
        self.worldboss_support_reward_templates = worldboss_support_reward_templates
        self.arena_rank_reward_templates = arena_rank_reward_templates
        self.battle_record_templates = battle_record_templates
        self.weekly_rank_start_templates = weekly_rank_start_templates
        self.weekly_rank_select_templates = weekly_rank_select_templates
        self.knights_growth_rank_templates = knights_growth_rank_templates
        self.pet_gift_templates = pet_gift_templates
        self.web_network_error_templates = web_network_error_templates
        self.date_change_templates = date_change_templates
        self.knights_activity_templates = knights_activity_templates
        self.uncontrollable_templates = uncontrollable_templates
        self.tutorial_unlock_templates = tutorial_unlock_templates
        self.tutorial_skip_templates = tutorial_skip_templates
        self.login_reward_templates = login_reward_templates
        self.sleep = sleep
        self.now = now
        self.poll_seconds = poll_seconds
        self.retry_interval_seconds = retry_interval_seconds
        self.failure_seconds = failure_seconds

    def _find_popup(
        self, screen: np.ndarray
    ) -> tuple[Match | None, str | None, str | None, str | None, str | None]:
        """按优先级返回首个命中的弹窗（匹配点, 标识, 动作, 诊断标签, 失败文案）。"""
        match = find_network_retry(screen, self.templates)
        if match is not None:
            return (
                match,
                "network",
                "retry-network",
                "network_retry_failed",
                f"断网重连弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
            )
        if self.web_network_error_templates is not None:
            match = find_web_network_error_close(
                screen, self.web_network_error_templates
            )
            if match is not None:
                return (
                    match,
                    "web_network_error",
                    "dismiss-web-network-error",
                    "web_network_error_failed",
                    f"网页「网络错误」右上角的 X 点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        # 2026-11-03：游戏按时间自己弹的两条。变更日期会把页面强制切回大厅
        # （跑任何路线都会被打断），所以排在登录奖励前面 —— 先把它点掉再谈别的。
        # 2026-11-06：主线在关卡入口页会被这个**居中模态**剧情弹窗整页盖住
        # （Episode 3 第 10 章「无法控制」）⇒ 认不出关卡入口 ⇒ 45 秒超时整条失败。
        # 它是标准弹窗（不是整屏页面），放这里安全。
        if self.uncontrollable_templates is not None:
            match = find_uncontrollable_close(screen, self.uncontrollable_templates)
            if match is not None:
                return (
                    match,
                    "uncontrollable",
                    "dismiss-uncontrollable",
                    "uncontrollable_failed",
                    f"「无法控制」弹窗底部「点击关闭」点了{_MAX_POPUP_CLICKS}次仍未关掉",
                )
        # 2026-11-06 12:29 真机：主线打到 Episode 4 第 11 关，弹「轻触后解锁
        # 【觉醒者艾庭】」教学遮罩。它把「准备战斗」和 ESC 一起吞掉 ⇒
        # prepare_battle 点 4 次不转场、收尾 ESC 2 次无效 ⇒ 主线 ✗ 且每日任务
        # 「已中止」，后面 8 条路线全没跑。判据排他（全库 360 张反例最高 0.4323），
        # 三张图只在 pc/ 里 ⇒ 模拟器整段跳过，放守卫安全。
        if self.tutorial_unlock_templates is not None:
            match = find_tutorial_unlock_skip(screen, self.tutorial_unlock_templates)
            if match is not None:
                return (
                    match,
                    "tutorial_unlock",
                    "dismiss-tutorial-unlock",
                    "tutorial_unlock_failed",
                    f"「轻触后解锁」教学遮罩点了{_MAX_POPUP_CLICKS}次仍未消失",
                )
        # 2026-11-06 22:27 真机：新手账号大厅右上角常驻一块「跳过教学 ✕」——
        # 它把原来的**快捷菜单蓝四格顶掉**，导航层「打开快捷菜单」锚点找不到，
        # 多条路线在这台机器上反复失败（老账号的模拟器从来没这个东西）。
        # 点掉 ✕ 之后这一整块才消失、右上角才恢复成快捷菜单。
        if self.tutorial_skip_templates is not None:
            point = find_tutorial_skip_point(screen, self.tutorial_skip_templates)
            if point is not None:
                return (
                    point,
                    "tutorial_skip",
                    "dismiss-tutorial-skip",
                    "tutorial_skip_failed",
                    f"「跳过教学」按钮点了{_MAX_POPUP_CLICKS}次仍未消失",
                )
        # ⚠️「骑士团活动」页**不能**放在这里：骑士团捐赠路线正常流程就会切到
        # 「每周任务」标签（实测 22:33:42 `open-weekly-tab` 之后就在那一页），
        # 守卫每帧都点在 capture 层跑 ⇒ 一进那页就被踢出去，路线直接失败。
        # 它只在「回首页」这个场景需要 —— 见 `home_return.find_knights_activity_close`。
        if self.date_change_templates is not None:
            match = find_date_change_close(screen, self.date_change_templates)
            if match is not None:
                return (
                    match,
                    "date_change",
                    "dismiss-date-change",
                    "date_change_failed",
                    f"「日期变更」弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.login_reward_templates is not None:
            match = find_login_reward_close(screen, self.login_reward_templates)
            if match is not None:
                return (
                    match,
                    "login_reward",
                    "dismiss-login-reward",
                    "login_reward_failed",
                    f"「获得登录奖励」弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.intimacy_templates is not None:
            match = find_intimacy_level_up_dismiss(screen, self.intimacy_templates)
            if match is not None:
                return (
                    match,
                    "intimacy",
                    "dismiss-intimacy-level-up",
                    "intimacy_level_up_failed",
                    f"亲密度提升弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.friendship_templates is not None:
            match = find_friendship_points_popup_close(
                screen,
                self.friendship_templates.title,
                self.friendship_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "friendship_points",
                    "close-friendship-points-popup",
                    "friendship_points_failed",
                    f"友情点数弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.friend_request_templates is not None:
            match = find_friend_request_cancel(
                screen,
                self.friend_request_templates.title,
                self.friend_request_templates.cancel,
            )
            if match is not None:
                return (
                    match,
                    "friend_request",
                    "cancel-friend-request",
                    "friend_request_failed",
                    f"好友申请弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.side_story_notice_templates is not None:
            match = find_side_story_notice_close(
                screen, self.side_story_notice_templates
            )
            if match is not None:
                return (
                    match,
                    "side_story_notice",
                    "dismiss-side-story-notice",
                    "side_story_notice_failed",
                    f"支线故事通知点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.reward_notice_templates is not None:
            match = find_reward_notice_close(screen, self.reward_notice_templates)
            if match is not None:
                return (
                    match,
                    "reward_notice",
                    "dismiss-reward-notice",
                    "reward_notice_failed",
                    f"获得奖励通知点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.gift_claim_templates is not None:
            match = find_gift_claim_close(screen, self.gift_claim_templates)
            if match is not None:
                return (
                    match,
                    "gift_claim",
                    "dismiss-gift-claim",
                    "gift_claim_failed",
                    f"领取支援物品弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.account_rank_up_templates is not None:
            match = find_account_rank_up_close(screen, self.account_rank_up_templates)
            if match is not None:
                return (
                    match,
                    "account_rank_up",
                    "dismiss-account-rank-up",
                    "account_rank_up_failed",
                    f"账号Rank提升弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.knights_signin_templates is not None:
            match = find_knights_signin_close(
                screen,
                self.knights_signin_templates.title,
                self.knights_signin_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "knights_signin",
                    "close-knights-signin",
                    "knights_signin_failed",
                    f"骑士团签到弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.gift_support_templates is not None:
            match = find_gift_support_close(
                screen,
                self.gift_support_templates.title,
                self.gift_support_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "gift_support",
                    "close-gift-support",
                    "gift_support_failed",
                    f"领取支援物品弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.knights_weekly_reward_templates is not None:
            match = find_knights_weekly_reward_close(
                screen,
                self.knights_weekly_reward_templates.title,
                self.knights_weekly_reward_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "knights_weekly_reward",
                    "close-knights-weekly-reward",
                    "knights_weekly_reward_failed",
                    f"骑士团周结算奖励弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.worldboss_support_reward_templates is not None:
            match = find_worldboss_support_reward_close(
                screen,
                self.worldboss_support_reward_templates.title,
                self.worldboss_support_reward_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "worldboss_support_reward",
                    "close-worldboss-support-reward",
                    "worldboss_support_reward_failed",
                    f"世界首领辅助队伍奖励弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.arena_rank_reward_templates is not None:
            match = find_arena_rank_reward_close(
                screen,
                self.arena_rank_reward_templates.title,
                self.arena_rank_reward_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "arena_rank_reward",
                    "close-arena-rank-reward",
                    "arena_rank_reward_failed",
                    f"段位升级奖励弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.battle_record_templates is not None:
            match = find_battle_record_close(
                screen,
                self.battle_record_templates.title,
                self.battle_record_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "battle_record",
                    "close-battle-record",
                    "battle_record_failed",
                    f"战斗记录弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.weekly_rank_start_templates is not None:
            match = find_weekly_rank_start_close(
                screen,
                self.weekly_rank_start_templates.title,
                self.weekly_rank_start_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "weekly_rank_start",
                    "close-weekly-rank-start",
                    "weekly_rank_start_failed",
                    f"新的每周排名弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.weekly_rank_select_templates is not None:
            choice = find_weekly_rank_select_action(
                screen, self.weekly_rank_select_templates
            )
            if choice is not None:
                match, action = choice
                return (
                    match,
                    "weekly_rank_select",
                    action,
                    "weekly_rank_select_failed",
                    f"每周排名选择奖励弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.knights_growth_rank_templates is not None:
            match = find_knights_growth_rank_close(
                screen,
                self.knights_growth_rank_templates.title,
                self.knights_growth_rank_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "knights_growth_rank",
                    "close-knights-growth-rank",
                    "knights_growth_rank_failed",
                    f"骑士团成长Rank提升弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        if self.pet_gift_templates is not None:
            match = find_pet_gift_badge(screen, self.pet_gift_templates.badge)
            if match is not None:
                return (
                    match,
                    "pet_gift",
                    "claim-pet-gift",
                    "pet_gift_failed",
                    f"宠物小屋礼物角标点击{_MAX_POPUP_CLICKS}次后仍未消失",
                )
        return None, None, None, None, None

    def __call__(
        self, runtime: "Runtime", screen: np.ndarray
    ) -> tuple[np.ndarray, bool]:
        # ⚠️⚠️ **竖屏画面直接放行**（2026-10-07 修，用户点 2 的真凶）。
        #
        # 这一层所有判据（网络重连、亲密度升级、好友申请、骑士团签到弹窗……）
        # 都是**横屏**控件，基准是横屏画布 1982x1132，定位时按
        # ``screen.shape / _REFERENCE_SIZE`` 缩放，并有**宽高比守卫**
        # （``evidence/sanctuary._scale_region``：``abs(scale_x - scale_y) > 0.02``
        # 就抛「画面宽高比与模板基准不一致」）。
        #
        # 社区路线点进「游戏社区」后画面变成 **1080x1920** ⇒ 缩放比例
        # 横向 1080/1982=0.545、纵向 1920/1132=1.696 ⇒ 守卫**必然抛错** ⇒
        # 异常从 ``Runtime.capture`` 冒到主循环（它不在主循环的 ``try`` 里）
        # ⇒ **失败收尾把刚打开的社区关掉**。实跑原文：
        # ``14:50:10执行点击 enter_community → 14:50:13 收尾=人还在社区竖屏页面里``，
        # 最后一行是 ``运行失败 模式=community 原因=画面宽高比与模板基准不一致``。
        #
        # 为什么放行是对的：这些弹窗是**游戏主界面**的弹窗，竖屏段是游戏内
        # H5（社区），**根本不会有它们**；而竖屏段自己的弹窗（签到成功、
        # 兑换成功、网络异常）由 ``community_pages`` 那套 1080x1920 判据管。
        #
        # ⚠️ 2026-10-07 新接的「网页网络错误」（``web_network_error``）同样够不到竖屏：
        # 那条长条长在**横屏**的游戏内 WebView 上（网页活动列表 1982x1132）。
        # 社区那半边的竖屏 H5 报网络异常是**另一张脸**（整页「网络连接异常，下拉刷新」），
        # 归 ``community`` 路线管。别把两者当成一个。
        #
        # ⚠️ 判据是**画面自身的高宽比**，不依赖任何外部状态 ⇒ 窗口一进竖屏
        # 它就自动停手，通道切回横屏后自动恢复。
        height, width = screen.shape[:2]
        if width < height:
            return screen, False

        stable_frames = 0
        clicks = 0
        last_click_at: float | None = None
        handled = False
        active_popup: str | None = None
        while True:
            match, popup, action, diagnostic_label, failure_message = self._find_popup(screen)
            if match is None:
                return screen, handled
            handled = True
            if popup != active_popup:
                active_popup = popup
                stable_frames = 1
                clicks = 0
                last_click_at = None
            else:
                stable_frames += 1
            current = self.now()
            if stable_frames >= 2:
                # 点击预算 _MAX_POPUP_CLICKS 次，间隔 3 秒；模拟器卡顿会吞掉
                # 转场期间的输入，多给几次机会。末次点击后 15 秒仍无改善才熔断。
                if (
                    last_click_at is None
                    or (
                        clicks < _MAX_POPUP_CLICKS
                        and current - last_click_at >= self.retry_interval_seconds
                    )
                ):
                    runtime.click(match.center, action)
                    clicks += 1
                    last_click_at = current
                elif (
                    clicks >= _MAX_POPUP_CLICKS
                    and last_click_at is not None
                    and current - last_click_at >= self.failure_seconds
                ):
                    path = (
                        runtime.save_diagnostic(diagnostic_label, screen)
                        if runtime.diagnostic_dir is not None
                        else "not-configured"
                    )
                    raise RuntimeError(
                        f"{failure_message}；已保存诊断 {path}"
                    )
            self.sleep(self.poll_seconds)
            screen = runtime.capture_unguarded()


# ---------------------------------------------------------------------------
# 2026-11-03 新增两条：游戏内「变更日期」「获得登录奖励」弹窗
#
# 两条都是**游戏自己按时间弹**的模态通知窗，谁在跑都会撞上：
#   * 「变更日期：日期变更，将前往大厅。」—— 会把当前页面强制切回大厅；
#   * 「获得登录奖励」—— 每日首次登录的 6 格奖励，底部「点击关闭」。
#
# 死法（2026-11-03 主线实跑，两条各犯一次）：
#   * 18:00:42 变更日期弹窗 ⇒ 主线在「等待通关」上干等 46 秒无进展 ⇒ 超时放弃；
#   * 18:01:57 登录奖励弹窗 ⇒ 收尾连按 2 次 ESC 页面不动（这层不吃 ESC）⇒「回首页失败」。
#   两个页面都没登记 ⇒ guard 每帧过也看不见 ⇒ 只能等到超时。
#
# 判据口径沿用既有约定：**标题排他 + 关闭点只负责定位**。
# 标题跨页排他实测（全库 364 张夹具，2026-11-03）：
#   date_change_title 最高 0.5517（阈 0.82，余量 0.27）
#   login_reward_title 最高 0.5703（阈 0.82，余量 0.25）
# ⚠️ 「点击关闭」这四个字**完全不排他**（游戏里通用灰字控件，reward_popup 那批 0.9），
# 所以它绝不能单独当判据；这里只用来确定「点哪」。
# ⚠️ 标题在、关闭点找不到 ⇒ 返回 None **不动手**：这两层都是「必须点关闭」型，
# 屏幕中心底下就是奖励格子（点下去可能领掉东西），不许拿一个猜的坐标顶上。
# ---------------------------------------------------------------------------

# 两页的 ROI 都从 1982x1132 的 PC 真机帧上量：
#   标题「变更日期」208x49 落在 (857,353)；「点击关闭」138x30 落在 (892,755)。
#   标题「获得登录奖励」304x49 落在 (806,227)；「点击关闭」111x24 落在 (924,1081)。
_DATE_CHANGE_TITLE_REGION = (800, 320, 400, 120)
# 「骑士团活动」页：标题在左上角（实测 bbox 103,152 215x42），关闭在底部中间偏右
# （实测 bbox 933,1082 92x21）。两个区域都留了一圈余量。
_KNIGHTS_ACTIVITY_TITLE_REGION = (60, 120, 340, 110)
_KNIGHTS_ACTIVITY_CLOSE_REGION = (820, 1040, 400, 80)
# 「无法控制」剧情弹窗：标题居中（实测 bbox 872,175 约 190x48），关闭在弹窗底部
# —— 与「骑士团活动」那颗「点击关闭」是同一个控件（实测都命中 (933,1082) 92x21）。
_UNCONTROLLABLE_TITLE_REGION = (820, 150, 340, 110)
_UNCONTROLLABLE_CLOSE_REGION = (820, 1040, 400, 80)
# 「轻触后解锁」教学遮罩（2026-11-06 主线 Episode 4 第 11 关）：
#   黑框左半实测 bbox 880,810 260x170；右上「跳过教学」按钮 1605,50 315x100；
#   底部被高亮的图标 1050,975 160x140。三块区域都留了一圈余量。
_TUTORIAL_TITLE_REGION = (850, 780, 620, 230)
_TUTORIAL_SKIP_REGION = (1580, 30, 400, 150)
_TUTORIAL_HIGHLIGHT_REGION = (1020, 950, 240, 182)
# 高亮框有呼吸动画：4 张正例 0.7894~1.0000，全库反例最高 0.6148。
# 它**只定位点击点、不参与判据**，所以给 0.70；判据仍是 title 的 0.82。
_TUTORIAL_HIGHLIGHT_THRESHOLD = 0.70
_DATE_CHANGE_CLOSE_REGION = (800, 720, 400, 110)
_LOGIN_REWARD_TITLE_REGION = (760, 190, 480, 120)
_LOGIN_REWARD_CLOSE_REGION = (860, 1040, 280, 90)
# 标题门槛 0.82：与 friendship / side_story_notice 同档；跨页最高 0.5703，余量 0.25。
_GAME_NOTICE_TITLE_THRESHOLD = 0.82
# 关闭点门槛 0.85：它只定位、不判定，正例自匹配 1.0000，留 0.15 抗渲染差异。
_GAME_NOTICE_CLOSE_THRESHOLD = 0.85


def load_date_change_templates(template_dir: Path) -> DateChangeTemplates:
    title = template_dir / "date_change_title.png"
    close = template_dir / "date_change_close.png"
    if not (title.exists() and close.exists()):
        return DateChangeTemplates(title=None, close=None)
    return DateChangeTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def load_login_reward_templates(template_dir: Path) -> LoginRewardTemplates:
    title = template_dir / "login_reward_title.png"
    close = template_dir / "login_reward_close.png"
    if not (title.exists() and close.exists()):
        return LoginRewardTemplates(title=None, close=None)
    return LoginRewardTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def _find_titled_popup_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
    title_region: tuple[int, int, int, int],
    close_region: tuple[int, int, int, int],
) -> Match | None:
    """标题成立且关闭点定位得到 ⇒ 返回关闭点；任一不成立 ⇒ None（不动手）。"""
    title = find_template(
        screen,
        title_template,
        _GAME_NOTICE_TITLE_THRESHOLD,
        region=title_region,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _GAME_NOTICE_CLOSE_THRESHOLD,
        region=close_region,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def load_uncontrollable_templates(template_dir: Path) -> UncontrollableTemplates:
    title = template_dir / "uncontrollable_title.png"
    close = template_dir / "uncontrollable_close.png"
    if not (title.exists() and close.exists()):
        return UncontrollableTemplates(title=None, close=None)
    return UncontrollableTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def find_uncontrollable_close(
    screen: np.ndarray,
    templates: UncontrollableTemplates,
) -> Match | None:
    """「无法控制」弹窗底部「✕ 点击关闭」；标题不成立就不动手。"""
    if templates.title is None or templates.close is None:
        return None
    return _find_titled_popup_close(
        screen,
        templates.title,
        templates.close,
        _UNCONTROLLABLE_TITLE_REGION,
        _UNCONTROLLABLE_CLOSE_REGION,
    )


def load_tutorial_unlock_templates(template_dir: Path) -> TutorialUnlockTemplates:
    """三张图都在 ``global/pc/``；模拟器口径下一张都找不到 ⇒ 整段跳过。"""
    title = template_dir / "tutorial_unlock_title.png"
    skip = template_dir / "tutorial_skip_button.png"
    highlight = template_dir / "tutorial_highlight_icon.png"
    if not title.exists():
        return TutorialUnlockTemplates(title=None, skip=None, highlight=None)
    confirm = template_dir / "tutorial_skip_confirm.png"
    return TutorialUnlockTemplates(
        title=load_template(str(title)),
        skip=load_template(str(skip)) if skip.exists() else None,
        highlight=load_template(str(highlight)) if highlight.exists() else None,
        confirm=load_template(str(confirm)) if confirm.exists() else None,
    )


def load_tutorial_skip_templates(template_dir: Path) -> TutorialSkipTemplates:
    """大厅右上角「跳过教学 ✕」。两张图都在 ``global/pc/`` ⇒ 模拟器整段跳过。"""
    button = template_dir / "tutorial_skip_button.png"
    confirm = template_dir / "tutorial_skip_confirm.png"
    if not button.exists() or not confirm.exists():
        return TutorialSkipTemplates(button=None, confirm=None)
    return TutorialSkipTemplates(
        button=load_template(str(button)),
        confirm=load_template(str(confirm)),
    )


def find_tutorial_skip_point(
    screen: np.ndarray,
    templates: TutorialSkipTemplates,
) -> Match | None:
    """认「跳过教学」按钮 ⇒ 返回**那个 ✕** 的点击点；认不出 / 找不到 ✕ ⇒ None。

    判据是 ``button``（整块「跳过教学 ✕」，2026-11-06 真机 0.9861 / 阈 0.85），
    ``confirm`` 只负责「点哪儿」—— 用户明确要求点 ✕、不能点文字。
    **找不到 ✕ 就一个动作都不发**：宁可留证停住，也不点一个可能只是收起说明的位置。
    """
    if templates.button is None or templates.confirm is None:
        return None
    button = find_template(
        screen,
        templates.button,
        _GAME_NOTICE_CLOSE_THRESHOLD,
        region=_TUTORIAL_SKIP_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if button is None:
        return None
    confirm = find_template(
        screen,
        templates.confirm,
        _GAME_NOTICE_CLOSE_THRESHOLD,
        region=_TUTORIAL_SKIP_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if confirm is None:
        return None
    return Match(confirm.center, min(button.score, confirm.score))


def find_tutorial_unlock_skip(
    screen: np.ndarray,
    templates: TutorialUnlockTemplates,
) -> Match | None:
    """认出「轻触后解锁」遮罩 ⇒ 返回可点的关闭点；认不出 / 定位不到 ⇒ None。

    判据只有 ``title`` 一颗（黑框左半，排他）。``skip`` / ``highlight`` **只决定点哪**：
    优先点右上角「跳过教学 ✕」，找不到再点黑框箭头指向的高亮图标。两个都定位
    不到就保守不动手 —— 绝不退回猜出来的坐标。
    """
    if templates.title is None:
        return None
    title = find_template(
        screen,
        templates.title,
        _GAME_NOTICE_TITLE_THRESHOLD,
        region=_TUTORIAL_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    if templates.skip is not None:
        skip = find_template(
            screen,
            templates.skip,
            _GAME_NOTICE_CLOSE_THRESHOLD,
            region=_TUTORIAL_SKIP_REGION,
            reference_size=_REFERENCE_SIZE,
        )
        if skip is not None:
            # 点击点以那块按钮里的 **✕** 为准（用户 2026-11-06 明确「要点那个叉叉
            # 才行」）。整块按钮 315 宽、中心落在「跳过教学」四个字上 —— 点文字只是
            # 展开/收起说明，结束不了教学。✕ 定位不到时才退回中心（旧的保守行为）。
            if templates.confirm is not None:
                confirm = find_template(
                    screen,
                    templates.confirm,
                    _GAME_NOTICE_CLOSE_THRESHOLD,
                    region=_TUTORIAL_SKIP_REGION,
                    reference_size=_REFERENCE_SIZE,
                )
                if confirm is not None:
                    return Match(
                        confirm.center,
                        min(title.score, skip.score, confirm.score),
                    )
            return Match(skip.center, min(title.score, skip.score))
    if templates.highlight is not None:
        highlight = find_template(
            screen,
            templates.highlight,
            _TUTORIAL_HIGHLIGHT_THRESHOLD,
            region=_TUTORIAL_HIGHLIGHT_REGION,
            reference_size=_REFERENCE_SIZE,
        )
        if highlight is not None:
            return Match(highlight.center, min(title.score, highlight.score))
    return None


def load_knights_activity_templates(template_dir: Path) -> KnightsActivityTemplates:
    title = template_dir / "knights_activity_title.png"
    close = template_dir / "knights_activity_close.png"
    if not (title.exists() and close.exists()):
        return KnightsActivityTemplates(title=None, close=None)
    return KnightsActivityTemplates(
        title=load_template(str(title)),
        close=load_template(str(close)),
    )


def find_knights_activity_close(
    screen: np.ndarray,
    templates: KnightsActivityTemplates,
) -> Match | None:
    """「骑士团活动」页底部的「✕ 点击关闭」；标题不成立就不动手。"""
    if templates.title is None or templates.close is None:
        return None
    return _find_titled_popup_close(
        screen,
        templates.title,
        templates.close,
        _KNIGHTS_ACTIVITY_TITLE_REGION,
        _KNIGHTS_ACTIVITY_CLOSE_REGION,
    )


def find_date_change_close(
    screen: np.ndarray,
    templates: DateChangeTemplates,
) -> Match | None:
    """「日期变更，将前往大厅。」弹窗的「点击关闭」。"""
    if templates.title is None or templates.close is None:
        return None
    return _find_titled_popup_close(
        screen,
        templates.title,
        templates.close,
        _DATE_CHANGE_TITLE_REGION,
        _DATE_CHANGE_CLOSE_REGION,
    )


def find_login_reward_close(
    screen: np.ndarray,
    templates: LoginRewardTemplates,
) -> Match | None:
    """「获得登录奖励」弹窗的「点击关闭」。"""
    if templates.title is None or templates.close is None:
        return None
    return _find_titled_popup_close(
        screen,
        templates.title,
        templates.close,
        _LOGIN_REWARD_TITLE_REGION,
        _LOGIN_REWARD_CLOSE_REGION,
    )
