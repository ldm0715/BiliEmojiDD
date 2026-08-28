"""主窗口：FluentWindow 导航 + 侧栏主题切换 + 关闭窗口时的下载保护。"""
from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    MessageBox,
    NavigationItemPosition,
    NavigationToolButton,
    Theme,
    qconfig,
    setTheme,
)

from app.common.config import cfg
from app.common.signal_bus import signal_bus
from app.common.theme import is_dark
from app.components.task import task_manager
from app.view.download_page import DownloadPage
from app.view.dress_page import DressPage
from app.view.emoji_page import EmojiPage
from app.view.setting_page import SettingPage


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.navigationInterface.setExpandWidth(150)  # 侧栏展开宽度（默认 322）
        self.emojiPage = EmojiPage(self)
        self.dressPage = DressPage(self)
        self.downloadPage = DownloadPage(self)
        self.settingPage = SettingPage(self)

        self.initNavigation()
        self.initWindow()

    def initNavigation(self) -> None:
        # FluentWindow.addSubInterface 要求页面 objectName 非空
        self.emojiPage.setObjectName("emojiPage")
        self.dressPage.setObjectName("dressPage")
        self.downloadPage.setObjectName("downloadPage")
        self.settingPage.setObjectName("settingPage")
        self.addSubInterface(self.emojiPage, FluentIcon.EMOJI_TAB_SYMBOLS, "表情包")
        self.addSubInterface(self.dressPage, FluentIcon.ALBUM, "收藏集")
        self.addSubInterface(self.downloadPage, FluentIcon.DOWNLOAD, "下载")
        # 主题切换按钮：插在设置之前 → 位于设置上方（bottom 布局先加的在上面）
        self.themeNavBtn = NavigationToolButton(
            FluentIcon.BRIGHTNESS, self.navigationInterface
        )
        self.themeNavBtn.setToolTip("切换亮色 / 暗色主题")
        self.themeNavBtn.clicked.connect(self._toggle_theme)
        self.navigationInterface.addWidget(
            routeKey="themeToggle",
            widget=self.themeNavBtn,
            onClick=self._toggle_theme,
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settingPage,
            FluentIcon.SETTING,
            "设置",
            NavigationItemPosition.BOTTOM,
        )
        self._update_theme_icon()
        qconfig.themeChangedFinished.connect(self._update_theme_icon)

    def _toggle_theme(self) -> None:
        next_theme = Theme.LIGHT if is_dark() else Theme.DARK
        # 先 setTheme 再存 cfg.theme：保证保存时 ThemeMode 与应用主题一致
        setTheme(next_theme)
        qconfig.set(cfg.theme, next_theme)
        signal_bus.configChanged.emit()  # 让设置页主题下拉同步

    def _update_theme_icon(self) -> None:
        # 图标随主题变换：亮色显示对比度（提示可切暗），暗色显示亮度（提示可切亮）
        self.themeNavBtn.setIcon(
            FluentIcon.BRIGHTNESS if is_dark() else FluentIcon.CONSTRACT
        )

    def initWindow(self) -> None:
        self.setWindowTitle("B 站表情包下载器")
        self.resize(1100, 760)
        self.setMinimumSize(820, 600)

    def closeEvent(self, event: QCloseEvent) -> None:
        if task_manager.running_downloads:
            # 下载不支持安全中断：clear() 只能清掉尚未开始的任务，
            # 立即退出会终止运行中的下载并可能残留 .part 临时文件。
            box = MessageBox(
                "下载进行中",
                "下载不支持安全中断。\n"
                "立即退出将终止下载进程，并可能残留 .part 临时文件。\n\n"
                "确定要退出吗？",
                self,
            )
            box.yesButton.setText("退出")
            box.cancelButton.setText("取消")
            if not box.exec():
                event.ignore()
                return
        # 仅清除尚未开始的任务；运行中的下载在确认退出后随进程结束
        task_manager.clear_pending()
        event.accept()
