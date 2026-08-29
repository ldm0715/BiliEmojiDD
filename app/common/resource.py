"""静态资源定位：应用图标等。

图标放在项目根的 `static/`（不是包内），所以路径按本文件位置回溯两级：
`app/common/resource.py` → parents[0]=common、[1]=app、[2]=项目根。
文件缺失时一律返回空 `QIcon`，不抛异常——少一个图标不该让应用起不来。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
APP_ICON_PATH = STATIC_DIR / "logo.ico"


def app_icon() -> QIcon:
    """应用图标（标题栏 / 任务栏 / 设置页头共用）。"""
    if not APP_ICON_PATH.is_file():
        return QIcon()
    return QIcon(str(APP_ICON_PATH))
