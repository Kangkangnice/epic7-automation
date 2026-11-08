"""PC 专属全局弹窗扩展（**模拟器一条新代码都不会走到**）。

为什么单独一个文件
------------------
2026-11-07 主线 13:11 实跑：Episode 5 第 3 关通关后弹出「解锁缘分」通知窗
（标题「解锁缘分」+ 英雄头像 + 「已与贝洛妮卡结下缘分」+ 金色 OK 按钮），
整页盖住关卡入口 ⇒ 主线报 ``页面无进展：主线画面[跳过确认]未识别``，
安全停止并回家。它不在既有 23 类全局弹窗里，守卫每帧过也看不见。

用户 2026-11-07 对移植项目定的硬约束：**所有改动只能在 PC 里，不能影响模拟器，
不能改公共地方，要给 PC 单独留个口，模拟器完全不动**。所以这里：

* ``global_popups.py`` / ``story.py`` / ``arena.py`` / ``navigation.py``
  **一个字节都不改**；
* 新判据、新模板、新装配全在本文件 + ``templates/global/pc/``；
* ``main.py`` 只有一处 ``if is_pc(template_root):`` 注入，模拟器分支不执行；
* 注入方式是给 ``Epic7GlobalPopupGuard`` 的 ``_find_popup`` 套一层包装，
  **复用原守卫的全部安全机制**（连续 2 帧同一弹窗才出手、点击预算、
  间隔、熔断、存诊断、抛错），不复制第二套循环、不新增第二个数字。

模板只在 ``templates/global/pc/`` 下：模拟器口径下 ``TemplateDir`` 回落
到 ``templates/global/``，两张图都不存在 ⇒ ``load_relationship_unlock_templates``
返回全 ``None`` ⇒ 即便误调用，``install_pc_only_popups`` 也原样返回守卫。

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
    """两张图只在 ``global/pc/``；模拟器口径下一张都找不到 ⇒ 全 None。"""
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
