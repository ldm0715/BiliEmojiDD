"""主题自适应：全局调色板 + 主题感知取色 + 重刷绑定。

qfluentwidgets 只给其组件套 QSS、不改全局 palette，本项目大量纯 QWidget
（QScrollArea / QListWidget / QLabel）的背景与默认文字色依赖 palette，
因此在主题切换时本模块按生效主题应用全局调色板。文字优先用 qfluentwidgets
主题化 Label（BodyLabel/CaptionLabel/StrongBodyLabel）并配 setTextColor(light, dark)。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ThemeColor, isDarkTheme, qconfig

# (light, dark) 文字色对，供主题化 Label 的 setTextColor 使用
BODY_TEXT = ("#1f1f1f", "#f2f2f2")  # 主文字：浅色深字 / 深色浅字
SECONDARY_TEXT = ("#6f6f6f", "#9aa0a6")  # 次要/提示文字
ORANGE_TEXT = ("#f69730", "#f69730")  # 收藏集徽标 / 已下载状态，两主题一致


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
