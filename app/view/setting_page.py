"""设置页：Cookie / 下载目录 / 主题（Fluent 设置卡片版式）。

版式参照 Win11 / QFluentWidgets Gallery 设置页：大标题 → 分组标题 → 每行一张
「图标 + 标题 / 灰色副标题 + 右侧控件」窄卡片，整页滚动。控件与槽函数沿用改版前
的实现，本文件只负责「控件怎么摆」。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    ExpandGroupSettingCard,
    ExpandLayout,
    FluentIcon,
    IconWidget,
    IndeterminateProgressRing,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
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

from app.common.config import APP_CONFIG_DIR, APP_VERSION, cfg
from app.common.exception import cause_hint, show_bili_error
from app.common.net import make_emoji
from app.common.notify import (
    NEVER_DISMISS,
    notify_error,
    notify_success,
    notify_warning,
)
from app.common.proxy import PROXY_PLACEHOLDER, normalize_proxy, redact_proxy
from app.common.resource import app_icon
from app.common.signal_bus import signal_bus
from app.common.theme import SECONDARY_TEXT, bind_theme
from app.components.disk_cache import MB, clear_all, total_size
from app.components.download_runner import open_in_explorer
from app.components.proxy_probe import PROBE_NAME, PROBE_URL, probe_proxy
from app.components.task import run_task

_THEMES = [Theme.AUTO, Theme.LIGHT, Theme.DARK]
# 字体渲染后端下拉：文案 -> cfg.font_engine 的取值
_FONT_ENGINES = [("默认 (DirectWrite)", "default"), ("FreeType", "freetype")]

_PAGE_MARGIN = 36  # 分组左右留白（与大标题对齐）
_LOGO_SIZE = 64  # 顶部应用图标边长
_ROW_H = 60  # 展开区每行高度（addGroupWidget 靠固定高算展开高度）
_RING_SIZE = 14  # 按钮内加载环直径
_RING_GAP = 10  # 加载环与文字之间的空隙
_BTN_PAD = 28  # 按钮左右内边距估值，用于预留忙碌态宽度


class _BusyPushButton(PushButton):
    """带加载环的按钮：忙碌时文字前面转圈，明示「正在跑」。

    组件库没有 loading 态按钮，这里自己拼：`IndeterminateProgressRing` 当子控件，
    忙碌时给文字前面塞若干空格腾位置，再把环挪到文字左边（按钮文字是居中画的，
    所以位置得按 `fontMetrics` 现算）。**空格数按空格实际宽度算而不是写死**——
    换字体空格宽度就变（Segoe UI 7px / LXGW 等宽 10px），写死会导致环压在文字上。

    **不覆写 `__init__`**：`PushButton.__init__` 是库自实现的 `singledispatchmethod`，
    `(text, parent)` 那个重载内部会**再调一次** `self.__init__(parent=parent)`，
    子类若加必填位置参数会直接 TypeError。初始化一律走库留的 `_postInit()` 钩子
    ——注意它在 `setText` 之前执行，所以空闲文案只能等 `reserve_busy()` 时再记。
    """

    def _postInit(self) -> None:
        self._ring = IndeterminateProgressRing(self, start=False)
        self._ring.setFixedSize(_RING_SIZE, _RING_SIZE)
        self._ring.setStrokeWidth(3)
        # 点击穿透：环盖在按钮上，不能吃掉点击
        self._ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ring.hide()
        self._idle_text = ""
        self._busy_text = ""

    def _busy_prefix(self) -> str:
        """够放下加载环 + 空隙的空格数（向上取整）。"""
        space = max(1, self.fontMetrics().horizontalAdvance(" "))
        return " " * -(-(_RING_SIZE + _RING_GAP) // space)

    def reserve_busy(self, busy_text: str) -> None:
        """按忙碌态的文字把宽度定死——否则一转圈按钮就变宽，整行跟着跳。"""
        self._idle_text = self.text()
        self._busy_text = busy_text
        width = self.fontMetrics().horizontalAdvance(
            self._busy_prefix() + busy_text
        ) + _BTN_PAD
        self.setFixedWidth(max(self.sizeHint().width(), width))

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.setText(self._busy_prefix() + (self._busy_text or self._idle_text))
            self._ring.show()
            self._ring.start()
        else:
            self._ring.stop()
            self._ring.hide()
            if self._idle_text:
                self.setText(self._idle_text)
        self.setEnabled(not busy)
        self._place_ring()

    def is_busy(self) -> bool:
        return not self._ring.isHidden()

    def _place_ring(self) -> None:
        # 判据用 isHidden 而非 isVisible：按钮尚未 show() 时子控件 isVisible() 恒为 False
        if self._ring.isHidden():
            return
        text_w = self.fontMetrics().horizontalAdvance(self.text())
        left = max(6, (self.width() - text_w) // 2)
        self._ring.move(left, (self.height() - _RING_SIZE) // 2)
        self._ring.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_ring()


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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部身份区：整体居中，第一行大图标，第二行「应用名 + 版本号」
        self.titleLabel = TitleLabel("BiliEmojiDD", self)
        self.logoIcon = IconWidget(app_icon(), self)
        self.logoIcon.setFixedSize(_LOGO_SIZE, _LOGO_SIZE)
        self.versionLabel = CaptionLabel(f"v{APP_VERSION}", self)
        self.versionLabel.setTextColor(*SECONDARY_TEXT)
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
        # 版本号贴着应用名底部排
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
        root.addWidget(self.scrollArea, 1)

        self._build_account_group()
        self._build_download_group()
        self._build_cache_group()
        self._build_theme_group()

    # ---- 账号 ----
    def _build_account_group(self) -> None:
        group = SettingCardGroup("账号", self.scrollWidget)

        self.cookieCard = ExpandGroupSettingCard(
            FluentIcon.VPN,
            "B 站 Cookie",
            "部分功能需要登录；Cookie 仅保存在本机配置中，不会上传",
            group,
        )
        self.cookieEdit = PasswordLineEdit(self.cookieCard)
        self.cookieEdit.setPlaceholderText("SESSDATA=...; bili_jct=...")
        self.cookieEdit.setText(cfg.cookie.value)
        self.saveBtn = PrimaryPushButton("保存", self.cookieCard)
        self.cookieCard.addGroupWidget(_expand_row([self.cookieEdit, self.saveBtn]))

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

        group.addSettingCards([self.cookieCard, self.verifyCard, self.configCard])
        self.expandLayout.addWidget(group)
        self.accountGroup = group

        # 还没填 Cookie 时直接展开：首次使用不用先找到那个 ⌄
        if not cfg.cookie.value.strip():
            self.cookieCard.setExpand(True)

        self.saveBtn.clicked.connect(self._on_save)
        self.verifyBtn.clicked.connect(self._on_verify)

    def _on_save(self) -> None:
        cookie = self.cookieEdit.text().strip().strip('"\'')
        qconfig.set(cfg.cookie, cookie)
        signal_bus.configChanged.emit()
        notify_success(
            "已保存",
            "Cookie 已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_verify(self) -> None:
        cookie = self.cookieEdit.text().strip().strip('"\'')
        if not cookie:
            notify_warning(
                "未填写 Cookie",
                "请先填写 Cookie 再验证",
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
            on_error=lambda e: show_bili_error(e, self),
            on_finished=lambda ok: self.verifyBtn.setEnabled(True),
        )

    def _on_verify_ok(self, packages) -> None:
        notify_success(
            "验证通过",
            f"表情包访问权限有效，共 {len(packages)} 个表情包",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

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
        # 副标题跟随路径（纯展示同步，保存逻辑仍读 dirEdit）；
        # ExpandSettingCard 自身没有 setContent，标题行在 .card 上
        self.dirEdit.textChanged.connect(self.dirCard.card.setContent)

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
        self.proxyTestBtn = _BusyPushButton("测试", group)
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
            "同时下载的文件数（1–16）",
            [self.threadSpin],
            group,
        )

        self.downloadSaveBtn = PrimaryPushButton("保存", group)
        self.saveDownloadCard = _WidgetSettingCard(
            FluentIcon.SAVE,
            "保存下载设置",
            "下载目录与线程数修改后需保存才生效（代理改完即时生效）",
            [self.downloadSaveBtn],
            group,
        )

        group.addSettingCards(
            [
                self.dirCard,
                self.proxyCard,
                self.threadCard,
                self.saveDownloadCard,
            ]
        )
        self.expandLayout.addWidget(group)
        self.downloadGroup = group

        self.browseBtn.clicked.connect(self._on_browse)
        self.openDirBtn.clicked.connect(self._on_open_dir)
        self.downloadSaveBtn.clicked.connect(self._on_save_download)
        self.proxyTestBtn.clicked.connect(self._on_test_proxy)
        self.proxySwitch.checkedChanged.connect(self._on_proxy_toggled)
        # 代理即时生效，不等「保存下载设置」——改了 IP 却忘了点保存，其它请求还在用旧地址，
        # 而报错里显示的又是配置里那个旧值，根本对不上（踩过）
        self.proxyEdit.editingFinished.connect(self._autosave_proxy)

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
        """地址框回车 / 失焦即保存。

        静默版：地址不合法就不写也不弹提示（切个焦点就弹一次太吵），
        报错留给显式的「保存」与「测试」。空地址照写——`current_proxies()` 本来就把
        「开着但地址为空」当直连，写进去才能让副标题与实际行为一致。
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

        保存与「测试」共用这一个入口。返回空串表示不使用代理。
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

    def _on_open_dir(self) -> None:
        path = Path(self.dirEdit.text().strip() or cfg.download_dir.value)
        path.mkdir(parents=True, exist_ok=True)
        open_in_explorer(path, self)

    def _on_save_download(self) -> None:
        directory = self.dirEdit.text().strip()
        if not directory:
            notify_warning(
                "下载目录为空",
                "请选择下载目录",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        proxy_text = self._current_proxy()
        if proxy_text is None:  # 校验未过，提示已弹
            return
        qconfig.set(cfg.download_dir, directory)
        qconfig.set(cfg.proxy_enabled, self.proxySwitch.isChecked())
        # 关开关时不清空地址：下次打开还在。current_proxies() 只看开关
        if proxy_text:
            qconfig.set(cfg.proxy, proxy_text)
            self._set_proxy_text(proxy_text)  # 回填规范化后的地址
        self._refresh_proxy_content()
        qconfig.set(cfg.max_workers, self.threadSpin.value())
        signal_bus.configChanged.emit()
        notify_success(
            "已保存",
            "下载目录与线程数已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

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
