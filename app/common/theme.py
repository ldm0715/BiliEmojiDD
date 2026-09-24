"""主题自适应：全局调色板 + 主题感知取色 + 重刷绑定。

qfluentwidgets 只给其组件套 QSS、不改全局 palette，本项目大量纯 QWidget
（QScrollArea / QListWidget / QLabel）的背景与默认文字色依赖 palette，
因此在主题切换时本模块按生效主题应用全局调色板。文字优先用 qfluentwidgets
主题化 Label（BodyLabel/CaptionLabel/StrongBodyLabel）并配 setTextColor(light, dark)。
"""
from __future__ import annotations

from functools import cache

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ThemeColor, isDarkTheme, qconfig

# (light, dark) 文字色对，供主题化 Label 的 setTextColor 使用
BODY_TEXT = ("#1f1f1f", "#f2f2f2")  # 主文字：浅色深字 / 深色浅字
SECONDARY_TEXT = ("#6f6f6f", "#9aa0a6")  # 次要/提示文字
ORANGE_TEXT = ("#f69730", "#f69730")  # 收藏集徽标 / 已下载状态，两主题一致
# 状态灯的两档。**不是**照抄 mirror_card 的胶囊底色（那是给白字压的深底），
# 文字色在暗色主题下要提亮才不会糊在 #202020 上。
SUCCESS_TEXT = ("#0f7b0f", "#4cc24c")  # Cookie 有效
DANGER_TEXT = ("#c42b1c", "#ff6b5e")  # Cookie 已失效


def is_dark() -> bool:
    """当前生效主题是否为深色（AUTO 已由 qconfig 解析为具体主题）。"""
    return bool(isDarkTheme())


def color_body() -> str:
    """主文字色（按当前主题）。"""
    return BODY_TEXT[1] if is_dark() else BODY_TEXT[0]


def color_secondary() -> str:
    """次要文字色（按当前主题）。"""
    return SECONDARY_TEXT[1] if is_dark() else SECONDARY_TEXT[0]


def bind_theme(widget, fn) -> None:
    """立即执行 fn()，并在每次主题切换（themeChangedFinished）后重新执行。

    fn 必须是 widget 的绑定方法：widget 销毁时 PySide6 会自动断开该连接，避免泄漏。
    """
    fn()
    qconfig.themeChangedFinished.connect(fn)


# QSS 文本缓存（`functools.lru_cache` 包装后的「路径 → qss」函数），
# 断言脚本读它的 `cache_info()` 来证明「读文件次数不随控件数增长」
_qss_content_cache = None


def _patch_qss_content_cache() -> None:
    """按 QSS 路径缓存文件内容——主题切换的性能大头之一。

    上游 `updateStyleSheet()` 对每个注册控件调一次 `getStyleSheet(source, theme)`，
    里面是 `StyleSheetBase.content()` → `getStyleSheetFromFile(path)`：**每个控件都重开一次
    QFile、重读一遍 qss 资源**，之后还要再过一遍 `font.py` 的字体替换正则。实测空应用
    238 个注册控件就是 238 次白读，表情包网格塞满卡时 1738 次。

    路径本身已经带主题（`FluentStyleSheet.path()` = `:/qfluentwidgets/qss/<theme>/<名字>.qss`），
    qss 内容在运行期也不会变，所以按路径缓存不会串主题。

    挂在 `StyleSheetBase.content` 而不是 `getStyleSheetFromFile` 上：`font.py` 的字体补丁
    靠 `__wrapped__` 判幂等，抢先套一层 `lru_cache` 会让它以为自己已经打过而静默跳过。
    `CustomStyleSheet` / `StyleSheetCompose` 各自覆写了 `content`，不受影响。
    """
    global _qss_content_cache
    from qfluentwidgets.common import style_sheet as qss_mod

    original = qss_mod.StyleSheetBase.content
    if getattr(original, "_qss_cached", False):  # 幂等：别套第二层
        return

    @cache
    def content_for(path: str) -> str:
        # 现取模块属性：字体补丁可能在本补丁之后才打上
        return qss_mod.getStyleSheetFromFile(path)

    def cached_content(self, theme=qss_mod.Theme.AUTO) -> str:
        return content_for(self.path(theme))

    cached_content._qss_cached = True  # 不能叫 __wrapped__，见 docstring
    qss_mod.StyleSheetBase.content = cached_content
    _qss_content_cache = content_for


_patch_qss_content_cache()


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(32, 32, 32))
    p.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.Base, QColor(28, 28, 28))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 40))
    p.setColor(QPalette.ColorRole.Text, QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.Highlight, ThemeColor.PRIMARY.color())
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(160, 160, 160))
    p.setColor(QPalette.ColorRole.Link, QColor(0, 188, 212))
    p.setColor(QPalette.ColorRole.Light, QColor(60, 60, 60))
    p.setColor(QPalette.ColorRole.Midlight, QColor(50, 50, 50))
    p.setColor(QPalette.ColorRole.Mid, QColor(40, 40, 40))
    p.setColor(QPalette.ColorRole.Dark, QColor(20, 20, 20))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(240, 240, 240))
    return p


def _apply_app_palette() -> None:
    """按生效主题设置全局调色板：深色用暗色板，浅色恢复标准板。"""
    app = QApplication.instance()
    if app is None:
        return
    if is_dark():
        app.setPalette(_dark_palette())
    else:
        app.setPalette(app.style().standardPalette())
    # 强制重绘全部控件：避免网格/滚动区等容器保留旧 palette 的反色残留
    # （个别控件 update 签名被覆写，逐个 try 兜底）
    for widget in app.allWidgets():
        try:
            widget.update()
        except TypeError:
            pass


qconfig.themeChangedFinished.connect(_apply_app_palette)
_apply_app_palette()  # 覆盖 main.py 先 setTheme 后 import 本模块的情形
