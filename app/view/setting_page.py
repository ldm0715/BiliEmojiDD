"""设置页：Cookie / 下载目录 / 主题（Fluent 设置卡片版式）。

版式参照 Win11 / QFluentWidgets Gallery 设置页：大标题 → 分组标题 → 每行一张
「图标 + 标题 / 灰色副标题 + 右侧控件」窄卡片，整页滚动。控件与槽函数沿用改版前
的实现，本文件只负责「控件怎么摆」。
"""
from __future__ import annotations

from pathlib import Path

from biliemoji import AuthRequired
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    ExpandGroupSettingCard,
    ExpandLayout,
    FluentIcon,
    HyperlinkButton,
    IconWidget,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    SwitchButton,
    Theme,
    TitleLabel,
    ToolTipFilter,
    ToolTipPosition,
    qconfig,
    setTheme,
)

from app.common.config import (
    APP_CONFIG_DIR,
    APP_VERSION,
    LICENSE_URL,
    REPO_SLUG,
    REPO_URL,
    cfg,
)
from app.common.exception import cause_hint, show_bili_error
from app.common.net import current_proxies, make_emoji
from app.common.notify import (
    NEVER_DISMISS,
    notify_error,
    notify_info,
    notify_success,
    notify_warning,
)
from app.common.proxy import PROXY_PLACEHOLDER, normalize_proxy, redact_proxy
from app.common.resource import app_icon
from app.common.signal_bus import signal_bus
from app.common.theme import bind_theme
from app.common.version import is_newer
from app.components import cookie_status
from app.components.bili_login import fetch_account
from app.components.cache import save_all_packages_cache
from app.components.disk_cache import MB, clear_all, total_size
from app.components.download_runner import open_in_explorer
from app.components.login_dialog import (
    AccountAvatar,
    show_cookie_dialog,
    show_login_dialog,
)
from app.components.mirror_card import MirrorSettingCard
from app.components.page_scaffold import BusyPushButton, tune_scroll, version_badge
from app.components.proxy_probe import PROBE_NAME, PROBE_URL, probe_proxy
from app.components.task import run_task
from app.components.update_dialog import show_update_dialog
from app.components.updater import NoRelease, fetch_latest_release

_THEMES = [Theme.AUTO, Theme.LIGHT, Theme.DARK]
# 字体渲染后端下拉：文案 -> cfg.font_engine 的取值
_FONT_ENGINES = [("默认 (DirectWrite)", "default"), ("FreeType", "freetype")]

_PAGE_MARGIN = 36  # 分组左右留白（与大标题对齐）
_LOGO_SIZE = 64  # 顶部应用图标边长
_ROW_H = 60  # 展开区每行高度（addGroupWidget 靠固定高算展开高度）


class _WidgetSettingCard(SettingCard):
    """右侧可挂任意控件的设置行。

    库里只有 `PushSettingCard`（单个原生 QPushButton），这里复用同一套接线：
    `SettingCard.hBoxLayout` 末尾是 `addStretch(1)`，之后加的控件自然靠右排。

    横向 `Expanding` 的控件按 **stretch** 加而不是 `AlignRight`：带对齐标志的项拿的是
    sizeHint 宽度、不会被压缩，窄窗口下会把整行顶出卡片右边缘（代理地址框踩过）。
    """

    def __init__(self, icon, title, content=None, widgets=(), parent=None) -> None:
        super().__init__(icon, title, content, parent)
        for widget in widgets:
            widget.setParent(self)
            expanding = (
                widget.sizePolicy().horizontalPolicy()
                == QSizePolicy.Policy.Expanding
            )
            if expanding:
                self.hBoxLayout.addWidget(widget, 1)
            else:
                self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
            self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addSpacing(8)


def _expand_row(widgets, parent: QWidget | None = None) -> QWidget:
    """构造 `ExpandGroupSettingCard` 展开区的一行（左缩进对齐标题列）。

    `addGroupWidget` 按 `viewLayout.sizeHint()` 算展开高度，行必须有确定高度。
    """
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(48, 12, 24, 12)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        widget.setParent(row)
        layout.addWidget(widget, 1 if index == 0 else 0)
    row.setFixedHeight(_ROW_H)
    return row


def _button_box(buttons, parent: QWidget | None = None) -> QWidget:
    """把多个按钮包成一个控件。

    `HeaderSettingCard.addWidget` 每次调用都会重新把 `expandButton` 加进布局，
    **只能调一次**，所以多控件必须先包容器。
    """
    box = QWidget(parent)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for button in buttons:
        button.setParent(box)
        layout.addWidget(button)
    return box


class SettingPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._probed_proxy = ""  # 「测试」按下时的地址，供失败提示回显
        # 扫码登录对话框。必须留引用：只 show() 不持有的话 Python 包装器会被回收，
        # 对话框在轮询到一半时凭空消失
        self._loginDialog = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部身份区：整体居中，第一行大图标，第二行「应用名 + 版本胶囊」
        self.titleLabel = TitleLabel("BiliEmojiDD", self)
        self.logoIcon = IconWidget(app_icon(), self)
        self.logoIcon.setFixedSize(_LOGO_SIZE, _LOGO_SIZE)
        self.versionLabel = version_badge(APP_VERSION, self)
        # 缩进/留白走布局边距，不用 setContentsMargins：Label 套了组件库 QSS，
        # QStyleSheetStyle 会用 QSS 盒模型重算 contentsMargins，手动设的被忽略
        header_box = QVBoxLayout()
        header_box.setContentsMargins(_PAGE_MARGIN, 20, _PAGE_MARGIN, 16)
        header_box.setSpacing(6)
        header_box.addWidget(
            self.logoIcon, 0, Qt.AlignmentFlag.AlignHCenter
        )
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)
        name_row.addStretch(1)
        name_row.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        # 版本胶囊贴着应用名底部排
        name_row.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignBottom)
        name_row.addStretch(1)
        header_box.addLayout(name_row)
        root.addLayout(header_box)

        self.scrollArea = ScrollArea(self)
        self.scrollWidget = QWidget()
        self.scrollWidget.setObjectName("settingScrollWidget")
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.expandLayout.setContentsMargins(_PAGE_MARGIN, 0, _PAGE_MARGIN, 24)
        self.expandLayout.setSpacing(28)
        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # FluentWindow 给 stackedWidget 套了 QSS，页面靠「自己不画背景」透出窗口底色；
        # QScrollArea 是原生控件，不显式透明会在暗色下露出 palette 的 Base 色块。
        # `.QWidget` 类选择器只命中 viewport / scrollWidget 这类纯 QWidget，不级联到卡片。
        self.scrollArea.setStyleSheet(
            "QScrollArea{border:none;background:transparent}"
            ".QWidget{background:transparent}"
        )
        # 本页与主页同样重（单帧重绘十几毫秒），按上游默认的 24 帧 / 格滚必掉帧
        tune_scroll(self.scrollArea)
        root.addWidget(self.scrollArea, 1)

        # 「关于」放第一个：分组按加入 expandLayout 的顺序自上而下排
        self._build_about_group()
        self._build_account_group()
        self._build_download_group()
        self._build_cache_group()
        self._build_theme_group()

    # ---- 关于 ----
    def _build_about_group(self) -> None:
        group = SettingCardGroup("关于", self.scrollWidget)

        self.repoCard = _WidgetSettingCard(
            FluentIcon.GITHUB,
            "代码仓库",
            REPO_SLUG,
            [HyperlinkButton(REPO_URL, "打开仓库", group, FluentIcon.LINK)],
            group,
        )

        self.checkUpdateBtn = BusyPushButton("检查更新", group)
        self.checkUpdateBtn.reserve_busy("检查中")
        self.updateCard = _WidgetSettingCard(
            FluentIcon.UPDATE,
            "检查更新",
            f"当前版本 v{APP_VERSION}",
            [self.checkUpdateBtn],
            group,
        )

        self.autoUpdateSwitch = SwitchButton(group)
        self.autoUpdateSwitch.setOnText("开")
        self.autoUpdateSwitch.setOffText("关")
        self.autoUpdateSwitch.setChecked(cfg.auto_check_update.value)
        self.autoUpdateCard = _WidgetSettingCard(
            FluentIcon.SYNC,
            "自动检查更新",
            "每次启动应用时在后台检查一次；没有新版本时不打扰",
            [self.autoUpdateSwitch],
            group,
        )

        self.mirrorCard = MirrorSettingCard(group)
        self.mirrorCard.notify = self._notify_from_card
        # 断言脚本与外部按名取用；卡片内部才是真正的持有者
        self.mirrorCombo = self.mirrorCard.combo

        self.licenseCard = _WidgetSettingCard(
            FluentIcon.CERTIFICATE,
            "开源许可",
            "本项目 GPL-3.0 · 依赖 PySide6 (LGPLv3) / PySide6-Fluent-Widgets (GPLv3)",
            [HyperlinkButton(LICENSE_URL, "查看协议", group, FluentIcon.LINK)],
            group,
        )

        group.addSettingCards(
            [
                self.repoCard,
                self.updateCard,
                self.autoUpdateCard,
                self.mirrorCard,
                self.licenseCard,
            ]
        )
        self.expandLayout.addWidget(group)
        self.aboutGroup = group

        self.checkUpdateBtn.clicked.connect(self._on_check_update)
        self.autoUpdateSwitch.checkedChanged.connect(self._on_auto_update_toggled)

    def _notify_from_card(self, kind: str, title: str, content: str) -> None:
        """给 `MirrorSettingCard` 用的提示出口——组件不直接依赖本页的提示风格。"""
        {"success": notify_success, "warning": notify_warning, "error": notify_error}.get(
            kind, notify_info
        )(title, content, parent=self, position=InfoBarPosition.TOP_RIGHT)

    def _on_auto_update_toggled(self, enabled: bool) -> None:
        # 即时生效：设置页所有开关 / 下拉 / 输入都是「改完即落库」，没有保存按钮
        qconfig.set(cfg.auto_check_update, enabled)

    def _on_mirror_changed(self, index: int) -> None:
        mirror = self.mirrorCombo.itemData(index)
        if mirror is None:
            return
        qconfig.set(cfg.gh_mirror, mirror)

    def _on_check_update(self) -> None:
        self.checkUpdateBtn.set_busy(True)
        run_task(
            fetch_latest_release,
            on_success=self._on_release,
            on_error=self._on_update_failed,
            on_finished=lambda ok: self.checkUpdateBtn.set_busy(False),
        )

    def _on_release(self, info) -> None:
        if not is_newer(info.tag, APP_VERSION):
            self.updateCard.setContent(f"已是最新版本 v{APP_VERSION}")
            notify_success(
                "已是最新版本",
                f"当前 v{APP_VERSION}，仓库最新发布为 {info.tag or '（无）'}",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self.updateCard.setContent(f"发现新版本 {info.tag}（当前 v{APP_VERSION}）")
        show_update_dialog(info, self.window())

    def _on_update_failed(self, exc: Exception) -> None:
        if isinstance(exc, NoRelease):
            notify_info(
                "暂无发布版本",
                f"{REPO_SLUG} 还没有发布过 Release",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        lines = [cause_hint(exc) or str(exc) or type(exc).__name__]
        if not cfg.gh_mirror.value:
            lines.append("直连 GitHub 不通时，可在上方「下载加速」选一个镜像后重试。")
        notify_error(
            "检查更新失败",
            "\n".join(lines),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=NEVER_DISMISS,
        )

    # ---- 账号 ----
    def _build_account_group(self) -> None:
        group = SettingCardGroup("账号", self.scrollWidget)

        # 一张卡承载「登录 + 账号」两件事，按登录态切换内容——不并排放两张卡。
        # 三个按钮各自连自己的槽、靠显隐切换，**不做「一个按钮换文案换行为」**
        # 那种状态耦合（那种写法迟早出双触发）
        self.avatar = AccountAvatar(group)
        self.manualCookieBtn = PushButton("手动填写", group)
        self.scanLoginBtn = PrimaryPushButton("扫码登录", group)
        self.logoutBtn = PushButton("退出登录", group)
        self.loginCard = _WidgetSettingCard(
            FluentIcon.PEOPLE,
            "B 站账号",
            "未登录 — 部分功能需要登录",
            [self.avatar, self.manualCookieBtn, self.scanLoginBtn, self.logoutBtn],
            group,
        )

        self.verifyBtn = PushButton("验证", group)
        self.verifyCard = _WidgetSettingCard(
            FluentIcon.CERTIFICATE,
            "访问权限",
            "用当前 Cookie 试拉取全部表情包，确认登录是否有效",
            [self.verifyBtn],
            group,
        )

        self.configCard = SettingCard(
            FluentIcon.DOCUMENT,
            "配置文件",
            str(APP_CONFIG_DIR / "config.json"),
            group,
        )

        group.addSettingCards([self.loginCard, self.verifyCard, self.configCard])
        self.expandLayout.addWidget(group)
        self.accountGroup = group

        self._sync_account_card()
        self.manualCookieBtn.clicked.connect(self._on_manual_cookie)
        self.scanLoginBtn.clicked.connect(self._on_login_clicked)
        self.logoutBtn.clicked.connect(self._on_logout)
        self.verifyBtn.clicked.connect(self._on_verify)

    def _sync_account_card(self) -> None:
        """按登录态切换这张卡的样子。**不联网**——启动时不该为它发请求。

        未登录给两条路（扫码为主、手动填写为退路），已登录只剩退出——两者
        **不同时出现**：都登上去了还摆着「手动填写」，看着就多余。
        """
        name = cfg.account_name.value.strip()
        mid = cfg.account_mid.value
        logged_in = bool(cfg.cookie.value.strip())
        # 文案刻意短：这一行在窄窗口（约 600px）下要和头像、按钮并排，
        # 太长会把行顶出卡片
        if name:
            content = f"{name} · UID {mid}" if mid else name
        elif logged_in:
            content = "已登录"
        else:
            content = "未登录 — 部分功能需要登录"
        self.loginCard.setContent(content)
        self.avatar.set_url(cfg.account_face.value.strip())
        self.manualCookieBtn.setVisible(not logged_in)
        self.scanLoginBtn.setVisible(not logged_in)
        self.logoutBtn.setVisible(logged_in)

    def _on_login_clicked(self) -> None:
        self._loginDialog = show_login_dialog(
            self.window(),
            on_success=self._on_login_ok,
            proxies=current_proxies(),
        )

    def _on_manual_cookie(self) -> None:
        self._loginDialog = show_cookie_dialog(
            self.window(),
            cookie=cfg.cookie.value,
            on_save=self._on_cookie_saved,
        )

    def _on_login_ok(self, cookie: str) -> None:
        """扫码确认后：Cookie 立即落盘生效，账号信息随后异步补上。"""
        self._apply_cookie(cookie)
        notify_success(
            "登录成功",
            "Cookie 已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_cookie_saved(self, cookie: str) -> None:
        """手动填写保存后：与扫码走同一条路，只是措辞不同。"""
        self._apply_cookie(cookie)
        notify_success(
            "已保存",
            "Cookie 已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_logout(self) -> None:
        """退出登录：只清登录态，下载目录、已下载文件与缓存都不动。"""
        box = MessageBox(
            "退出登录",
            "将清除本机保存的 Cookie 与账号信息。\n"
            "下载目录、已下载的文件与缓存都不受影响。",
            self.window(),
        )
        # 组件库 MessageBox 的按钮默认是英文（OK / Cancel），必须自己写中文
        box.yesButton.setText("退出")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self._apply_cookie("")
        notify_info(
            "已退出登录",
            "Cookie 与账号信息已清除",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _apply_cookie(self, cookie: str) -> None:
        """写入 Cookie 并同步界面 —— 扫码 / 手动填写 / 退出登录**三条路的唯一汇合点**。

        **换了值就先清掉上一个账号的昵称头像**：新的 nav 请求回来之前若继续显示
        旧昵称，用户会以为登的还是那个号。

        **Cookie 有效性记录一律作废**（不看值有没有变）：用户重新填一遍就是
        「我要重新验证」的意思，不能因为指纹恰好没变就把上一盏红灯继续摆下去。
        紧接着的 `_refresh_account` 会用一次 nav 重新给出结论。
        """
        changed = cookie != cfg.cookie.value
        cookie_status.invalidate()
        qconfig.set(cfg.cookie, cookie)
        if changed:
            qconfig.set(cfg.account_name, "")
            qconfig.set(cfg.account_mid, 0)
            qconfig.set(cfg.account_face, "")
        self._sync_account_card()
        signal_bus.configChanged.emit()
        self._refresh_account(cookie)

    def _refresh_account(self, cookie: str = "") -> None:
        """查一次「当前登的是谁」并记下来。拿不到就静默——不拿它当错误报。

        这一次 `nav` 同时是 Cookie 有效性的权威判据：结果并进 `cookie_status`
        的同一份记录，主页的状态灯因此不必再多打一次请求。
        """
        cookie = (cookie or cfg.cookie.value).strip()
        if not cookie:
            return
        # 代理在主线程读好再交给 worker：worker 线程不碰 cfg（见 net.py 模块说明）
        proxies = current_proxies()
        run_task(
            lambda: fetch_account(cookie, proxies=proxies),
            on_success=lambda account: self._on_account(account, cookie),
            on_error=lambda _e: None,  # 网络失败不改状态（网络不通不算 Cookie 失效）
        )

    def _on_account(self, account, cookie: str = "") -> None:
        # 「B 站明确说没登录」= 失效；网络异常走不到这里。Cookie 用发起时的快照，
        # 免得中途登出 / 换号把结论写到别人头上
        cookie_status.note(
            cookie_status.VALID if account else cookie_status.INVALID, cookie
        )
        if account is None:
            return
        qconfig.set(cfg.account_name, account.name)
        qconfig.set(cfg.account_mid, account.mid)
        qconfig.set(cfg.account_face, account.face)
        self._sync_account_card()

    def _on_verify(self) -> None:
        """验证**生效的** Cookie —— 不再读某个输入框，那就是配置里这一个值。"""
        cookie = cfg.cookie.value.strip()
        if not cookie:
            notify_warning(
                "未登录",
                "请先扫码登录或手动填写 Cookie",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self.verifyBtn.setEnabled(False)

        # 以 biliemoji 2.0.0 实际 API 为准：all_packages() 会校验 cookie 并可能拉取全量
        def task():
            return make_emoji(cookie=cookie).all_packages()

        run_task(
            task,
            on_success=self._on_verify_ok,
            on_error=self._on_verify_failed,
            on_finished=lambda ok: self.verifyBtn.setEnabled(True),
        )

    def _on_verify_failed(self, exc) -> None:
        """验证失败：只有明确的鉴权失败才动状态。

        其它失败（网络 / 风控 / 超时）保持原状——错误提示已经由 `show_bili_error`
        给出，不该顺手把状态灯判红。
        """
        if isinstance(exc, AuthRequired):
            cookie_status.invalidate()
        show_bili_error(exc, self)

    def _on_verify_ok(self, packages) -> None:
        notify_success(
            "验证通过",
            f"表情包访问权限有效，共 {len(packages)} 个表情包",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )
        # 并进同一份 Cookie 状态（主页的灯读它），顺带把这批全量写进缓存——
        # 主页那次静默预拉取随后命中缓存、零请求
        cookie = cfg.cookie.value
        cookie_status.note(cookie_status.VALID, cookie)
        save_all_packages_cache(cookie, packages)
        # 顺手把昵称头像补上：验证过了说明 Cookie 可用，账号信息也该拿得到
        self._refresh_account()

    # ---- 下载 ----
    def _build_download_group(self) -> None:
        group = SettingCardGroup("下载", self.scrollWidget)

        self.dirCard = ExpandGroupSettingCard(
            FluentIcon.DOWNLOAD,
            "下载目录",
            cfg.download_dir.value,
            group,
        )
        self.dirEdit = LineEdit(self.dirCard)
        self.dirEdit.setText(cfg.download_dir.value)
        self.browseBtn = PushButton("选择文件夹", self.dirCard)
        self.openDirBtn = PushButton("打开下载文件夹", self.dirCard)
        self.dirCard.addWidget(_button_box([self.browseBtn, self.openDirBtn]))
        self.dirCard.addGroupWidget(_expand_row([self.dirEdit]))
        # 副标题跟随路径（纯展示同步）；
        # ExpandSettingCard 自身没有 setContent，标题行在 .card 上
        self.dirEdit.textChanged.connect(self.dirCard.card.setContent)
        # 空目录不是合法状态（下载会落到当前工作目录），所以清空后失焦会被填回来
        self.dirCard.setToolTip(
            "改完按回车或点到别处立即生效。\n"
            "目录不能为空：清空后焦点移开会自动填回当前目录。"
        )
        self.dirCard.installEventFilter(
            ToolTipFilter(self.dirCard, 500, ToolTipPosition.TOP)
        )

        # 代理 = 往 requests 里填的那个 proxies 值，就一行地址。
        # 开关关着时地址框不可编辑，且应用彻底直连（连系统代理都不读，见 app/common/net.py）
        self.proxySwitch = SwitchButton(group)
        self.proxySwitch.setOnText("开")
        self.proxySwitch.setOffText("关")
        self.proxySwitch.setChecked(cfg.proxy_enabled.value)
        self.proxyEdit = LineEdit(group)
        self.proxyEdit.setPlaceholderText(PROXY_PLACEHOLDER)
        self._set_proxy_text(cfg.proxy.value)
        # 宽度交给布局：最窄能缩到 150（够看清 127.0.0.1:7890），宽窗口最多长到 320
        self.proxyEdit.setMinimumWidth(150)
        self.proxyEdit.setMaximumWidth(320)
        self.proxyEdit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.proxyTestBtn = BusyPushButton("测试", group)
        self.proxyTestBtn.reserve_busy("测试中")
        self.proxyCard = _WidgetSettingCard(
            FluentIcon.GLOBE,
            "代理",
            "关闭时直连；开启后请求走此地址",  # 副标题随即被 _refresh_proxy_content 换成生效值
            [self.proxySwitch, self.proxyEdit, self.proxyTestBtn],
            group,
        )
        self.proxyCard.setToolTip(
            "这里填的就是 requests 的 proxies 值，形如 http://127.0.0.1:7890。\n"
            "支持 http / https / socks5 / socks5h，要认证就写成\n"
            "http://用户名:密码@主机:端口。协议指的是代理自身说什么协议。\n"
            "应用不读 Windows 系统代理，也不读 HTTP_PROXY 环境变量——\n"
            "开关关掉就是直连。\n"
            "\n"
            "「测试」用当前填写的值（不必先保存）向下面这个接口发一次真实请求：\n"
            f"    GET {PROBE_URL}\n"
            f"（{PROBE_NAME}，不需要 Cookie；搜不到结果也算通，只要请求本身打通）\n"
            "ping 通不代表那个端口上有可用代理，所以要真发一次。"
        )
        # 组件库风格的提示气泡（原生 tooltip 不跟主题）
        self.proxyCard.installEventFilter(
            ToolTipFilter(self.proxyCard, 500, ToolTipPosition.TOP)
        )
        self._sync_proxy_enabled(self.proxySwitch.isChecked())

        self.threadSpin = SpinBox(group)
        self.threadSpin.setRange(1, 16)
        self.threadSpin.setValue(cfg.max_workers.value)
        self.threadSpin.setFixedWidth(110)
        self.threadCard = _WidgetSettingCard(
            FluentIcon.SPEED_HIGH,
            "下载线程数",
            "同时下载的文件数（1–16），改完即时生效",
            [self.threadSpin],
            group,
        )

        # 这一组**没有「保存」按钮**：下载目录、线程数、代理全是改完即时生效。
        # 手动保存那套的代价是「界面和配置文件可以不一致」——用户在框里清空了地址
        # 却没点保存，文件里那个旧值会一直留着（代理开关因此被自动拨开过，见
        # app/common/config.py::_migrate 的说明）。
        group.addSettingCards(
            [
                self.dirCard,
                self.proxyCard,
                self.threadCard,
            ]
        )
        self.expandLayout.addWidget(group)
        self.downloadGroup = group

        self.browseBtn.clicked.connect(self._on_browse)
        self.openDirBtn.clicked.connect(self._on_open_dir)
        self.proxyTestBtn.clicked.connect(self._on_test_proxy)
        self.proxySwitch.checkedChanged.connect(self._on_proxy_toggled)
        # 三条都即时生效，不等「保存」——改了 IP 却忘了保存，其它请求还在用旧地址，
        # 而报错里显示的又是配置里那个旧值，根本对不上（踩过）
        self.proxyEdit.editingFinished.connect(self._autosave_proxy)
        self.dirEdit.editingFinished.connect(self._autosave_dir)
        # 接线放在 setRange/setValue 之后：构造期那次 setValue 早于 connect，不会误写
        self.threadSpin.valueChanged.connect(self._autosave_threads)

    def _sync_proxy_enabled(self, enabled: bool) -> None:
        """开关关着时连填都填不了——「没开代理」这件事在界面上就是确定的。"""
        self.proxyEdit.setEnabled(enabled)
        if not self.proxyTestBtn.is_busy():  # 测试进行中由 set_busy 管，别插手
            self.proxyTestBtn.setEnabled(enabled)
        self._refresh_proxy_content()

    def _set_proxy_text(self, text: str) -> None:
        """回填地址并把光标移回开头。

        地址常常比输入框宽，`setText` 后光标停在末尾、框里只看得到尾巴
        （`p://1.2.3.4:8181`），从头显示才认得出是哪个代理。
        """
        self.proxyEdit.setText(text)
        self.proxyEdit.setCursorPosition(0)

    def _refresh_proxy_content(self) -> None:
        """副标题显示**当前生效**的代理（读 cfg，不是读输入框）。

        输入框里是「正在编辑的值」，cfg 里才是「其它请求真正在用的值」，
        两者可能不同步——把生效值摆出来，省得对着报错猜。
        """
        if not cfg.proxy_enabled.value:
            self.proxyCard.setContent("已关闭：所有请求直连，不读系统代理")
            return
        address = redact_proxy(cfg.proxy.value)
        self.proxyCard.setContent(
            f"当前生效：{address}" if address else "已开启但地址为空，仍是直连"
        )

    def _on_proxy_toggled(self, enabled: bool) -> None:
        qconfig.set(cfg.proxy_enabled, enabled)
        self._sync_proxy_enabled(enabled)

    def _autosave_proxy(self) -> None:
        """地址框回车 / 失焦即落库（`MainWindow.closeEvent` 的补写也走它）。

        静默版：地址不合法就不写也不弹提示（切个焦点就弹一次太吵），
        报错留给显式的「测试」。空地址照写——`current_proxies()` 本来就把
        「开着但地址为空」当直连，写进去才能让副标题与实际行为一致，
        也免得「界面清空了、文件里还留着老地址」。
        """
        text = self.proxyEdit.text().strip()
        if " " in text:
            return
        address = normalize_proxy(text)
        if address != cfg.proxy.value:
            qconfig.set(cfg.proxy, address)
            self._set_proxy_text(address)  # 回填规范化后的地址
        self._refresh_proxy_content()

    def _current_proxy(self) -> str | None:
        """按当前控件值取代理地址；不合法时弹提示并返回 None。

        「测试」用这一个入口（以前「保存」也共用；保存按钮已删）：
        返回空串表示不使用代理。
        """
        if not self.proxySwitch.isChecked():
            return ""
        text = self.proxyEdit.text().strip()
        if not text:
            notify_warning(
                "未填写代理地址",
                "代理开关已打开但地址为空，请填写形如 " + PROXY_PLACEHOLDER + " 的地址，"
                "或关掉开关直连",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )
            return None
        if " " in text:
            notify_warning(
                "无效代理地址",
                "地址里不能有空格，格式为 协议://[用户名:密码@]主机:端口",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )
            return None
        return normalize_proxy(text)  # 无协议前缀时补 http://

    def _on_test_proxy(self) -> None:
        """按当前填写的值发一次真实请求——ping 通不代表那个端口上有代理。"""
        proxy_text = self._current_proxy()
        if proxy_text is None:
            return
        # 先落库再测：保证「测试通过的那个地址」就是「应用正在用的地址」
        self._autosave_proxy()
        # 记下被测的地址：失败提示要报**这个**值，而不是配置里那个（可能还没保存）
        self._probed_proxy = proxy_text
        self.proxyTestBtn.set_busy(True)

        def task():
            return probe_proxy(proxy_text)

        run_task(
            task,
            on_success=self._on_proxy_ok,
            on_error=self._on_proxy_failed,
            on_finished=lambda ok: self._on_test_finished(),
        )

    def _on_test_finished(self) -> None:
        """收环后按开关重新对齐可用性——测试期间开关可能已经被拨掉了。"""
        self.proxyTestBtn.set_busy(False)
        self._sync_proxy_enabled(self.proxySwitch.isChecked())

    def _on_proxy_ok(self, message: str) -> None:
        notify_success(
            "代理可用",
            message,
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )

    def _on_proxy_failed(self, exc: Exception) -> None:
        """测试失败走自己的提示，不用通用的 `show_bili_error`。

        通用提示报的是「网络错误 + 配置里的代理」，而这里要报的是「测试失败 + 你刚填的
        那个地址 + 打的是哪个接口」——不然看到 ProxyError 也不知道测了什么。
        """
        tested = redact_proxy(self._probed_proxy)
        lines = [cause_hint(exc) or str(exc) or type(exc).__name__]
        lines.append(f"测试地址：{tested or '（直连）'}")
        lines.append(f"测试接口：GET {PROBE_URL}")
        notify_error(
            "代理测试失败",
            "\n".join(lines),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=NEVER_DISMISS,  # 带诊断信息，让用户自己关（0 是「立刻消失」，别写 0）
        )

    def _on_browse(self) -> None:
        start = self.dirEdit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择下载目录", start)
        if directory:
            self.dirEdit.setText(directory)
            self._autosave_dir()  # setText 不发 editingFinished，手动落库

    def _on_open_dir(self) -> None:
        path = Path(self.dirEdit.text().strip() or cfg.download_dir.value)
        path.mkdir(parents=True, exist_ok=True)
        open_in_explorer(path, self)

    # ---- 下载组的即时生效（没有「保存」按钮） ----

    def _autosave_dir(self) -> None:
        """下载目录：回车 / 失焦即落库。

        空目录**不写**（写了下载会落到当前工作目录，等于把用户的文件撒到不知哪里），
        并把输入框**回填成当前生效值** —— 界面不允许停在一个配置文件里没有的路径上，
        否则又回到「界面和文件不一致」那类 bug。静默处理，不弹提示：切个焦点就弹一次太吵。
        """
        text = self.dirEdit.text().strip()
        if not text:
            self._set_dir_text(cfg.download_dir.value)
            return
        if text == cfg.download_dir.value:
            return
        qconfig.set(cfg.download_dir, text)
        self._set_dir_text(text)
        # 主页英雄卡那一行显示的就是下载目录，靠这个信号刷新
        signal_bus.configChanged.emit()

    def _set_dir_text(self, text: str) -> None:
        """回填目录并保持卡片副标题同步（副标题挂在 textChanged 上，setText 会带动它）。"""
        if self.dirEdit.text() != text:
            self.dirEdit.setText(text)

    def _autosave_threads(self, value: int) -> None:
        """线程数：拨一下即落库（与缓存组的上限 SpinBox 同一套）。"""
        qconfig.set(cfg.max_workers, int(value))

    def commit_pending_edits(self) -> None:
        """把「改了但还没失焦」的输入补写一次。

        由 `MainWindow.closeEvent` 在关窗那一刻调用：编辑完直接点 X / Alt+F4 时，
        输入框不一定会发 `editingFinished`，不补写就会出现「界面改了、文件里没改」。
        `qconfig.set` 是同步落盘（值变了就写文件），所以这里不需要等任何异步。
        """
        self._autosave_dir()
        self._autosave_proxy()

    # ---- 缓存 ----
    def _build_cache_group(self) -> None:
        group = SettingCardGroup("缓存", self.scrollWidget)

        self.cacheSpin = SpinBox(group)
        self.cacheSpin.setRange(64, 8192)
        self.cacheSpin.setSingleStep(64)
        self.cacheSpin.setValue(cfg.cache_limit_mb.value)
        # SpinBox 右侧上下按钮占掉约 64px，四位数要给够宽度否则被裁
        self.cacheSpin.setFixedWidth(140)
        self.cacheLimitCard = _WidgetSettingCard(
            FluentIcon.CLOUD,
            "缓存上限",
            "图片与接口响应最多占用的磁盘空间（64–8192 MB），修改后立即生效",
            [self.cacheSpin],
            group,
        )

        self.clearCacheBtn = PushButton("清除缓存", group)
        self.cacheUsageCard = _WidgetSettingCard(
            FluentIcon.BROOM,
            "缓存占用",
            "统计中…",
            [self.clearCacheBtn],
            group,
        )

        group.addSettingCards([self.cacheLimitCard, self.cacheUsageCard])
        self.expandLayout.addWidget(group)
        self.cacheGroup = group

        self.cacheSpin.valueChanged.connect(self._on_cache_limit_changed)
        self.clearCacheBtn.clicked.connect(self._on_clear_cache)
        self._refresh_cache_usage()

    def _on_cache_limit_changed(self, value: int) -> None:
        # 即时保存（同主题下拉的风格）：下次 put 时现读该值，无需重启
        qconfig.set(cfg.cache_limit_mb, value)
        self._refresh_cache_usage()

    def _refresh_cache_usage(self) -> None:
        """扫目录算占用。文件可能上万，放后台线程，避免卡住主线程。"""
        limit = cfg.cache_limit_mb.value

        def on_ok(used: int) -> None:
            self.cacheUsageCard.setContent(
                f"已用 {used / MB:.1f} MB / 上限 {limit} MB"
            )

        run_task(
            total_size,
            on_success=on_ok,
            on_error=lambda e: self.cacheUsageCard.setContent("缓存占用未知"),
        )

    def _on_clear_cache(self) -> None:
        self.clearCacheBtn.setEnabled(False)
        run_task(
            clear_all,
            on_success=self._on_cache_cleared,
            on_finished=self._on_clear_cache_finished,
        )

    def _on_cache_cleared(self, _result) -> None:
        notify_success(
            "已清除",
            "图片与接口响应缓存已清空",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_clear_cache_finished(self, _ok: bool) -> None:
        self.clearCacheBtn.setEnabled(True)
        self._refresh_cache_usage()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_cache_usage()  # 每次进设置页刷新占用

    # ---- 主题 ----
    def _build_theme_group(self) -> None:
        group = SettingCardGroup("外观", self.scrollWidget)

        self.themeCombo = ComboBox(group)
        # qfluentwidgets addItem(text, icon, userData)：图标用组件库 FluentIcon
        self.themeCombo.addItem("跟随系统", FluentIcon.SYNC, userData=Theme.AUTO)
        self.themeCombo.addItem("浅色", FluentIcon.BRIGHTNESS, userData=Theme.LIGHT)
        self.themeCombo.addItem("深色", FluentIcon.CONSTRACT, userData=Theme.DARK)
        self.themeCombo.setMinimumWidth(140)
        try:
            self.themeCombo.setCurrentIndex(_THEMES.index(cfg.theme.value))
        except ValueError:
            self.themeCombo.setCurrentIndex(0)
        self.themeCard = _WidgetSettingCard(
            FluentIcon.BRUSH,
            "应用主题",
            "调整应用的浅色 / 深色外观",
            [self.themeCombo],
            group,
        )

        self.fontEngineCombo = ComboBox(group)
        for text, value in _FONT_ENGINES:
            self.fontEngineCombo.addItem(text, userData=value)
        self.fontEngineCombo.setMinimumWidth(180)
        engines = [value for _, value in _FONT_ENGINES]
        try:
            self.fontEngineCombo.setCurrentIndex(engines.index(cfg.font_engine.value))
        except ValueError:
            self.fontEngineCombo.setCurrentIndex(0)
        self.fontEngineCard = _WidgetSettingCard(
            FluentIcon.FONT,
            "字体渲染",
            "文字发糊 / 有彩边时换 FreeType 试试，重启应用后生效",
            [self.fontEngineCombo],
            group,
        )

        group.addSettingCards([self.themeCard, self.fontEngineCard])
        self.expandLayout.addWidget(group)
        self.themeGroup = group

        self.themeCombo.currentIndexChanged.connect(self._on_theme_changed)
        self.fontEngineCombo.currentIndexChanged.connect(self._on_font_engine_changed)
        signal_bus.configChanged.connect(self._sync_theme_combo)
        # ComboBox 闭合态只 setText 不 setIcon（上游行为），须自己补；
        # 且 FluentIcon 按调用瞬间的主题取黑/白 svg，主题切换后要重取
        bind_theme(self, self._sync_theme_icon)

    def _on_font_engine_changed(self, index: int) -> None:
        """渲染后端是平台插件的启动参数，只能下次启动时生效（见 font.apply_font_engine）。"""
        engine = self.fontEngineCombo.itemData(index)
        if engine is None:
            return
        qconfig.set(cfg.font_engine, engine)
        notify_success(
            "已保存",
            "字体渲染将在下次启动应用时生效",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _sync_theme_icon(self) -> None:
        """把当前选中项的图标同步到下拉框闭合态（ComboBox 自身不做这件事）。"""
        self.themeCombo.setIconSize(QSize(16, 16))
        self.themeCombo.setIcon(
            self.themeCombo.itemIcon(self.themeCombo.currentIndex())
        )

    def _sync_theme_combo(self) -> None:
        """外部切换主题（侧栏按钮）后同步下拉框显示。"""
        try:
            index = _THEMES.index(cfg.theme.value)
        except ValueError:
            index = 0
        self.themeCombo.blockSignals(True)
        self.themeCombo.setCurrentIndex(index)
        self.themeCombo.blockSignals(False)
        self._sync_theme_icon()  # 信号被屏蔽，图标得手动补

    def _on_theme_changed(self, index: int) -> None:
        theme = self.themeCombo.itemData(index)
        if theme is None:
            return
        # 先 setTheme 再存 cfg.theme：保证保存时 QFluentWidgets.ThemeMode 与应用主题一致
        setTheme(theme)
        qconfig.set(cfg.theme, theme)
        self._sync_theme_icon()
