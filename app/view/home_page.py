"""主页：应用介绍 + 功能入口引导（启动默认页）。

启动落在表情包页的「按 ID 查询」标签时整页是空的，既不好看也没告诉用户能做什么。
本页用 Fluent 卡片版式回答三个问题：这是什么、我能做什么、我该从哪一步开始。

五个模块，自上而下：

1. `_HeroCard`   —— logo / 应用名 / 版本 / 一句话简介 + 状态概览 + 主按钮（随 Cookie 状态变）
2. `_FeatureCard` ×3 —— 表情包 / 收藏集 / 下载，整卡可点，前两张带 `static/showcase` 本地展示图
3. `_QuickStartCard` —— 三步上手，每步一个跳转按钮
4. `_AboutCard`  —— 版本 / SDK / 链接 / 配置目录 / 免责声明
5. `_RecentSearchCard` —— 复用搜索历史，点胶囊直接带关键词跳到对应页搜索

**本页零网络请求**：展示图来自 `static/showcase/`（由 `scripts/fetch_showcase.py` 一次性
抓好入库），状态数据全是本地配置与内存队列。

导航一律走信号（`navigateRequested` / `searchRequested`）交给 `MainWindow` 处理，
本页不反向引用主窗口。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FlowLayout,
    FluentIcon,
    HyperlinkButton,
    IconWidget,
    ImageLabel,
    PillPushButton,
    PrimaryPushButton,
    ScrollArea,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    TransparentPushButton,
)

from app.common.config import APP_CONFIG_DIR, APP_VERSION, cfg
from app.common.resource import (
    PYSIDE_LOGO_PATH,
    QFLUENT_LOGO_PATH,
    app_icon,
    showcase_images,
    showcase_names,
)
from app.common.signal_bus import signal_bus
from app.common.theme import ORANGE_TEXT, SECONDARY_TEXT
from app.components.download_queue import download_queue, item_cover_url
from app.components.download_runner import open_in_explorer
from app.components.page_scaffold import (
    PAGE_BOTTOM,
    PAGE_MARGIN,
    SECTION_SPACING,
    SectionCard,
    page_title,
    title_row,
    version_badge,
)
from app.components.search_history import SearchHistory
from app.components.thumb import thumb_manager

# 导航 key：与 MainWindow._navigate 的映射表一一对应
NAV_EMOJI = "emoji"
NAV_DRESS = "dress"
NAV_DOWNLOAD = "download"
NAV_SETTING = "setting"

_LOGO_SIZE = 56
_EMOJI_THUMB = 52  # 表情展示图边长（方形）
_COLL_THUMB_W = 54  # 收藏集封面宽（3:4 竖版）
_STRIP_SPACING = 6
_CARD_MIN_W = 300  # 功能卡最小宽度，据此算响应式列数
_BOTTOM_MIN_W = 320  # 快速上手 / 关于卡的最小宽度
_DEP_LOGO_H = 22  # 「关于」卡里依赖徽标的高度
_QUEUE_THUMB = 44  # 下载卡队列预览封面边长
_PROJECT_URL = "https://pypi.org/project/biliemoji/"

_INTRO = "B 站表情包 / 收藏集（装扮）下载器：查询、预览、批量下载，一站搞定。"
_DISCLAIMER = "所有接口来自 B 站公开 API，可能随官方更新失效；仅供学习交流，请勿滥用。"


def _sdk_version() -> str:
    """biliemoji 版本。它是正常安装的包（本应用 package=false 才拿不到版本）。"""
    try:
        from importlib.metadata import version

        return version("biliemoji")
    except Exception:  # noqa: BLE001 拿不到版本不该影响主页
        return "?"


def _fit_image(label: ImageLabel, image: QImage, width: int, height: int) -> None:
    """把图预缩放到 width×height×dpr 交给 ImageLabel，再把控件钉回逻辑尺寸。

    **`ImageLabel.paintEvent` 每次重绘都会 `self.image.scaled(self.size()*dpr, …,
    SmoothTransformation)`**：源图尺寸对不上时，每一帧都要做一次平滑缩放。主页一屏十几张
    图叠上卡片 hover 动画就是肉眼可见的掉帧（其他页面的卡片走 `QPushButton.setIcon`，
    缩放只做一次，所以不卡）。

    `QImage::scaled` 在目标尺寸与自身相同时直接返回隐式共享副本、零像素开销，
    所以预先缩放到恰好 `size*dpr` 就把每帧的缩放变成了恒等操作——
    与 `image_viewer._letterbox` 让 delegate 的 scaled 成为恒等变换是同一招。
    """
    dpr = label.devicePixelRatioF()
    target = QSize(max(1, int(width * dpr)), max(1, int(height * dpr)))
    if not image.isNull():
        # 素材已按目标比例裁好（fetch_showcase / _cover_square），这里是等比缩放
        label.setImage(
            image.scaled(
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    label.setFixedSize(width, height)  # setImage 会按像素尺寸设死，改回逻辑尺寸


def _cover_square(pixmap, side: int, dpr: float) -> QImage:
    """封面裁成正方形：等比放大盖满后居中裁到恰好 side*dpr（保证 _fit_image 是恒等变换）。"""
    px = max(1, int(side * dpr))
    image = pixmap.toImage().scaled(
        px,
        px,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    return image.copy((image.width() - px) // 2, (image.height() - px) // 2, px, px)


class _ShowcaseStrip(QWidget):
    """一排本地展示图（表情方图 / 收藏集竖版封面）。

    图片全部来自 `static/showcase/`，读不出来就跳过；一张都没有时整条隐藏，
    由调用方按 `has_images()` 决定要不要加进布局。
    """

    def __init__(
        self, kind: str, *, width: int, ratio: float, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._item_w = width
        self._visible = -1  # 当前显示张数，用于 _fit() 早退

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_STRIP_SPACING)
        # 子项是定尺寸的图，布局默认会把「全部图排一行」的宽度当成本控件的最小宽度，
        # 反过来把整张功能卡撑到 400+ px（窄窗口下卡片被裁掉而不是缩小）。
        # SetNoConstraint 让布局不再回写控件的最小尺寸，放不下的图交给 _fit() 隐藏。
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(0)

        names = showcase_names(kind)
        self._labels: list[ImageLabel] = []
        height = int(width * ratio)
        for path in showcase_images(kind):
            source = QImage(str(path))
            if source.isNull():  # 文件损坏 / 格式不支持
                continue
            label = ImageLabel(self)
            label.setBorderRadius(6, 6, 6, 6)
            # 预缩放到 size*dpr：否则每帧重绘都要平滑缩放一次（见 _fit_image）
            _fit_image(label, source, width, height)
            label.setToolTip(names.get(path.name, ""))
            layout.addWidget(label)
            self._labels.append(label)
        layout.addStretch(1)
        self.setFixedHeight(height if self._labels else 0)

    def has_images(self) -> bool:
        return bool(self._labels)

    def count(self) -> int:
        return len(self._labels)

    def visible_count(self) -> int:
        return sum(1 for lbl in self._labels if not lbl.isHidden())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """按可用宽度增减显示张数。

        只做离散的 setVisible 切换（张数没变直接 return），**不是**在 resizeEvent 里
        写几何约束——后者拖拽窗口时每帧要跑好几轮「改约束 → 重排 → 又一次 resize」。
        """
        if not self._labels:
            return
        step = self._item_w + _STRIP_SPACING
        n = max(1, min(len(self._labels), (self.width() + _STRIP_SPACING) // step))
        if n == self._visible:
            return
        self._visible = n
        for index, label in enumerate(self._labels):
            label.setVisible(index < n)


class _FeatureCard(CardWidget):
    """功能入口卡：整卡可点（`CardWidget.clicked` 无参），带 hover 背景动画。

    中部内容区由调用方塞入：前两张是 `_ShowcaseStrip`，下载卡是队列统计文字。
    """

    def __init__(
        self, icon, title: str, desc: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setClickEnabled(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(_CARD_MIN_W)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(20, 16, 20, 12)
        self.vBoxLayout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(20, 20)
        self.titleLabel = SubtitleLabel(title, self)
        head.addWidget(self.iconWidget, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.vBoxLayout.addLayout(head)

        # 不换行的 Label 最小宽度就是整串文字宽度，会把整页最小宽度顶起来
        self.descLabel = BodyLabel(desc, self)
        self.descLabel.setTextColor(*SECONDARY_TEXT)
        self.descLabel.setWordWrap(True)
        self.vBoxLayout.addWidget(self.descLabel)

        self.vBoxLayout.addStretch(1)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        self.enterBtn = TransparentPushButton(FluentIcon.CHEVRON_RIGHT, "进入", self)
        # 卡片本身可点，按钮只是视觉指引——点它等同点卡片
        self.enterBtn.clicked.connect(self.clicked.emit)
        foot.addWidget(self.enterBtn)
        self.vBoxLayout.addLayout(foot)

    def add_content(self, widget: QWidget) -> None:
        """把内容插到说明文字与底部弹簧之间。"""
        widget.setParent(self)
        self.vBoxLayout.insertWidget(2, widget)


class _HeroCard(SimpleCardWidget):
    """顶部欢迎卡：品牌 + 简介 + 状态概览 + 主按钮。"""

    navigate = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        self.logoIcon = IconWidget(app_icon(), self)
        self.logoIcon.setFixedSize(_LOGO_SIZE, _LOGO_SIZE)
        layout.addWidget(self.logoIcon, 0, Qt.AlignmentFlag.AlignTop)

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.titleLabel = TitleLabel("BiliEmojiDD", self)
        self.versionLabel = version_badge(APP_VERSION, self)
        name_row.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignBottom)
        name_row.addStretch(1)
        box.addLayout(name_row)

        self.introLabel = BodyLabel(_INTRO, self)
        self.introLabel.setTextColor(*SECONDARY_TEXT)
        self.introLabel.setWordWrap(True)
        box.addWidget(self.introLabel)

        status_row = QHBoxLayout()
        status_row.setSpacing(16)
        self.cookieLabel = CaptionLabel("", self)
        self.queueLabel = CaptionLabel("", self)
        self.queueLabel.setTextColor(*SECONDARY_TEXT)
        status_row.addWidget(self.cookieLabel)
        status_row.addWidget(self.queueLabel)
        status_row.addStretch(1)
        box.addLayout(status_row)

        # 路径可能很长：不换行的话最小宽度就是整串路径，整页缩不到 820px
        self.dirLabel = CaptionLabel("", self)
        self.dirLabel.setTextColor(*SECONDARY_TEXT)
        self.dirLabel.setWordWrap(True)
        box.addWidget(self.dirLabel)
        layout.addLayout(box, 1)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(8)
        self.primaryBtn = PrimaryPushButton("开始使用", self)
        self.openDirBtn = TransparentPushButton(FluentIcon.FOLDER, "打开下载文件夹", self)
        side.addWidget(self.primaryBtn)
        side.addWidget(self.openDirBtn)
        side.addStretch(1)
        layout.addLayout(side, 0)

        self.primaryBtn.clicked.connect(self._on_primary)
        self.openDirBtn.clicked.connect(self._on_open_dir)
        signal_bus.configChanged.connect(self.refresh)
        download_queue.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        has_cookie = bool(cfg.cookie.value.strip())
        self.cookieLabel.setText(
            "● Cookie 已配置" if has_cookie else "● 未配置 Cookie"
        )
        # 未配置是需要注意的状态，用品牌橙（两个主题下都可读）
        self.cookieLabel.setTextColor(*(SECONDARY_TEXT if has_cookie else ORANGE_TEXT))
        self.queueLabel.setText(f"队列 {len(download_queue)} 项")
        self.dirLabel.setText(f"下载目录: {cfg.download_dir.value}")
        self.primaryBtn.setText("开始使用" if has_cookie else "填写 Cookie")

    def _on_primary(self) -> None:
        self.navigate.emit(
            NAV_EMOJI if cfg.cookie.value.strip() else NAV_SETTING
        )

    def _on_open_dir(self) -> None:
        path = Path(cfg.download_dir.value)
        path.mkdir(parents=True, exist_ok=True)
        open_in_explorer(path, self.window())


class _QuickStartCard(SectionCard):
    """快速上手三步，每步右侧一个跳转按钮。"""

    navigate = Signal(str)

    _STEPS = (
        ("1", "填写 Cookie", "全部表情包与收藏集下载需要登录，Cookie 只存在本机", "去设置", NAV_SETTING),
        ("2", "查询 / 搜索", "按 ID 查表情包，或用关键词搜收藏集，点卡片看详情", "去查询", NAV_EMOJI),
        ("3", "批量下载", "勾选「多选」加入队列，在下载页一键下载全部", "去下载", NAV_DOWNLOAD),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("快速上手", parent)
        # HeaderCardWidget.viewLayout 是 QHBoxLayout，多行内容先包一个容器
        holder = QWidget(self.view)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        for number, title, desc, action, route in self._STEPS:
            box.addWidget(self._build_step(number, title, desc, action, route, holder))
        self.add_widget(holder)

    def _build_step(
        self, number: str, title: str, desc: str, action: str, route: str, parent
    ) -> QWidget:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        index = StrongBodyLabel(number, row)
        index.setFixedWidth(16)
        index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(index, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        name = StrongBodyLabel(title, row)
        name.setWordWrap(True)
        hint = CaptionLabel(desc, row)
        hint.setTextColor(*SECONDARY_TEXT)
        hint.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(hint)
        layout.addLayout(text, 1)

        button = TransparentPushButton(action, row)
        button.clicked.connect(lambda _=False, r=route: self.navigate.emit(r))
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return row


class _AboutCard(SectionCard):
    """关于：版本 / 依赖 / 链接 / 配置目录 / 免责声明。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("关于", parent)
        holder = QWidget(self.view)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)

        # 应用名 + 版本胶囊（与英雄卡 / 设置页身份行同一套组件）
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)
        self.nameLabel = StrongBodyLabel("BiliEmojiDD", holder)
        self.versionLabel = version_badge(APP_VERSION, holder)
        name_row.addWidget(self.nameLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addStretch(1)
        box.addLayout(name_row)

        self.stackLabel = CaptionLabel(f"biliemoji {_sdk_version()} 提供接口能力", holder)
        self.stackLabel.setTextColor(*SECONDARY_TEXT)
        self.stackLabel.setWordWrap(True)
        box.addWidget(self.stackLabel)

        # 依赖徽标：PySide6（Qt for Python）+ QFluentWidgets，图在 static/
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 2, 0, 2)
        logo_row.setSpacing(12)
        self.stackLogos: list[ImageLabel] = []
        for path, tip in (
            (PYSIDE_LOGO_PATH, "PySide6 (Qt for Python)"),
            (QFLUENT_LOGO_PATH, "PyQt-Fluent-Widgets"),
        ):
            source = QImage(str(path)) if path.is_file() else QImage()
            if source.isNull():
                continue
            logo = ImageLabel(holder)
            # 按原图比例定宽，再预缩放到 size*dpr（见 _fit_image）
            width = max(1, round(_DEP_LOGO_H * source.width() / source.height()))
            _fit_image(logo, source, width, _DEP_LOGO_H)
            logo.setToolTip(tip)
            logo_row.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
            self.stackLogos.append(logo)
        logo_row.addStretch(1)
        box.addLayout(logo_row)

        self.configLabel = CaptionLabel(f"配置目录: {APP_CONFIG_DIR}", holder)
        self.configLabel.setTextColor(*SECONDARY_TEXT)
        self.configLabel.setWordWrap(True)
        box.addWidget(self.configLabel)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.linkBtn = HyperlinkButton(_PROJECT_URL, "biliemoji SDK", holder, FluentIcon.LINK)
        self.configBtn = TransparentPushButton(FluentIcon.FOLDER, "打开配置目录", holder)
        self.configBtn.clicked.connect(self._on_open_config)
        row.addWidget(self.linkBtn)
        row.addWidget(self.configBtn)
        row.addStretch(1)
        box.addLayout(row)

        self.disclaimerLabel = CaptionLabel(_DISCLAIMER, holder)
        self.disclaimerLabel.setTextColor(*SECONDARY_TEXT)
        self.disclaimerLabel.setWordWrap(True)
        box.addWidget(self.disclaimerLabel)
        box.addStretch(1)
        self.add_widget(holder)

    def _on_open_config(self) -> None:
        APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        open_in_explorer(APP_CONFIG_DIR, self.window())


class _QueuePreviewStrip(QWidget):
    """下载卡里的队列预览：实时显示队列前几项的封面。

    走和卡片网格同一套异步缩略图（`thumb_manager` + `signal_bus.thumbLoaded`，
    命中内存/磁盘缓存时同步返回），封面未到位前留一个占位色块。
    """

    _MAX = 4  # 最多显示几项（不足就少显示几个）

    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._urls: list[str] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_STRIP_SPACING)
        # 同 _ShowcaseStrip：不让定尺寸封面把功能卡的最小宽度顶起来
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(0)
        self._labels: list[ImageLabel] = []
        for _ in range(self._MAX):
            label = ImageLabel(self)
            label.setBorderRadius(6, 6, 6, 6)
            label.setFixedSize(size, size)
            label.hide()
            layout.addWidget(label)
            self._labels.append(label)
        self._moreLabel = CaptionLabel("", self)
        self._moreLabel.setTextColor(*SECONDARY_TEXT)
        layout.addWidget(self._moreLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        self.setFixedHeight(size)

        signal_bus.thumbLoaded.connect(self._on_thumb)

    def visible_count(self) -> int:
        return sum(1 for lbl in self._labels if not lbl.isHidden())

    def refresh(self, items: list) -> None:
        """按当前队列重建预览。items 为队列副本（按加入顺序）。"""
        shown = items[: self._MAX]
        self._urls = [item_cover_url(it) or "" for it in shown]
        for index, label in enumerate(self._labels):
            if index >= len(shown):
                label.hide()
                continue
            label.setImage(QImage())  # 清掉上一项的图，避免错位残留
            label.setFixedSize(self._size, self._size)
            label.setToolTip(_item_name(shown[index]))
            label.show()
        rest = len(items) - len(shown)
        self._moreLabel.setText(f"+{rest}" if rest > 0 else "")
        self.setVisible(bool(shown))
        for url in self._urls:
            if url:
                # 先连后请求：命中 QPixmapCache 时 thumb_manager 是同步 emit
                thumb_manager.request(url)

    def _on_thumb(self, url: str, pixmap) -> None:
        for index, own in enumerate(self._urls):
            if own == url and index < len(self._labels):
                label = self._labels[index]
                square = _cover_square(pixmap, self._size, label.devicePixelRatioF())
                _fit_image(label, square, self._size, self._size)


def _item_name(item) -> str:
    """队列项显示名（表情包 text / 收藏集 name）。"""
    return getattr(item, "text", None) or getattr(item, "name", None) or "未命名"


class _FlowHolder(QWidget):
    """`FlowLayout` 的容器：把布局的 heightForWidth 转成控件自身的高度。

    **`FlowLayout.sizeHint()` 返回的是 `minimumSize()`——最大单项的尺寸，也就是
    「一行」的高度**，与实际换了几行无关。直接把它塞进卡片布局，卡片只会给一行的高度，
    第二行往后的胶囊全部溢出、压在下方内容上（最近搜索重叠就是这么来的）。
    `search_history.py` 的浮层面板不进任何布局、自己 `setGeometry`，所以没暴露这个问题。

    修法是走 Qt 官方那套：控件声明 `hasHeightForWidth`，size policy 打开
    `setHeightForWidth(True)`，父布局据此按当前宽度问出真实高度。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.flowLayout = FlowLayout(self, needAni=False)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setHorizontalSpacing(6)
        self.flowLayout.setVerticalSpacing(6)
        self._last_height = -1
        policy = QSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flowLayout.heightForWidth(width)

    def sizeHint(self) -> QSize:
        width = self.width() or super().sizeHint().width()
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return self.flowLayout.minimumSize()

    def refresh_geometry(self) -> None:
        """行数变了才通知父布局重算，避免 resize → updateGeometry → resize 自激。"""
        height = self.heightForWidth(self.width())
        if height == self._last_height:
            return
        self._last_height = height
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_geometry()


class _RecentSearchCard(SectionCard):
    """最近搜索：三个 namespace 的记录合并成胶囊，点击带关键词跳转。"""

    activated = Signal(str, str)  # (namespace, keyword)

    # (namespace, 图标, 提示前缀)
    _SOURCES = (
        ("dress", FluentIcon.ALBUM, "收藏集搜索"),
        ("emoji_id", FluentIcon.EMOJI_TAB_SYMBOLS, "表情包 ID"),
        ("emoji_filter", FluentIcon.SEARCH, "表情包过滤"),
    )
    _MAX_CHIPS = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("最近搜索", parent)
        self._holder = _FlowHolder(self.view)
        self._flow = self._holder.flowLayout
        self.add_widget(self._holder)
        self.reload()

    def chip_count(self) -> int:
        return self._flow.count()

    def reload(self) -> None:
        """重读历史文件重建胶囊；没有任何记录时整卡隐藏。"""
        # FlowLayout.takeAt 返回的是 widget 不是 QLayoutItem，清空一律用库自带的
        # takeAllWidgets()（内部已 deleteLater）。本卡没有常驻子控件，无需先摘出来。
        self._flow.takeAllWidgets()
        total = 0
        for namespace, icon, prefix in self._SOURCES:
            for text in SearchHistory(namespace).items():
                if total >= self._MAX_CHIPS:
                    break
                chip = PillPushButton(icon, text, self._holder)
                chip.setCheckable(False)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setToolTip(f"{prefix}: {text}")
                chip.clicked.connect(
                    lambda _=False, ns=namespace, t=text: self.activated.emit(ns, t)
                )
                self._flow.addWidget(chip)
                total += 1
        self._holder.refresh_geometry()  # 行数变了，重新向卡片报高度
        self.setVisible(total > 0)


class HomePage(QWidget):
    """主页。导航一律发信号交给 MainWindow，本页不引用主窗口。"""

    navigateRequested = Signal(str)  # NAV_EMOJI / NAV_DRESS / NAV_DOWNLOAD / NAV_SETTING
    searchRequested = Signal(str, str)  # (namespace, keyword)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._feature_cols = 0
        self._bottom_cols = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titleLabel = page_title("主页", self)
        root.addLayout(title_row(self.titleLabel))

        self.scrollArea = ScrollArea(self)
        self.scrollWidget = QWidget()
        self.scrollWidget.setObjectName("homeScrollWidget")
        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # 页面靠「自己不画背景」透出窗口底色；QScrollArea 是原生控件，不显式透明
        # 会在暗色下露出 palette 的 Base 色块。`.QWidget` 类选择器只命中 viewport /
        # scrollWidget 这类纯 QWidget，不级联到卡片。
        self.scrollArea.setStyleSheet(
            "QScrollArea{border:none;background:transparent}"
            ".QWidget{background:transparent}"
        )
        root.addWidget(self.scrollArea, 1)

        content = QVBoxLayout(self.scrollWidget)
        content.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, PAGE_BOTTOM)
        content.setSpacing(SECTION_SPACING)

        self.heroCard = _HeroCard(self.scrollWidget)
        self.heroCard.navigate.connect(self.navigateRequested.emit)
        content.addWidget(self.heroCard)

        self.featureGrid = QGridLayout()
        self.featureGrid.setContentsMargins(0, 0, 0, 0)
        self.featureGrid.setSpacing(SECTION_SPACING)
        self.featureCards = self._build_feature_cards()
        content.addLayout(self.featureGrid)

        self.bottomGrid = QGridLayout()
        self.bottomGrid.setContentsMargins(0, 0, 0, 0)
        self.bottomGrid.setSpacing(SECTION_SPACING)
        self.quickStartCard = _QuickStartCard(self.scrollWidget)
        self.quickStartCard.navigate.connect(self.navigateRequested.emit)
        self.aboutCard = _AboutCard(self.scrollWidget)
        content.addLayout(self.bottomGrid)

        self.recentCard = _RecentSearchCard(self.scrollWidget)
        self.recentCard.activated.connect(self.searchRequested.emit)
        content.addWidget(self.recentCard)
        content.addStretch(1)

        self._reflow(force=True)

    # ---- 功能入口卡 ----

    def _build_feature_cards(self) -> list[_FeatureCard]:
        self.emojiCard = _FeatureCard(
            FluentIcon.EMOJI_TAB_SYMBOLS,
            "表情包",
            "按包 ID 查询，或登录后拉取全部表情包并按关键词过滤，支持 GIF 动图。",
            self.scrollWidget,
        )
        self.emojiStrip = _ShowcaseStrip(
            "emoji", width=_EMOJI_THUMB, ratio=1.0, parent=self.emojiCard
        )
        if self.emojiStrip.has_images():
            self.emojiCard.add_content(self.emojiStrip)
        else:
            self.emojiStrip.setVisible(False)
        self.emojiCard.clicked.connect(
            lambda: self.navigateRequested.emit(NAV_EMOJI)
        )

        self.dressCard = _FeatureCard(
            FluentIcon.ALBUM,
            "收藏集",
            "关键词搜索 B 站装扮 / 收藏集，静态图片与动态视频都能直接预览。",
            self.scrollWidget,
        )
        self.dressStrip = _ShowcaseStrip(
            "collection", width=_COLL_THUMB_W, ratio=4 / 3, parent=self.dressCard
        )
        if self.dressStrip.has_images():
            self.dressCard.add_content(self.dressStrip)
        else:
            self.dressStrip.setVisible(False)
        self.dressCard.clicked.connect(
            lambda: self.navigateRequested.emit(NAV_DRESS)
        )

        self.downloadCard = _FeatureCard(
            FluentIcon.DOWNLOAD,
            "下载",
            "会话级混合队列，表情包与收藏集一起攒，攒够了一次批量下载。",
            self.scrollWidget,
        )
        queue_box = QWidget(self.downloadCard)
        queue_layout = QVBoxLayout(queue_box)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)
        self.queueCountLabel = StrongBodyLabel("", queue_box)
        self.queuePreview = _QueuePreviewStrip(_QUEUE_THUMB, queue_box)
        self.queueDirLabel = CaptionLabel("", queue_box)
        self.queueDirLabel.setTextColor(*SECONDARY_TEXT)
        self.queueDirLabel.setWordWrap(True)
        queue_layout.addWidget(self.queueCountLabel)
        queue_layout.addWidget(self.queuePreview)
        queue_layout.addWidget(self.queueDirLabel)
        self.downloadCard.add_content(queue_box)
        self.downloadCard.clicked.connect(
            lambda: self.navigateRequested.emit(NAV_DOWNLOAD)
        )

        download_queue.changed.connect(self._refresh_queue)
        signal_bus.configChanged.connect(self._refresh_queue)
        self._refresh_queue()
        return [self.emojiCard, self.dressCard, self.downloadCard]

    def _refresh_queue(self) -> None:
        self.queueCountLabel.setText(f"队列 {len(download_queue)} 项")
        self.queueDirLabel.setText(f"下载到 {cfg.download_dir.value}")
        self.queuePreview.refresh(download_queue.items())

    # ---- 响应式列数 ----

    def feature_columns(self) -> int:
        return self._feature_cols

    def bottom_columns(self) -> int:
        return self._bottom_cols

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _columns(self, available: int, min_width: int, maximum: int) -> int:
        step = min_width + SECTION_SPACING
        return max(1, min(maximum, (available + SECTION_SPACING) // step))

    def _reflow(self, *, force: bool = False) -> None:
        """按可用宽度重排卡片列数。

        列数没变直接 return——只有跨过阈值才动布局，避免拖拽窗口时反复重排
        （「在 resizeEvent 里按比例改几何」那套在视频播放器上踩过明显卡顿）。
        """
        available = max(0, self.width() - PAGE_MARGIN * 2)
        features = self._columns(available, _CARD_MIN_W, 3)
        bottom = self._columns(available, _BOTTOM_MIN_W, 2)
        if not force and features == self._feature_cols and bottom == self._bottom_cols:
            return
        self._feature_cols = features
        self._bottom_cols = bottom
        self._fill_grid(self.featureGrid, self.featureCards, features)
        self._fill_grid(
            self.bottomGrid, [self.quickStartCard, self.aboutCard], bottom
        )

    @staticmethod
    def _fill_grid(grid: QGridLayout, widgets: list[QWidget], columns: int) -> None:
        for widget in widgets:
            grid.removeWidget(widget)
        # 旧列可能比新列多，多余的列 stretch 要清掉，否则右侧留下空白列
        for column in range(max(columns, grid.columnCount())):
            grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, widget in enumerate(widgets):
            grid.addWidget(widget, index // columns, index % columns)
            widget.setVisible(True)

    # ---- 刷新时机 ----

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.heroCard.refresh()
        self._refresh_queue()
        self.recentCard.reload()  # 历史是别的页写的，每次回主页重读
