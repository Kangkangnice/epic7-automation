"""刷新英雄分类表（职业 / 属性 / 星级）。

⚠️ 本工具只能给**图鉴库里已有头像**的英雄归类。新英雄上线且图鉴库还没有图时，
先用 ``tools/add_hero.py`` 补头像与条目，再回来跑这里复核
（步骤见 ``docs/maintenance/hero_roster.md`` 第二节）。

分类表是**快照**：游戏出新英雄、图鉴库补了新头像之后，这张表不会自己变，
新英雄会一直落在「未收录分类」。所以刷新必须是一条能反复执行的命令，
而不是当初手工跑一次。

用法（在 ``auto_game`` 工作区根目录，用项目的虚拟环境）：

    python -m auto_game_unified.tools.refresh_hero_meta --check
    python -m auto_game_unified.tools.refresh_hero_meta --write

``--check`` 只比对、打印报告；``--write`` 才落盘。两种模式都会把外部英雄库页面
与头像抓到 ``runtime_logs/hero_avatars`` 复用，第二次运行不再重复下载。

判据（与建表时一致）：RANSAC 内点 >= 20，且 >= 2 倍第二名。低于门槛的一律不写入 ——
宁可留「未收录分类」，也不按名字猜一个分类：按名字对齐会整批串行，因为图鉴库的名字
来自图鉴页识别，存在错字（实测名为「岚」的头像实为 Ken、「亚敏」实为 Aki）。

写回策略：**只补不删**。新抓到的条目里没有覆盖到的旧条目一律保留；与旧值冲突的条目
默认保留旧值并列进报告的「冲突」一节，确认无误后加 ``--force`` 才用新值覆盖。
一次网络异常不应把已有的分类抹成未收录。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.data_paths import data_root
from auto_game_unified.games.epic7.hero_catalog import META_FILENAME
from auto_game_unified.games.epic7.hero_match import default_library_dir, library_names

SOURCE_URL = "https://epic7db.com/heroes"
USER_AGENT = "Mozilla/5.0"

# 单个头像比对时参与评分的特征上限。与建表那次保持一致，便于结果可复现。
ORB_FEATURES = 1200
RATIO_TEST = 0.75
RANSAC_REPROJ = 5.0
MIN_GOOD = 40
MIN_INLIERS = 20
RIVAL_RATIO = 2

JOB_ZH = {
    "Warrior": "战士",
    "Knight": "骑士",
    "Thief": "盗贼",
    "Ranger": "射手",
    "Mage": "魔导士",
    "Soul Weaver": "精灵师",
}
ELEMENT_ZH = {"Fire": "火", "Ice": "水", "Earth": "木", "Light": "光", "Dark": "暗"}

CARD_RE = re.compile(
    r'<li class="hero"\s+data-name="([^"]+)"\s+data-class="([^"]+)"\s+'
    r'data-element="([^"]+)"\s+data-stars="([^"]+)"[^>]*>(.*?)</li>',
    re.S,
)
AVATAR_RE = re.compile(r'class="hero-avatar"\s+src="([^"]+)"')


def cache_dir() -> Path:
    """头像缓存。

    放在运行产物目录下的 ``runtime_logs/`` 里，源码运行时就是仓库里的
    ``auto_game_unified/runtime_logs/hero_avatars``（该目录已被忽略）；
    直接放 ``data_root()`` 会把几百张图丢进包目录，污染工作区。
    """

    path = data_root() / "runtime_logs" / "hero_avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open(url: str, timeout: int = 40):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_catalog(url: str) -> list[dict]:
    """抓外部英雄库。页面是服务端渲染的，卡片带 data-* 属性，直接解析即可。"""

    with _open(url) as response:
        html = response.read().decode("utf-8", errors="replace")
    heroes: list[dict] = []
    for name, job, element, stars, body in CARD_RE.findall(html):
        avatar = AVATAR_RE.search(body)
        if not avatar or job not in JOB_ZH or element not in ELEMENT_ZH:
            continue
        heroes.append(
            {
                "name": name,
                "job": JOB_ZH[job],
                "element": ELEMENT_ZH[element],
                "stars": int(stars),
                "avatar": _absolute(avatar.group(1), url),
            }
        )
    return heroes


def _absolute(src: str, page_url: str) -> str:
    if src.startswith("http"):
        return src
    match = re.match(r"(https?://[^/]+)", page_url)
    host = match.group(1) if match else "https://epic7db.com"
    return host + src


def download_avatars(heroes: list[dict]) -> dict[str, Path]:
    """按英雄名落盘；已存在的跳过。返回 名字 -> 本地文件。"""

    folder = cache_dir()
    saved: dict[str, Path] = {}
    downloaded = 0
    for hero in heroes:
        if not hero.get("avatar"):
            continue
        target = folder / (re.sub(r"[^A-Za-z0-9_\-]", "_", hero["name"]) + ".webp")
        if not target.exists() or target.stat().st_size == 0:
            try:
                with _open(hero["avatar"], timeout=30) as response:
                    target.write_bytes(response.read())
                downloaded += 1
                time.sleep(0.15)
            except Exception as exc:  # noqa: BLE001 离线工具，按条记录后继续
                print(f"  头像下载失败：{hero['name']}（{exc}）")
                continue
        saved[hero["name"]] = target
    print(f"头像：本次下载 {downloaded} 张，可用 {len(saved)} 张")
    return saved


def _imread(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _center_crop(image: np.ndarray, ratio: float = 0.78) -> np.ndarray:
    height, width = image.shape[:2]
    side = int(min(height, width) * ratio)
    y0 = (height - side) // 2
    x0 = (width - side) // 2
    return image[y0:y0 + side, x0:x0 + side]


class Matcher:
    """把图鉴库头像与外部英雄头像逐一比对。

    方向和运行时相反：这里外部头像是模板、图鉴库头像是待判定目标。
    运行时只读分类表，不再做比对，所以这段逻辑只服务本工具。
    """

    def __init__(self, avatars: dict[str, Path], heroes: dict[str, dict]) -> None:
        self._orb = cv2.ORB_create(
            nfeatures=ORB_FEATURES, edgeThreshold=5, patchSize=31
        )
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._templates: list[tuple[str, list, np.ndarray]] = []
        for name, path in avatars.items():
            image = _imread(path)
            if image is None:
                continue
            image = _center_crop(
                cv2.resize(image, (128, 128), interpolation=cv2.INTER_AREA)
            )
            keypoints, desc = self._orb.detectAndCompute(image, None)
            if desc is None:
                continue
            self._templates.append((name, keypoints, desc))
        self._heroes = heroes

    def best(self, probe: np.ndarray) -> tuple[str, int, int] | None:
        keypoints, desc = self._orb.detectAndCompute(probe, None)
        if desc is None:
            return None
        scored: list[tuple[int, int, str]] = []
        for name, template_keypoints, template_desc in self._templates:
            matches = self._bf.knnMatch(desc, template_desc, k=2)
            good = [
                pair[0]
                for pair in matches
                if len(pair) == 2 and pair[0].distance < RATIO_TEST * pair[1].distance
            ]
            inliers = 0
            if len(good) >= 8:
                src = np.float32([keypoints[m.queryIdx].pt for m in good])
                dst = np.float32([template_keypoints[m.trainIdx].pt for m in good])
                homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_REPROJ)
                if homography is not None and mask is not None:
                    inliers = int(mask.sum())
            scored.append((inliers, len(good), name))
        scored.sort(reverse=True)
        if not scored:
            return None
        best_inliers, best_good, best_name = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0
        return best_name, best_inliers, second


def build_table(library: Path, matcher: Matcher, heroes: dict[str, dict]) -> dict[str, dict]:
    names = library_names(library)
    table: dict[str, dict] = {}
    rejected: list[str] = []
    for index, name in enumerate(names, start=1):
        image = _imread(library / f"{name}.png")
        if image is None:
            rejected.append(name)
            continue
        found = matcher.best(_center_crop(image))
        if found is None:
            rejected.append(name)
            continue
        best_name, inliers, second = found
        if inliers < MIN_INLIERS or inliers < second * RIVAL_RATIO:
            rejected.append(name)
            continue
        hero = heroes.get(best_name)
        if hero is None:
            rejected.append(name)
            continue
        table[name] = {
            "en": hero["name"],
            "job": hero["job"],
            "element": hero["element"],
            "stars": hero["stars"],
        }
        if index % 50 == 0:
            print(f"  已比对 {index}/{len(names)}")
    print(f"比对完成：{len(table)} 名已归类，{len(rejected)} 名未达门槛")
    return table


def read_existing(path: Path) -> tuple[dict[str, dict], list[str], str]:
    """读回现有表：条目表 + 上次抓到的外部英雄名单 + 上次刷新日期。"""

    if not path.is_file():
        return {}, [], ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, [], ""
    if not isinstance(payload, dict):
        return {}, [], ""
    heroes = payload.get("heroes")
    catalog = payload.get("catalog")
    fetched = payload.get("fetched_at")
    return (
        heroes if isinstance(heroes, dict) else {},
        [name for name in catalog if isinstance(name, str)] if isinstance(catalog, list) else [],
        fetched if isinstance(fetched, str) else "",
    )


def report(
    existing: dict[str, dict],
    fresh: dict[str, dict],
    *,
    previous_catalog: list[str],
    current_catalog: list[str],
    parsed: int,
) -> list[str]:
    added = sorted(set(fresh) - set(existing))
    missing = sorted(set(existing) - set(fresh))
    conflicts = sorted(
        name
        for name in set(existing) & set(fresh)
        if (existing[name].get("job"), existing[name].get("element"), existing[name].get("stars"))
        != (fresh[name]["job"], fresh[name]["element"], fresh[name]["stars"])
    )
    new_heroes = sorted(set(current_catalog) - set(previous_catalog))
    gone_heroes = sorted(set(previous_catalog) - set(current_catalog))
    lines = [
        f"外部英雄库本次 {parsed} 名，与图鉴库对上 {len(fresh)} 名",
        f"表内现有 {len(existing)} 条",
        f"新增可归类 {len(added)} 条" + (("：" + "、".join(added)) if added else ""),
        f"本次未达门槛但保留 {len(missing)} 条" + (("：" + "、".join(missing)) if missing else ""),
        f"取值冲突 {len(conflicts)} 条" + (("：" + "、".join(conflicts)) if conflicts else ""),
    ]
    if previous_catalog:
        lines.append(
            f"外部库比上次多出 {len(new_heroes)} 名"
            + (("：" + "、".join(new_heroes)) if new_heroes else "")
        )
        if gone_heroes:
            lines.append(f"外部库比上次少了 {len(gone_heroes)} 名：{'、'.join(gone_heroes)}")
    return lines


def merge(
    existing: dict[str, dict], fresh: dict[str, dict], force: bool
) -> dict[str, dict]:
    """只补不删；冲突默认保留旧值。"""

    merged = dict(existing)
    for name, value in fresh.items():
        if name in merged and not force:
            continue
        merged[name] = value
    return dict(sorted(merged.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新英雄分类表")
    parser.add_argument(
        "--check", action="store_true", help="只比对并打印报告，不写回（默认行为）"
    )
    parser.add_argument("--write", action="store_true", help="写回 meta.json")
    parser.add_argument(
        "--force", action="store_true", help="冲突时用新值覆盖旧值（默认保留旧值）"
    )
    parser.add_argument("--url", default=SOURCE_URL, help="外部英雄库地址")
    parser.add_argument(
        "--library",
        default="",
        help="图鉴库目录，默认取随包位置",
    )
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 老控制台没有 reconfigure
        pass

    library = Path(args.library) if args.library else default_library_dir()
    if not library.is_dir():
        print(f"图鉴库不存在：{library}")
        return 1

    print(f"外部英雄库：{args.url}")
    catalog = fetch_catalog(args.url)
    if not catalog:
        print("没有解析到任何英雄：页面结构可能已变，需按新结构改 CARD_RE。")
        return 1
    print(f"解析到 {len(catalog)} 名英雄")

    avatars = download_avatars(catalog)
    heroes = {hero["name"]: hero for hero in catalog}
    matcher = Matcher(avatars, heroes)
    fresh = build_table(library, matcher, heroes)

    target = library / META_FILENAME
    existing, previous_catalog, previous_date = read_existing(target)
    if previous_date:
        print(f"本地分类表建立于 {previous_date}")
    for line in report(
        existing,
        fresh,
        previous_catalog=previous_catalog,
        current_catalog=[hero["name"] for hero in catalog],
        parsed=len(catalog),
    ):
        print(line)

    if not args.write:
        print("未写入。确认无误后加 --write 落盘。")
        return 0

    merged = merge(existing, fresh, args.force)
    payload = {
        "source": f"{args.url}（{len(catalog)} 名）",
        "fetched_at": time.strftime("%Y-%m-%d"),
        "count": len(merged),
        "heroes": merged,
        "catalog": sorted(hero["name"] for hero in catalog),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"已写入 {target}，共 {len(merged)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
