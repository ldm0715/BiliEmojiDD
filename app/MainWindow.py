"""主窗口：FluentWindow 导航 + 侧栏主题切换 + 关闭窗口时的下载保护。"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtGui import QCloseEvent, QPixmap, QRegion
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    MessageBox,
    NavigationItemPosition,
    NavigationPushButton,
    PushButton,
    Theme,
    qconfig,
    setTheme,
)

from app.common.config import APP_VERSION, cfg
from app.common.notify import NEVER_DISMISS, notify_info
from app.common.resource import app_icon
from app.common.signal_bus import signal_bus
from app.common.theme import is_dark
from app.common.version import is_newer
from app.components import cookie_status
from app.components.task import run_task, task_manager
from app.components.update_dialog import show_update_dialog
from app.components.updater import fetch_latest_release
from app.components.video_cache import video_cache
from app.view.download_page import DownloadPage
from app.view.dress_page import DressPage
from app.view.emoji_page import EmojiPage
from app.view.home_page import (
    NAV_DOWNLOAD,
    NAV_DRESS,
    NAV_EMOJI,
    NAV_SETTING,
    HomePage,
)
from app.view.setting_page import SettingPage

# 启动自检延迟：先让首屏画完，别和页面构造抢线程
_AUTO_CHECK_DELAY = 3000

# 切页滑动的时长与位移，照上游 `PopUpAniStackedWidget`（300ms / deltaY=76 / OutQuad）。
# 想更干脆就把时长压到 150 左右，观感是「快速滑一下」。
_SLIDE_DURATION = 300
_SLIDE_DELTA = 76
# 快照控件的 objectName，给断言脚本找残留用
_SLIDE_OVERLAY_NAME = "pageSlideOverlay"

# `render()` 的两套旗标：只画容器自己那层 / 只画页面内容
# （PySide6 的 `RenderFlag` 只导出这三个，没有 C++ 里的 `DrawWidget`；
#  `render()` 默认值是 `DrawWindowBackground | DrawChildren`。）
_BG_ONLY = QWidget.RenderFlag.DrawWindowBackground
_CONTENT_ONLY = QWidget.RenderFlag.DrawChildren


def _page_snapshot(container, page) -> QPixmap:
    """把页面渲成一张位图当快照——**不能直接用 `page.grab()`**。

    `QWidget.grab()` 会拿控件自己的 `palette().window()` 铺底，而 QSS 接管过的子树里
    palette 是缓存值（`app.setPalette()` 进不去，见 `theme.py` 的说明）：亮色切暗色后
    页面 palette 还停在 `#efefef`，抓出来整张快照就是浅灰，动画放完真页面才变黑
    ——「切页先白一下再变黑」就是这么来的，跟 QSS 有没有刷干净无关（踩过）。

    所以自己开画布：底色取 `container` 自己那层（`stackedWidget` 注册了 QSS，底色是对的，
    `DrawWindowBackground` 的透明度也保留，叠在真背景上就与实时渲染一致），页面内容用
    `DrawChildren` 画上去、跳过页面那层过期 palette。
    """
    dpr = page.devicePixelRatioF()
    snap = QPixmap(int(page.width() * dpr), int(page.height() * dpr))
    snap.setDevicePixelRatio(dpr)
    snap.fill(Qt.GlobalColor.transparent)
    # 只画 container 自己（含 QSS 底色），不带子控件
    container.render(snap, QPoint(), QRegion(), _BG_ONLY)
    # 再叠页面内容：不带 DrawWindowBackground，也就用不到 page 那层 palette
    page.render(snap, QPoint(), QRegion(), _CONTENT_ONLY)
    return snap


class MainWindow(FluentWindow):
    def __init__(self, on_progress: Callable[[str], None] | None = None) -> None:
        """`on_progress` 是开屏面板的进度回调（`SplashWindow.set_message`）。

        五个页面同步构造要好几秒，这期间没有事件循环，开屏面板只能靠这里主动
        回调来换文案 + 同步重绘。不传就是静默构造（屏幕外脚本、测试都这么用）。
        """
        super().__init__()
        report = on_progress or (lambda _text: None)
        self.navigationInterface.setExpandWidth(150)  # 侧栏展开宽度（默认 322）
        # 切页动画的持有引用（PySide6 会回收没有 Python 引用的动画对象）。
        # 必须在 initNavigation 之前初始化：addSubInterface 装第一页时就会切一次页
        self._slide_ani = None
        self._slide_overlay = None
        self._slide_page = None
        self._slide_focus = None
        # 标题栏返回按钮走 qrouter.pop() → stacked.setCurrentWidget，不经 switchTo，
        # 所以直接换掉实例上的方法，三个切页入口统一走滑入（见 _set_current_interface）
        self.stackedWidget.setCurrentWidget = self._set_current_interface
        report("正在准备主页…")
        self.homePage = HomePage(self)
        report("正在准备表情包页…")
        self.emojiPage = EmojiPage(self)
        report("正在准备收藏集页…")
        self.dressPage = DressPage(self)
        report("正在准备下载页…")
        self.downloadPage = DownloadPage(self)
        report("正在准备设置页…")
        self.settingPage = SettingPage(self)

        report("正在装配窗口…")
        # 主页在 showEvent 里触发 Cookie 检测，结论经这个信号回来 → 静默预拉取
        # 全部表情包。连接放在「页面都构造好、initNavigation 之前」：主页是被
        # addSubInterface 显示出来的，那一刻信号必须已经有人接。
        signal_bus.cookieStateChanged.connect(self._on_cookie_state)
        self.initNavigation()
        self.initWindow()
        if cfg.auto_check_update.value:
            QTimer.singleShot(_AUTO_CHECK_DELAY, self._auto_check_update)

    # ---- 切页 ----

    def _set_current_interface(self, interface, popOut: bool = True) -> None:
        """切页：状态立即生效，动画只滑一张快照。

        上游 `PopUpAniStackedWidget` 是**移动真页面**（300ms `pos` 动画，deltaY=76），
        每一帧都要重绘整页——实测单帧重绘主页 17.8ms / 设置页 12.7ms / 表情包
        9.2ms，而 60Hz 的预算只有 16.7ms，这就是当初把动画关掉的原因。
        这里改成：先把目标页抓成一张位图（一次 5–18ms），再让位图本身从 +76px 滑到
        原位——每帧只贴一次图（实测 0.47ms），页面藏在快照底下不参与重绘。

        仍只换 `stackedWidget` 实例上的 `setCurrentWidget`（而不是只覆写
        `switchTo`），把三个入口一次盖全：侧栏点击、`switchTo`、标题栏返回按钮
        （`qrouter.pop()` 直接调 `stacked.setCurrentWidget`）。
        `popOut` 参数只为签名兼容，这里一律忽略：两个方向都走同一条滑入。
        """
        view = self.stackedWidget.view
        index = view.indexOf(interface)
        if index < 0 or index == view.currentIndex():
            return
        self._finish_slide()  # 上一次还在飞就先收尾
        # 先切状态：侧栏高亮 / currentWidget() / qrouter 都不等动画跑完
        QStackedWidget.setCurrentIndex(view, index)
        self._start_slide(interface)

    def _start_slide(self, interface) -> None:
        """抓快照 → 藏起真页面 → 滑快照。

        顺序不能颠倒：`render()` 必须发生在页面已经显示之后（没显示过的控件渲出来是空的），
        而页面必须在动画开始前藏掉——否则顶部 `_SLIDE_DELTA` 那一条会同时露出
        「页面顶部」和「快照顶部」，叠出一条重复的内容带。
        这几步之间没有事件循环，不会有人看见中间态。
        """
        view = self.stackedWidget.view
        focused = self.window().focusWidget()
        self._slide_focus = (
            focused if focused is not None and interface.isAncestorOf(focused) else None
        )

        # 必须挂在 stackedWidget 上而不是 view 上：view 是 QStackedWidget，
        # 直接给它加子控件会被 QStackedLayout 当成新的一页（notify.py 的 InfoBar 同理）。
        # `show()` 不能省：窗口已经显示之后再 new 出来的子控件，Qt 不会自动显示，
        # 漏了这句动画照样跑，只是那张图从头到尾没画出来（踩过）。
        overlay = QLabel(self.stackedWidget)
        overlay.setObjectName(_SLIDE_OVERLAY_NAME)  # 断言脚本靠它找残留
        overlay.setPixmap(_page_snapshot(self.stackedWidget, interface))
        overlay.setGeometry(view.geometry())
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.show()
        overlay.raise_()
        interface.hide()

        ani = QPropertyAnimation(overlay, b"pos", self)
        ani.setDuration(_SLIDE_DURATION)
        ani.setEasingCurve(QEasingCurve.OutQuad)
        ani.setStartValue(QPoint(view.x(), view.y() + _SLIDE_DELTA))
        ani.setEndValue(view.pos())
        ani.finished.connect(self._finish_slide)

        self._slide_ani = ani
        self._slide_overlay = overlay
        self._slide_page = interface
        ani.start()

    def _finish_slide(self) -> None:
        """收尾：删快照、把真页面放回来。成功与打断两条路都走它，所以必须幂等。"""
        ani, overlay, page = self._slide_ani, self._slide_overlay, self._slide_page
        focus, self._slide_focus = self._slide_focus, None
        self._slide_ani = self._slide_overlay = self._slide_page = None
        if ani is not None:
            ani.stop()
            ani.deleteLater()
        if overlay is not None:
            overlay.hide()
            # 先摘父级再 deleteLater：`processEvents()` 不派发 DeferredDelete，
            # 光 deleteLater 会让它一直挂在 stackedWidget 上（等同项目里 FlowLayout 的清理套路）
            overlay.setParent(None)
            overlay.deleteLater()
        if page is not None:
            page.show()  # 快照与真页面内容一致，这一下看不出接缝
        if focus is not None:
            # 页面藏起来时 Qt 会把焦点挪走，动画结束补回页内原来的那个控件
            try:
                focus.setFocus()
            except RuntimeError:  # 控件已随页面销毁
                pass

    def switchTo(self, interface) -> None:
        self._set_current_interface(interface)

    def initNavigation(self) -> None:
        # FluentWindow.addSubInterface 要求页面 objectName 非空
        self.homePage.setObjectName("homePage")
        self.emojiPage.setObjectName("emojiPage")
        self.dressPage.setObjectName("dressPage")
        self.downloadPage.setObjectName("downloadPage")
        self.settingPage.setObjectName("settingPage")
        # 主页放第一个 → addSubInterface 在 stackedWidget.count()==1 时会自动
        # setCurrentItem + setDefaultRouteKey，它自然成为启动页，无需额外 switchTo
        self.addSubInterface(self.homePage, FluentIcon.HOME, "主页")
        self.addSubInterface(self.emojiPage, FluentIcon.EMOJI_TAB_SYMBOLS, "表情包")
        self.addSubInterface(self.dressPage, FluentIcon.ALBUM, "收藏集")
        self.addSubInterface(self.downloadPage, FluentIcon.DOWNLOAD, "下载")
        # 主题切换按钮：插在设置之前 → 位于设置上方（bottom 布局先加的在上面）
        # 用 NavigationPushButton（不是 NavigationToolButton）：侧栏展开时会显示文字
        self.themeNavBtn = NavigationPushButton(
            FluentIcon.BRIGHTNESS, "主题", False, self.navigationInterface
        )
        self.themeNavBtn.setToolTip("切换亮色 / 暗色主题")
        # 只经 addWidget(onClick=...) 接线：NavigationPanel._registerWidget 会把 onClick
        # 连到 widget.clicked，这里再手动 connect 一次会让一次点击切两遍主题（等于没切）
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
        # 主页只发信号（不反向引用窗口），跳转在这里落地
        self.homePage.navigateRequested.connect(self._navigate)

    def _navigate(self, key: str) -> None:
        page = {
            NAV_EMOJI: self.emojiPage,
            NAV_DRESS: self.dressPage,
            NAV_DOWNLOAD: self.downloadPage,
            NAV_SETTING: self.settingPage,
        }.get(key)
        if page is not None:
            self.switchTo(page)

    # ---- Cookie 状态 ----

    def _on_cookie_state(self, state: str) -> None:
        """Cookie 确认有效 → 后台静默预拉取全部表情包（**不切页**）。

        用户留在主页，等他进表情包页时列表已经就绪（命中 24 小时缓存时零请求）。
        再核对一次 `known_state()` 是防迟到回调：探针在飞的时候用户可能已经登出，
        那时记录已被 `_apply_cookie` 作废，不该再拿旧结论去发请求。
        """
        if state != cookie_status.VALID:
            return
        if cookie_status.known_state() != cookie_status.VALID:
            return
        # 延到事件循环第一拍：别把「读缓存 + 建 20 张卡片」的开销塞进窗口构造
        QTimer.singleShot(0, self.emojiPage.ensure_all_packages)

    # ---- 检查更新 ----

    def _auto_check_update(self) -> None:
        """启动后静默查一次新版本。

        **失败彻底静默**：启动时没网 / GitHub 不通不该弹错，用户要查自会去设置页点。
        """
        run_task(
            fetch_latest_release,
            on_success=self._on_auto_release,
            on_error=lambda exc: None,
        )

    def _on_auto_release(self, info) -> None:
        """有新版才出声，且只出一条带按钮的提示——不在启动时糊用户一脸模态窗。"""
        if not is_newer(info.tag, APP_VERSION):
            return
        bar = notify_info(
            f"发现新版本 {info.tag}",
            f"当前 v{APP_VERSION}。可在此查看更新说明，或到「设置 → 关于」再操作。",
            parent=self,
            duration=NEVER_DISMISS,
        )
        button = PushButton("查看更新", bar)
        button.clicked.connect(lambda: self._open_update_dialog(info, bar))
        bar.addWidget(button)

    def _open_update_dialog(self, info, bar) -> None:
        bar.close()
        show_update_dialog(info, self)

    def _toggle_theme(self) -> None:
        next_theme = Theme.LIGHT if is_dark() else Theme.DARK
        # 先 setTheme 再存 cfg.theme：保证保存时 ThemeMode 与应用主题一致。
        # lazy=True：没在画的控件（别的页面、滚出视口的卡片）不立刻重刷，改由上游的
        # DirtyStyleSheetWatcher 在它们下一次绘制时补——实测空应用 350ms → 127ms，
        # 表情包网格塞满卡时 1.9s → 1.0s。晚到的控件在下一次绘制前一定已经刷好。
        setTheme(next_theme, lazy=True)
        qconfig.set(cfg.theme, next_theme)
        signal_bus.configChanged.emit()  # 让设置页主题下拉同步

    def _update_theme_icon(self) -> None:
        # 图标随主题变换：亮色显示对比度（提示可切暗），暗色显示亮度（提示可切亮）
        self.themeNavBtn.setIcon(
            FluentIcon.BRIGHTNESS if is_dark() else FluentIcon.CONSTRACT
        )

    def initWindow(self) -> None:
        # FluentTitleBar 自带 iconLabel + titleLabel，且已连好 windowIconChanged /
        # windowTitleChanged——设这两项即可，无需自定义标题栏
        self.setWindowIcon(app_icon())
        self.setWindowTitle("BiliEmojiDD")
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
        # 设置页里「改了但还没失焦」的输入（下载目录 / 代理地址）在此补写：
        # 点 X / Alt+F4 关窗时输入框不一定发 editingFinished，不补写就会出现
        # 「界面改了、文件里没改」。放在 accept 之后：用户取消关窗时输入框里的值该留着。
        self.settingPage.commit_pending_edits()
        video_cache.cleanup()  # 删掉本会话的视频临时目录
        event.accept()
