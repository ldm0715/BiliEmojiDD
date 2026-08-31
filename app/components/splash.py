"""开屏面板：应用启动那几秒里先把图标 / 名称 / 版本号亮出来。

冷启动实测（本机）：`import PySide6` 0.4s + `import qfluentwidgets` 0.5s +
`import app.MainWindow` 2.1s + `MainWindow()` 2.7s ≈ 6s，其中后两项占八成——
这段时间里屏幕上什么都没有，用户会以为程序没起来（真实反馈）。

**上游 `qfluentwidgets.SplashScreen` 不合用**：它必须挂在一个已经存在的
`FluentWindow` 上（构造里 `parent.installEventFilter`），而我们要遮的恰恰是
「MainWindow 还没造出来」那一段；它也只画一个居中图标，没有名称与版本号。
所以这里自己写一个独立的顶层窗口，在 `import app.MainWindow` **之前**就亮出来。

期间没有事件循环，所以：
- 不做动画（转圈会僵在某一帧，看着更像卡死）；
- 进度靠 `set_message()` 分阶段换文案，内部走 `repaint()` **同步重绘**，
  不用 `processEvents()`——那会在 MainWindow 半构造好的时候重入事件派发。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, IconWidget, TitleLabel, isDarkTheme

from app.common.config import APP_VERSION
from app.common.resource import app_icon
from app.common.theme import SECONDARY_TEXT
from app.components.page_scaffold import version_badge

# 显示名用 `BiliEmojiDD`（大写 B），与窗口标题 / 主页 / 设置页身份行一致。
# `config.APP_NAME` 是小写 b 的 `biliEmojiDD`，那是 %APPDATA% 目录名，不是品牌名。
_TITLE = "BiliEmojiDD"

_WIDTH = 380
_HEIGHT = 230
_ICON = 64
_RADIUS = 10
# 卡片底色：与上游 splash 同一套取值（深色 #202020 / 浅色纯白）
_BG = ((255, 255, 255), (32, 32, 32))
_BORDER = ((0, 0, 0, 26), (255, 255, 255, 26))


class SplashWindow(QWidget):
    """启动画面。用法见模块 docstring 与 `main.py`。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # SplashScreen 标志位在任务栏不占位；置顶避免被别的窗口盖住
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # 圆角要靠自绘 + 透明背景，否则四角是方的
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_WIDTH, _HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 22)
        layout.setSpacing(10)
        # **不要给整个布局设 AlignHCenter**：带对齐标志的项只拿到自己的 sizeHint 宽度，
        # 而 `wordWrap` 的 Label 的 sizeHint 宽度很窄，进度文案会被挤成细细一条、
        # 折成好几行还看不清（真实反馈）。居中由每个子项自己的对齐标志负责，
        # 需要铺满整行的 messageLabel 则**不带**标志加进来。

        self.iconWidget = IconWidget(app_icon(), self)
        self.iconWidget.setFixedSize(_ICON, _ICON)
        layout.addWidget(self.iconWidget, 0, Qt.AlignmentFlag.AlignHCenter)

        self.titleLabel = TitleLabel(_TITLE, self)
        layout.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        self.versionLabel = version_badge(APP_VERSION, self)
        layout.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

        self.messageLabel = CaptionLabel("正在启动…", self)
        self.messageLabel.setTextColor(*SECONDARY_TEXT)
        self.messageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.messageLabel.setWordWrap(True)
        # 文案长短不一，高度按两行钉死：否则每换一次文案整块布局都要重排、面板抖动
        self.messageLabel.setFixedHeight(
            self.messageLabel.fontMetrics().height() * 2 + 2
        )
        layout.addWidget(self.messageLabel)  # 不带对齐标志 = 铺满整行

        self._center()

    def _center(self) -> None:
        """摆到主屏可用区正中（避开任务栏）。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        center = screen.availableGeometry().center()
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def start(self) -> None:
        """显示并确保真的画出来了。

        `show()` 只是排了一个 expose 事件，不跑事件循环的话窗口是空的。
        这一次 `processEvents` 在 MainWindow 存在之前调用，没有重入风险；
        之后的进度更新一律走 `set_message` 的同步 `repaint()`。
        """
        self.show()
        self.raise_()
        QApplication.processEvents()

    def set_message(self, text: str) -> None:
        """更新进度文案并立刻重绘（同步，不进事件循环）。"""
        self.messageLabel.setText(text)
        self.repaint()

    def finish(self, window: QWidget | None = None) -> None:
        """关闭开屏面板；给了主窗口就顺手把它提到前面。"""
        self.close()
        if window is not None:
            window.raise_()
            window.activateWindow()
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()

        path = QPainterPath()
        # 描边画在内侧半像素上，避免抗锯齿把边糊到控件外
        path.addRoundedRect(0.5, 0.5, _WIDTH - 1, _HEIGHT - 1, _RADIUS, _RADIUS)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*_BG[dark]))
        painter.drawPath(path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(*_BORDER[dark]))
        painter.drawPath(path)
