"""Small, immutable descriptions for route-specific visual evidence."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping


class EvidenceState(Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AtomEvidence:
    key: str
    template_path: str
    region: tuple[int, int, int, int]
    threshold: float
    description: str = ""
    required: bool = True
    reference_size: tuple[int, int] = (1982, 1132)
    # 同一个控件的**其它长相**（相对 template_root 的路径）。默认空 ⇒ 绝大多数锚点
    # 仍是单模板。目前唯一使用者是大厅「秘密商店」入口：商店有未读内容时入口图标上
    # 会盖一块红 N 角标，与干净模板的相似度只有 ~0.81（门槛 0.82）⇒ 会被判成
    # 「锚点缺失」把整条路线打挂（详见 evidence/shop_refresh.py 的常量注释）。
    # 判定语义：**任一候选过阈即算命中**，命中取过阈候选中分数最高的那个。
    alt_template_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class AtomObservation:
    key: str
    template: str
    config: str
    region: tuple[int, int, int, int]
    reference_size: tuple[int, int]
    threshold: float
    observed: bool
    score: float | None
    center: tuple[int, int] | None


@dataclass(frozen=True)
class PageEvidence:
    key: str
    required: tuple[str, ...] = ()
    any_of: tuple[tuple[str, ...], ...] = ()
    forbidden: tuple[str, ...] = ()

    def evaluate(self, observations: Mapping[str, bool]) -> EvidenceState:
        if any(observations.get(key, False) for key in self.forbidden):
            return EvidenceState.UNSAFE
        if not all(observations.get(key, False) for key in self.required):
            return EvidenceState.UNKNOWN
        if not all(
            any(observations.get(key, False) for key in group)
            for group in self.any_of
        ):
            return EvidenceState.UNKNOWN
        return EvidenceState.SAFE


@dataclass(frozen=True)
class EvidenceProfile:
    atoms: Mapping[str, AtomEvidence]
    pages: tuple[PageEvidence, ...] = ()
    page_evaluator: Callable[
        [Mapping[str, AtomObservation]], Mapping[str, EvidenceState]
    ] | None = None
    config_path: str = ""
    template_root: Path | None = None

    def atom(self, key: str) -> AtomEvidence:
        return self.atoms[key]

    def page(self, key: str) -> PageEvidence:
        for page in self.pages:
            if page.key == key:
                return page
        raise KeyError(key)

    def evaluate_pages(
        self, observations: Mapping[str, AtomObservation]
    ) -> dict[str, EvidenceState]:
        if self.page_evaluator is not None:
            return dict(self.page_evaluator(observations))
        flags = {key: item.observed for key, item in observations.items()}
        return {page.key: page.evaluate(flags) for page in self.pages}


def validate_profile(profile: EvidenceProfile, root: Path) -> list[str]:
    errors: list[str] = []
    atom_keys = set(profile.atoms)

    for key, atom in profile.atoms.items():
        path = root / atom.template_path
        if atom.required and not path.is_file():
            errors.append(f"{key}: 模板不存在: {path}")
        if not 0.0 <= atom.threshold <= 1.0:
            errors.append(f"{key}: 阈值必须在 0 到 1 之间: {atom.threshold}")
        if len(atom.region) != 4:
            errors.append(f"{key}: 搜索区域必须包含 x,y,width,height")
            continue
        x, y, width, height = atom.region
        ref_width, ref_height = atom.reference_size
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            errors.append(f"{key}: 搜索区域必须为非负且宽高大于零: {atom.region}")
        elif x >= ref_width or y >= ref_height:
            errors.append(
                f"{key}: 搜索区域起点超出基准画面 {atom.reference_size}: {atom.region}"
            )

    page_keys: set[str] = set()
    for page in profile.pages:
        if page.key in page_keys:
            errors.append(f"页面键重复: {page.key}")
        page_keys.add(page.key)
        references = (*page.required, *page.forbidden, *(key for group in page.any_of for key in group))
        for reference in references:
            if reference not in atom_keys:
                errors.append(f"{page.key}: 引用不存在: {reference}")
    return errors
