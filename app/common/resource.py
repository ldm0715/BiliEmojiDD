"""静态资源定位：应用图标、内置字体、主页展示图等。

资源放在项目根的 `static/`（不是包内），所以路径按本文件位置回溯两级：
`app/common/resource.py` → parents[0]=common、[1]=app、[2]=项目根。
**任何缺失都静默降级**（返回空 `QIcon` / 空列表），不抛异常——少一张图不该让应用起不来。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QIcon

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
APP_ICON_PATH = STATIC_DIR / "logo.ico"
# 主页「关于」卡里的依赖徽标
QFLUENT_LOGO_PATH = STATIC_DIR / "qfluentwidget.png"
PYSIDE_LOGO_PATH = STATIC_DIR / "qtforpython.png"
# 主页展示图：由 scripts/fetch_showcase.py 一次性抓取并裁好后入库，运行时零网络请求
SHOWCASE_DIR = STATIC_DIR / "showcase"
SHOWCASE_MANIFEST = SHOWCASE_DIR / "manifest.json"
SHOWCASE_KINDS = ("emoji", "collection")
# 应用内置字体：只认 Qt 支持的三种容器格式（woff/woff2 加载必失败，见 scripts/convert_font.py）
FONT_DIR = STATIC_DIR / "font"
FONT_SUFFIXES = (".ttf", ".otf", ".ttc")


def app_icon() -> QIcon:
    """应用图标（标题栏 / 任务栏 / 设置页头共用）。"""
    if not APP_ICON_PATH.is_file():
        return QIcon()
    return QIcon(str(APP_ICON_PATH))


def app_font_files() -> list[Path]:
    """内置字体文件列表（目录不存在 / 没有可用格式都返回 []）。

    同族的多个字重（Regular / Bold …）全部登记即可，Qt 会按 `QFont.weight` 挑真字重；
    往 `static/font/` 里丢新文件就自动生效，无需改代码。
    """
    if not FONT_DIR.is_dir():
        return []
    return sorted(
        p for p in FONT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in FONT_SUFFIXES
    )


def _manifest() -> dict:
    try:
        data = json.loads(SHOWCASE_MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 缺失 / 损坏都当作没有清单
        return {}


def showcase_images(kind: str, limit: int = 8) -> list[Path]:
    """主页展示图路径列表。

    kind: 'emoji'（方形表情）| 'collection'（3:4 收藏集封面）。
    优先按 `manifest.json` 里的顺序取，清单缺失/损坏时退回目录内文件名排序。
    目录不存在返回 []——主页据此隐藏整条缩略图带。
    """
    folder = SHOWCASE_DIR / kind
    if kind not in SHOWCASE_KINDS or not folder.is_dir():
        return []
    out: list[Path] = []
    entries = _manifest().get(kind)
    if isinstance(entries, list):
        for entry in entries:
            name = entry.get("file") if isinstance(entry, dict) else entry
            if not isinstance(name, str):
                continue
            path = folder / name
            if path.is_file():
                out.append(path)
    if not out:  # 无清单 / 清单里的文件都不在 → 直接扫目录
        out = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix != ".json")
    return out[:limit] if limit > 0 else out


def showcase_names(kind: str) -> dict[str, str]:
    """文件名 → 素材名称（表情名 / 收藏集名），供 tooltip 使用；无清单返回 {}。"""
    entries = _manifest().get(kind)
    if not isinstance(entries, list):
        return {}
    return {
        e["file"]: e.get("name") or ""
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("file"), str)
    }
