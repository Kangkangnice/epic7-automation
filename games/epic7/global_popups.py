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
    """

    message: np.ndarray
    message_alt: np.ndarray | None = None


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
    return NetworkReconnectTemplates(
        message=load_template(str(template_dir / "network_message.png")),
        message_alt=(load_template(str(alt_message)) if alt_message.exists() else None),
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
    """
    for message_template in (templates.message, templates.message_alt):
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
        knights_signin_templates: KnightsSigninTemplates | None = None,
        gift_support_templates: GiftSupportTemplates | None = None,
        knights_weekly_reward_templates: KnightsWeeklyRewardTemplates | None = None,
        worldboss_support_reward_templates: WorldBossSupportRewardTemplates
        | None = None,
        pet_gift_templates: PetGiftTemplates | None = None,
        web_network_error_templates: WebNetworkErrorTemplates | None = None,
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
        self.knights_signin_templates = knights_signin_templates
        self.gift_support_templates = gift_support_templates
        self.knights_weekly_reward_templates = knights_weekly_reward_templates
        self.worldboss_support_reward_templates = worldboss_support_reward_templates
        self.pet_gift_templates = pet_gift_templates
        self.web_network_error_templates = web_network_error_templates
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
