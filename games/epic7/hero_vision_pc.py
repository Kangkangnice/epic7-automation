"""PC 专属：英雄合成「刻印记忆」红点判据（2026-11-08）。

## 这次修的是哪一次事故

11-08 16:41 每日任务跑到英雄合成，日志连着两行
「当前英雄非SSS但刻印按钮无红点，跳过」把有红点的卡翻了过去，
16:41:34 又突然认出红点并合成 —— 同一轮里时好时坏，不是整条路线不会合成。

## 本质原因

``HeroVisionMixin._red_dot_present`` 的几何口径是按**模拟器**标框收紧的：
``_REDDOT_ZONE=(1030,942,32,35)``，且 ``is_centered_dot`` 要求色块四周各留
3px、尺寸 10~28。模拟器红点实测 ``(1038,949,18,19)``，稳稳落在框内。

PC 客户端把同一颗红点画得**更大、更靠左上**，静止态实测
``(1030,942,26~29,26)``；红点左边还有一条同色橙棕色斜带（立绘边框装饰）
与它连成一片 ⇒ boundingRect 贴到判据窗左上边界，``local_x=0/local_y=0``
直接被 3px 内缩规则否决。翻卡动画中间那一瞬斜带分离、圆点缩到
``(1038,949,18,19)``，才「碰巧」被认出来 —— 这就是时好时坏的原因：

```
switch_before   (静止)  blob=(1030,942,28,26)  _red_dot_present=False
switch_departure(动画)  blob=(1038,949,18,19)  _red_dot_present=True
switch_final    (静止)  blob=(1030,942,28,26)  _red_dot_present=False
```

颜色没问题（H 7~22 / S 120~255 / V 120~237，zone 内 364~503 个橙红像素），
**是几何位置被模拟器窗口裁掉了**，不是识别不稳定，更不是业务逻辑变化。

## 为什么不是「放宽 zone / 调像素阈值」

全库 2983 帧审计：战斗、剧情、大厅页在同一坐标有整片暖色 UI
（zone 内橙红像素 1100+），单纯加一条「像素数够多」会在这些帧上误报。
模板匹配是能证伪的图形锚点：PC 静止态正例 0.9177~1.0000，
非红点全库最高约 0.51，阈 0.80 两侧余量分别 0.12 / 0.29。

## 边界（移植项目硬约束）

- **不改公共业务逻辑**：``hero_synthesis.py`` / ``hero_vision.py`` 一行不动，
  ``_REDDOT_ZONE``、HSV 区间、``is_centered_dot`` 保持模拟器口径。
- **平台差异收敛到图片**：新判据图只放 ``templates/hero/pc/``。
- **PC 单独留口**：唯一装配点是 ``modes.py::_build_hero_synthesis`` 里的
  ``if is_pc(template_root)``；模拟器实例连这个方法都不会被装上去。
- 原判据为真时直接短路，PC 判据**只补漏**、不改写既有结论。
- 判据图缺失直接抛错（fail closed），绝不静默降级成「没红点」。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from auto_game_unified.core.matcher import find_template, load_template

_REFERENCE_SIZE = (1982, 1132)
# 比 _REDDOT_ZONE 外扩一圈：PC 静止态红点会顶到原框左上边界，
# 搜索区必须留出容纳整颗圆点的余量。
_REGION = (1016, 928, 60, 60)
_THRESHOLD = 0.80
_TEMPLATE_NAME = "imprint_red_dot.png"


def load_pc_red_dot_template(template_root) -> np.ndarray:
    """加载 PC 专属红点图。文件不在就抛错，不返回 None、不静默跳过。"""
    path = Path(str(template_root)) / "hero" / "pc" / _TEMPLATE_NAME
    return load_template(str(path))


def pc_red_dot_match(screen: np.ndarray, template: np.ndarray):
    """在固定区域里量 PC 红点图的分数（不套阈值，供取证/测试用）。"""
    return find_template(
        screen,
        template,
        -1.0,
        region=_REGION,
        reference_size=_REFERENCE_SIZE,
    )


def install_pc_red_dot_vision(machine, template_root):
    """给**这一台 PC 实例**装上红点补判据；返回同一实例，方便链式装配。

    包装的是 ``_red_dot_present`` 而不是 ``next_action``：状态机原有的
    两帧稳定确认、页面判定、SSS 保护、动作契约全都原样复用，
    这里只回答「这颗红点在不在」。
    """
    template = load_pc_red_dot_template(template_root)
    if getattr(machine, "_pc_red_dot_vision_installed", False):
        return machine

    original = machine._red_dot_present

    def _red_dot_present_with_pc(screen: np.ndarray) -> bool:
        if original(screen):
            return True
        return (
            find_template(
                screen,
                template,
                _THRESHOLD,
                region=_REGION,
                reference_size=_REFERENCE_SIZE,
            )
            is not None
        )

    machine._red_dot_present = _red_dot_present_with_pc
    machine._pc_red_dot_vision_installed = True
    return machine
