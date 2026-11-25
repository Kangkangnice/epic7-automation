"""路线级最低声明：终点、覆盖层、空态、动作回执、危险动作。

这里只做**声明与纯校验**，不碰任何路线的判据与运行期行为。
规范正文在 ``docs/ROUTE_CONTRACT.md``；加载期断言在 ``modes.py``。
"""

from collections.abc import Collection
from dataclasses import dataclass

from auto_game_unified.games.epic7.global_popups import POPUP_KINDS


@dataclass(frozen=True)
class RouteContract:
    """一条路线对「活干完停在哪、会被什么挡住、点完怎么算成功」的最低表态。

    必填字段没有默认值：漏写字段与「确认没有」不是一回事。
    ``finish_note`` 只在 ``finish_at_home=False`` 时必须写。
    """

    mode: str
    terminal: str
    finish_at_home: bool
    overlays: frozenset[str]
    empty_states: tuple[str, ...]
    action_evidence: str
    finish_note: str = ""


def validate_contract(
    contract: RouteContract,
    states: Collection[str],
    popup_kinds: Collection[str] = POPUP_KINDS,
    transition_exempt: Collection[str] = (),
) -> list[str]:
    """返回声明里的问题列表；空列表表示通过。抛异常是 WP2 加载期断言的事。

    覆盖层类别默认就是全局弹窗守卫登记表；传入别的表只为测试用假数据。
    """
    problems: list[str] = []

    if contract.terminal not in states:
        problems.append(
            f"terminal={contract.terminal!r} 不在状态集合里；"
            f"合法取值：{', '.join(sorted(states)) or '(空)'}"
        )

    if not contract.finish_at_home and not contract.finish_note.strip():
        problems.append("finish_at_home=False 时 finish_note 不能为空")

    unknown_overlays = sorted(set(contract.overlays) - set(popup_kinds))
    if unknown_overlays:
        problems.append(
            f"overlays 含未登记类别 {unknown_overlays}；"
            f"合法取值：{', '.join(sorted(popup_kinds)) or '(空)'}"
        )

    unknown_empty = sorted(set(contract.empty_states) - set(states))
    if unknown_empty:
        problems.append(
            f"empty_states 含不在状态集合里的名字 {unknown_empty}；"
            f"合法取值：{', '.join(sorted(states)) or '(空)'}，或写 () 表示没有空态"
        )

    if contract.action_evidence != "transition_contract":
        if contract.mode not in transition_exempt:
            problems.append(
                f"action_evidence={contract.action_evidence!r} 既不是 'transition_contract'，"
                "这条路线也不在 TRANSITION_EXEMPT 里；回执方式必须二选一"
            )
        elif not contract.action_evidence.strip():
            problems.append(
                "在 TRANSITION_EXEMPT 里时 action_evidence 必须写清"
                "「用自己的什么机制验收」，不能为空"
            )

    return problems
