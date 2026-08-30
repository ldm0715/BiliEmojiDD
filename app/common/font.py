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

字体渲染后端见 `apply_font_engine()`——那个必须在 `QApplication` **构造之前**调，
和这里的 `apply_app_font()`（要求已有 QGuiApplication）时机正好相反。

无字体文件 / 加载失败一律静默返回 `None`，不影响启动。
"""
from __future__ import annotations

import os
import re
import sys

from PySide6.QtGui import QFont, QFontDatabase

from app.common.config import cfg
from app.common.resource import app_font_files

# 内置字体之后的兜底族：中文缺字回落 YaHei，拉丁回落 Segoe UI
_FALLBACK_FAMILIES = ("Microsoft YaHei", "Segoe UI", "PingFang SC")

# 首选族名：`static/font/` 里出现多个字体族时用它，避免「用哪个字体」取决于文件名排序。
# 目录里没有它就退回第一个成功加载的族，行为与以前一致。
PREFERRED_FAMILY = "LXGW WenKai Mono GB"

# FreeType 下决定字形是否对齐像素网格——「糊」与「实」的分界。DirectWrite 会忽略它。
_HINTING = QFont.HintingPreference.PreferFullHinting

_app_family: str | None = None


def app_font_family() -> str | None:
    """已加载的内置字体族名；未加载 / 加载失败为 None。"""
    return _app_family


def apply_font_engine() -> str | None:
    """按配置切换 Qt 的字体渲染后端，返回实际生效的引擎名（未切换返回 None）。

    **必须在 `QApplication` 构造之前调用**：这是平台插件的启动参数，插件一旦初始化就定型了。
    Qt 只在 Windows 平台插件上认这个选项；`QT_QPA_PLATFORM` 已被外部指定（屏幕外脚本的
    `offscreen`）时不覆盖，否则断言脚本会被拽回真实平台。

    实测（PySide6 6.4.2）：`freetype` 确实换掉了光栅化结果，`gdi` 被静默忽略，
    所以 `FONT_ENGINES` 里只给这两个选项。
    """
    engine = cfg.font_engine.value
    if engine == "default" or sys.platform != "win32":
        return None
    if os.environ.get("QT_QPA_PLATFORM"):
        return None
    os.environ["QT_QPA_PLATFORM"] = f"windows:fontengine={engine}"
    return engine


def load_app_fonts() -> str | None:
    """把 `static/font/` 下的字体全部注册进 QFontDatabase，返回该用的族名。

    需要已经存在 QGuiApplication 实例（`addApplicationFont` 的硬性要求）。
    """
    families: list[str] = []
    for path in app_font_files():
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:  # 格式不被支持（如 woff2）或文件损坏
            continue
        families.extend(QFontDatabase.applicationFontFamilies(font_id))
    if PREFERRED_FAMILY in families:
        return PREFERRED_FAMILY
    return families[0] if families else None


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
    font.setHintingPreference(_HINTING)
    app.setFont(font)
    _patch_qfluentwidgets(families)
    _patch_stylesheet_font(families)
    return _app_family


# 上游 23 个 qss 里硬编码的字体族串，形如
#   font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC';
# 单双引号都出现过，`PingFang SC` 有时没有。
_QSS_FAMILIES_RE = re.compile(
    r"""['"]Segoe UI['"]\s*,\s*['"]Microsoft YaHei['"]"""
    r"""(?:\s*,\s*['"]PingFang SC['"])?"""
)


def _patch_stylesheet_font(families: list[str]) -> None:
    """把库内 qss 里硬编码的字体族换成内置字体。

    **QSS 的优先级高于 `setFont`**，所以光打 `getFont` 补丁是不够的：
    `BUTTON` / `CHECK_BOX` / `INFO_BAR` / `EXPAND_SETTING_CARD` 等 23 个样式表都写死了
    `font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC'`，凡是应用了这些 qss 的控件
    都会退回 Segoe UI——表现就是「按钮、勾选框的字体没跟着换」。
    （`LINE_EDIT` / `COMBO_BOX` 里那两行是注释掉的，所以输入框和下拉一直是对的。）

    qss 编在 Qt 资源里（磁盘上 grep 不到），统一经 `getStyleSheetFromFile` 读出来，
    包一层做替换即可；库内没有别的模块直接 import 它，不用像 `getFont` 那样扫
    `sys.modules` 重绑。
    """
    from qfluentwidgets.common import style_sheet as qss_mod

    original = qss_mod.getStyleSheetFromFile
    if getattr(original, "__wrapped__", None) is not None:  # 幂等：别套第二层
        return
    replacement = ", ".join(f"'{name}'" for name in families)

    def patched_get_qss(file):
        return _QSS_FAMILIES_RE.sub(replacement, original(file))

    patched_get_qss.__wrapped__ = original  # 便于断言脚本识别补丁是否生效
    qss_mod.getStyleSheetFromFile = patched_get_qss


def _patch_qfluentwidgets(families: list[str]) -> None:
    """把 qfluentwidgets 的 getFont 换成「族名前插内置字体」的版本。"""
    from qfluentwidgets.common import font as qfw_font

    original = qfw_font.getFont

    def patched_get_font(fontSize=14, weight=QFont.Weight.Normal):  # 参数名对齐上游签名
        font = original(fontSize, weight)
        # 上游的族名接在后面继续当兜底；dict.fromkeys 去重且保序
        font.setFamilies(list(dict.fromkeys(families + list(font.families()))))
        font.setHintingPreference(_HINTING)
        return font

    patched_get_font.__wrapped__ = original  # 便于断言脚本识别补丁是否生效
    qfw_font.getFont = patched_get_font

    # 已导入的模块用的是导入时绑定的旧函数对象，逐个重绑
    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").split(".")[0] != "qfluentwidgets":
            continue
        if getattr(module, "getFont", None) is original:
            module.getFont = patched_get_font
