"""「解锁缘分」全局弹窗扩展（包装 ``_find_popup`` 的轻量方案，双端通用）。

为什么单独一个文件
------------------
2026-11-07 PC 主线 13:11 实跑：Episode 5 第 3 关通关后弹出「解锁缘分」通知窗
（标题「解锁缘分」+ 英雄头像 + 「已与贝洛妮卡结下缘分」+ 金色 OK 按钮），
整页盖住关卡入口 ⇒ 主线报 ``页面无进展：主线画面[跳过确认]未识别``，安全停止回家。
2026-11-22 12:12 模拟器主线也撞到同一层（角色=尤娜）⇒ 扩展为双端通用。

当初（2026-11-07）因「PC 移植不能动模拟器」的约束，判据、模板、装配都只放
``templates/global/pc/`` + 本文件，走包装守卫的路径以复用其安全机制。现在双端都要，
**保留这套轻量方案**，不再单独往 ``global_popups.py`` 加第 26 类（那要动多处写死的
构造参数测试）。所以这里：

* ``global_popups.py`` / ``story.py`` / ``arena.py`` / ``navigation.py`` 不改；
* 新判据全在本文件；模板两端各一份（见下）；
* ``main.py`` 双端都注入 ``install_pc_only_popups``（函数名是历史遗留，语义已通用）；
* 注入方式是给 ``Epic7GlobalPopupGuard`` 的 ``_find_popup`` 套一层包装，
  **复用原守卫的全部安全机制**（连续 2 帧同一弹窗才出手、点击预算、
  间隔、熔断、存诊断、抛错），不复制第二套循环、不新增第二个数字。

模板两端各一份：``templates/global/pc/`` 放 PC 字形图，``templates/global/`` 放
模拟器字形图。中文标题在两端字形不同 —— PC 图打模拟器帧只有 0.6808（阈 0.82 不过），
所以模拟器版标题按 2026-11-22 真机帧重裁。``TemplateDir`` 在 PC 下自动选 ``pc/`` 图、
模拟器下回落共享图；OK 按钮图通用，共享层一份即可。

判据（2026-11-07 全库取证，脚本 ``runtime_logs/_probe_1110_relationship_unlock.py``）
------------------------------------------------------------------------------
* 标题「解锁缘分」= **排他判据**，只裁四个字，不含会变的角色名 / 头像 / 正文。
  正例 1.0000，全库 381 张可比夹具负例最高 **0.4761**
  （``epic7_knights_donation/support_confirm.png``），阈值 0.82 ⇒ 余量 0.3439。
  其它 22 张全局弹窗夹具最高 0.4292。
* 金色 OK 按钮 = **只定位点击点**，不参与判定。正例 1.0000、中心 (957, 825)；
  在别的全局弹窗上最高 0.4124，远低于 0.85。
* 两者缺一 ⇒ 返回 None **不动手**：这层必须点 OK，屏幕中心底下是角色头像，
  不许拿一个猜的坐标顶上（``web_network_error`` 那颗 ✕ 的教训）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.games.epic7.global_popups import _MAX_POPUP_CLICKS

if TYPE_CHECKING:
    from auto_game_unified.games.epic7.global_popups import Epic7GlobalPopupGuard


_REFERENCE_SIZE = (1982, 1132)
# 从 1982x1132 的 PC 诊断帧上量：标题四字 bbox (862,310) 205x55；
# OK 按钮 bbox (805,775) 305x100。两块区域都留了一圈余量。
_TITLE_REGION = (800, 270, 420, 130)
_OK_REGION = (760, 730, 480, 180)
# 与 ``global_popups._GAME_NOTICE_TITLE_THRESHOLD`` / ``_CLOSE_THRESHOLD`` 同档，
# 不另立口径：负例余量 0.3439 / 0.4376，无需调阈值。
_TITLE_THRESHOLD = 0.82
_OK_THRESHOLD = 0.85


@dataclass(frozen=True)
class RelationshipUnlockTemplates:
    """「解锁缘分」弹窗（PC 专属）。

    ``title`` = 排他锚点；``ok`` = 点击点。两个字段都允许 ``None``
    —— 模拟器加载不到 ``pc/`` 图时就是全 ``None``，整层直接跳过。
    """

    title: np.ndarray | None
    ok: np.ndarray | None


def load_relationship_unlock_templates(template_dir) -> RelationshipUnlockTemplates:
    """按传入目录加载：PC 传 TemplateDir 自动选 pc/ 图，模拟器传普通 Path 用共享图。"""
    title = template_dir / "relationship_unlock_title.png"
    ok = template_dir / "relationship_unlock_ok.png"
    if not (title.exists() and ok.exists()):
        return RelationshipUnlockTemplates(title=None, ok=None)
    return RelationshipUnlockTemplates(
        title=load_template(str(title)),
        ok=load_template(str(ok)),
    )


def find_relationship_unlock_ok(
    screen: np.ndarray,
    templates: RelationshipUnlockTemplates,
) -> Match | None:
    """认出「解锁缘分」⇒ 返回 OK 的点击点；任一锚点不成立 ⇒ None（不动手）。"""
    if templates.title is None or templates.ok is None:
        return None
    title = find_template(
        screen,
        templates.title,
        _TITLE_THRESHOLD,
        region=_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    ok = find_template(
        screen,
        templates.ok,
        _OK_THRESHOLD,
        region=_OK_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if ok is None:
        return None
    return Match(ok.center, min(title.score, ok.score))


def install_pc_only_popups(
    guard: "Epic7GlobalPopupGuard",
    template_dir,
) -> "Epic7GlobalPopupGuard":
    """把 PC 专属弹窗挂到既有守卫的判据链最前面，返回**同一个 guard 对象**。

    ⚠️ 只在 ``main.py`` 的 ``is_pc(template_root)`` 分支调用。模拟器下：
    ① 这个函数根本不会被调用；② 即便调用，两张 ``pc/`` 图不存在 ⇒
    立即 ``return guard``，守卫的 ``_find_popup`` 原封不动。

    包装的是 ``_find_popup`` 而不是 ``__call__``：前者只回答「现在是哪层弹窗、
    点哪、叫什么、失败怎么报」，后者负责连续两帧确认 / 点击预算 / 熔断 / 存诊断。
    挂在前者的返回值契约上，等于让新弹窗**完全继承**既有安全机制，不需要复制
    一套循环，也不会引入第二个「最多点几次」的常量。
    """
    templates = load_relationship_unlock_templates(template_dir)
    if templates.title is None:
        return guard
    # 防重入：同一实例重复安装会套出多层闭包（虽然 main.py 只调一次）。
    if getattr(guard, "_pc_only_popups_installed", False):
        return guard

    original_find_popup = guard._find_popup

    def _find_popup_with_pc_only(screen: np.ndarray):
        match = find_relationship_unlock_ok(screen, templates)
        if match is not None:
            return (
                match,
                "relationship_unlock",
                "dismiss-relationship-unlock",
                "relationship_unlock_failed",
                f"「解锁缘分」弹窗点击{_MAX_POPUP_CLICKS}次后仍未消失",
            )
        return original_find_popup(screen)

    guard._find_popup = _find_popup_with_pc_only
    guard._pc_only_popups_installed = True
    return guard
