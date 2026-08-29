"""一次性抓取主页展示图（表情包封面 + 收藏集封面）到 `static/showcase/`。

**不是运行时代码**：主页只读本地文件、零网络请求。只有需要更新素材时才手工跑一次，
产物（图片 + manifest.json）随代码入库。

用法：
    uv run python scripts/fetch_showcase.py                 # 默认：全量表情包前 8 个 + 搜「2233」
    uv run python scripts/fetch_showcase.py --keyword 小电视
    uv run python scripts/fetch_showcase.py --emoji-ids 53 105 --emoji-count 2
    uv run python scripts/fetch_showcase.py --dry-run       # 只打印要抓什么，不下载

表情包来源：`--emoji-ids` 显式给则用它；否则有 Cookie 时走 `all_packages()` 取前 N 个包；
都没有则退回示例 ID 53。每个包取 `emote[0].url`（**跳过 gif_url，展示图要静态**），
取不到退回包封面 `pkg.url`。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtWidgets import QApplication

# app.common.config 会构造 QConfig（QObject）；先建 QApplication 与 main.py 保持一致
app = QApplication(sys.argv)

from biliemoji import BiliClient, Emoji
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from app.common.config import cfg
from app.common.proxy import parse_proxy
from app.common.resource import SHOWCASE_DIR, SHOWCASE_MANIFEST
from app.components import api_cache
from app.components.dress_helpers import is_collection

_EMOJI_SIZE = 128  # 表情：正方形边长
_COLL_WIDTH = 144  # 收藏集封面：3:4 竖版宽度
_COLL_RATIO = 4 / 3  # 高 / 宽
_JPEG_QUALITY = 85
_FALLBACK_IDS = [53]  # docs/usage.md 里的示例包 ID


def fetch_bytes(url: str) -> bytes | None:
    try:
        return BiliClient(cookie=cfg.cookie.value).get_bytes(url, timeout=15)
    except Exception as exc:  # noqa: BLE001 单张失败不中断整批
        print(f"    ! 下载失败: {exc}")
        return None


def crop_to_ratio(image: QImage, ratio: float) -> QImage:
    """居中裁剪到指定 高/宽 比例。"""
    w, h = image.width(), image.height()
    if w <= 0 or h <= 0:
        return image
    target_h = w * ratio
    if target_h <= h:  # 原图偏高 → 裁上下
        top = int((h - target_h) / 2)
        return image.copy(0, top, w, int(target_h))
    target_w = h / ratio  # 原图偏宽 → 裁左右
    left = int((w - target_w) / 2)
    return image.copy(left, 0, int(target_w), h)


def save_image(data: bytes, path: Path, *, width: int, ratio: float) -> bool:
    image = QImage()
    if not image.loadFromData(data):
        print("    ! 不是可识别的图片")
        return False
    image = crop_to_ratio(image, ratio).scaled(
        width,
        int(width * ratio),
        Qt.AspectRatioMode.IgnoreAspectRatio,  # 已裁成目标比例，这里是等比缩放
        Qt.TransformationMode.SmoothTransformation,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # PNG 保留透明通道（表情多为透明底），JPEG 用于不透明的收藏集封面
    ok = image.save(str(path), quality=_JPEG_QUALITY if path.suffix == ".jpg" else -1)
    if not ok:
        print(f"    ! 写入失败: {path}")
    return ok


def emote_url(pkg) -> str:
    """包的展示图：优先第一个表情的静态图，其次包封面。

    gif_url 一律跳过（展示图要静态）；纯文本颜文字包（如 #4）的 `emote.url` 是
    颜文字本身而不是链接，靠 http 前缀过滤掉。
    """
    for emote in getattr(pkg, "emote", None) or ():
        if emote.url and emote.url.startswith("http"):
            return emote.url
    url = getattr(pkg, "url", "") or ""
    return url if url.startswith("http") else ""


def pick_package_ids(args) -> list[int]:
    # 多取几个候选：颜文字包、取图失败的包会被跳过，只取 N 个容易凑不满
    want = args.emoji_count + 4
    if args.emoji_ids:
        return list(args.emoji_ids)[:want]
    cookie = cfg.cookie.value.strip()
    if cookie:
        try:
            packages = Emoji(
                cookie=cookie, proxies=parse_proxy(cfg.proxy.value)
            ).all_packages()
            return [p.id for p in packages][:want]
        except Exception as exc:  # noqa: BLE001 没权限就退回示例 ID
            print(f"  ! all_packages 失败（{exc}），退回示例 ID {_FALLBACK_IDS}")
    else:
        print(f"  ! 未配置 Cookie，退回示例 ID {_FALLBACK_IDS}")
    return _FALLBACK_IDS[:want]


def fetch_emoji(args) -> list[dict]:
    print("== 表情包 ==")
    entries: list[dict] = []
    for pid in pick_package_ids(args):
        if len(entries) >= args.emoji_count:
            break
        try:
            pkg = api_cache.emoji_package(pid)
        except Exception as exc:  # noqa: BLE001 单个包失败跳过
            print(f"  #{pid} 详情失败: {exc}")
            continue
        url = emote_url(pkg)
        name = (pkg.emote[0].text if pkg.emote else None) or pkg.text or f"#{pid}"
        print(f"  #{pid} {name} -> {url or '(无图)'}")
        if not url:
            continue
        if args.dry_run:
            entries.append({"file": "", "name": name, "package_id": pid})
            continue
        data = fetch_bytes(url)
        if data is None:
            continue
        filename = f"{len(entries) + 1:02d}.png"
        if save_image(
            data, SHOWCASE_DIR / "emoji" / filename, width=args.size, ratio=1.0
        ):
            entries.append({"file": filename, "name": name, "package_id": pid})
    return entries


def fetch_collection(args) -> list[dict]:
    print(f"== 收藏集（关键词 {args.keyword}）==")
    try:
        summaries = api_cache.search_dress(30, args.keyword)
    except Exception as exc:  # noqa: BLE001 搜索失败就没有收藏集素材
        print(f"  ! 搜索失败: {exc}")
        return []
    entries: list[dict] = []
    for summary in summaries:
        if len(entries) >= args.coll_count:
            break
        if not is_collection(summary):
            continue
        url = summary.image_cover or ""
        name = summary.name or "未命名"
        print(f"  {name} -> {url or '(无封面)'}")
        if not url or args.dry_run:
            if url:
                entries.append({"file": "", "name": name})
            continue
        data = fetch_bytes(url)
        if data is None:
            continue
        filename = f"{len(entries) + 1:02d}.jpg"
        if save_image(
            data,
            SHOWCASE_DIR / "collection" / filename,
            width=_COLL_WIDTH,
            ratio=_COLL_RATIO,
        ):
            entries.append({"file": filename, "name": name})
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取主页展示图到 static/showcase/")
    parser.add_argument("--emoji-ids", type=int, nargs="*", help="指定表情包 ID")
    parser.add_argument("--emoji-count", type=int, default=8, help="表情图数量")
    parser.add_argument("--keyword", default="2233", help="收藏集搜索关键词")
    parser.add_argument("--coll-count", type=int, default=6, help="收藏集封面数量")
    parser.add_argument("--size", type=int, default=_EMOJI_SIZE, help="表情图边长")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不下载")
    args = parser.parse_args()

    emoji = fetch_emoji(args)
    collection = fetch_collection(args)

    if args.dry_run:
        print("\n(dry-run，未写入任何文件)")
        return 0

    SHOWCASE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    SHOWCASE_MANIFEST.write_text(
        json.dumps(
            {"emoji": emoji, "collection": collection}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\n表情 {len(emoji)} 张 / 收藏集 {len(collection)} 张 -> {SHOWCASE_DIR}")
    return 0 if (emoji or collection) else 1


if __name__ == "__main__":
    sys.exit(main())
