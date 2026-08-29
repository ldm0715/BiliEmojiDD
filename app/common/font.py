"""全局字体：加载 `static/font/` 下的内置字体并让全应用（含 qfluentwidgets）用上它。

两件事必须都做，缺一不可：

1. `QApplication.setFont(...)` —— 管住原生控件（`QLabel` / `QPushButton` / `QListWidget` …）。
2. **给 qfluentwidgets 打补丁** —— 库里 `qfluentwidgets/common/font.py::getFont()` 把字体族
   **硬编码**成 `['Segoe UI', 'Microsoft YaHei', 'PingFang SC']`，组件库的每个
   Label / Button / ComboBox 构造时都 `setFont(getFont(...))`，所以光设应用字体它们
   一个都不跟。

打补丁的坑：库里有二十多个模块写的是 `from ...common.font import setFont, getFont`
——**导入那一刻就把函数对象绑到自己模块的全局名上了**，事后替换
`qfluentwidgets.common.font.getFont` 对它们无效。所以还要扫一遍 `sys.modules` 把仍指向
原函数的 `getFont` 重新绑定。`setFont` 不用管：它的函数体在**自己模块的 globals** 里查
`getFont`，天然吃到补丁。

无字体文件 / 加载失败一律静默返回 `None`，不影响启动。
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QFontDatabase

from app.common.resource import app_font_files

# 内置字体之后的兜底族：中文缺字回落 YaHei，拉丁回落 Segoe UI
_FALLBACK_FAMILIES = ("Microsoft YaHei", "Segoe UI", "PingFang SC")

_app_family: str | None = None


def app_font_family() -> str | None:
    """已加载的内置字体族名；未加载 / 加载失败为 None。"""
    return _app_family


def load_app_fonts() -> str | None:
    """把 `static/font/` 下的字体全部注册进 QFontDatabase，返回第一个成功的族名。

    需要已经存在 QGuiApplication 实例（`addApplicationFont` 的硬性要求）。
    """
    family: str | None = None
    for path in app_font_files():
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:  # 格式不被支持（如 woff2）或文件损坏
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families and family is None:
            family = families[0]
    return family


def font_families(family: str | None = None) -> list[str]:
    """字体族回落链：内置字体在前，系统字体兜底。"""
    family = family or _app_family
    head = [family] if family else []
    return head + [f for f in _FALLBACK_FAMILIES if f != family]


def apply_app_font(app) -> str | None:
    """加载内置字体 + 设为应用默认 + 给 qfluentwidgets 打补丁。返回族名或 None。

    必须在**导入 `app.MainWindow` 之前**调用：`sys.modules` 里那批 qfluentwidgets
    模块的 `getFont` 绑定要在页面控件构造前就换掉。
    """
    global _app_family
    _app_family = load_app_fonts()
    if _app_family is None:
        return None

    families = font_families(_app_family)
    base = app.font()
    font = QFont(base)
    font.setFamilies(families)
    app.setFont(font)
    _patch_qfluentwidgets(families)
    return _app_family


def _patch_qfluentwidgets(families: list[str]) -> None:
    """把 qfluentwidgets 的 getFont 换成「族名前插内置字体」的版本。"""
    from qfluentwidgets.common import font as qfw_font

    original = qfw_font.getFont

    def patched_get_font(fontSize=14, weight=QFont.Weight.Normal):  # 参数名对齐上游签名
        font = original(fontSize, weight)
        # 上游的族名接在后面继续当兜底；dict.fromkeys 去重且保序
        font.setFamilies(list(dict.fromkeys(families + list(font.families()))))
        return font

    patched_get_font.__wrapped__ = original  # 便于断言脚本识别补丁是否生效
    qfw_font.getFont = patched_get_font

    # 已导入的模块用的是导入时绑定的旧函数对象，逐个重绑
    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").split(".")[0] != "qfluentwidgets":
            continue
        if getattr(module, "getFont", None) is original:
            module.getFont = patched_get_font
