"""主窗口：FluentWindow 导航 + 关闭窗口时的下载保护。"""
from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    MessageBox,
    NavigationItemPosition,
)

from app.components.task import task_manager
from app.view.download_page import DownloadPage
from app.view.dress_page import DressPage
from app.view.emoji_page import EmojiPage
from app.view.setting_page import SettingPage


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
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
        self.addSubInterface(
            self.settingPage,
            FluentIcon.SETTING,
            "设置",
            NavigationItemPosition.BOTTOM,
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
