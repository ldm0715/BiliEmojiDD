"""收藏集详情页的内嵌视频播放器：组件库 VideoWidget + 缓冲状态覆盖层。

播放的永远是**本地文件**（`video_cache` 先把视频下到会话临时目录），不直接播远程 URL——
原因见 `app/components/video_cache.py` 的模块注释（代理与 UA）。

上游坑（勿"修回去"）：`qfluentwidgets.multimedia.VideoWidget` 内部的
`GraphicsVideoItem.paint` 用 `QPainter.CompositionMode_Difference` 画每一帧，
只有背景是纯黑时 `|src - 0| == src` 才是恒等变换。而库里的 QSS 给
`QGraphicsView` 设的是 `background: transparent`、`backgroundBrush` 是 `NoBrush`
（两个主题都实测过）—— 亮色主题下卡片近白底会让整段视频反色。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QDialog, QGraphicsView, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IndeterminateProgressRing,
    RoundMenu,
    TransparentToolButton,
)

# MaskDialogBase 未从 qfluentwidgets 顶层导出，按项目既有做法从子模块直接导入
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase
from qfluentwidgets.multimedia import MediaPlayBarButton, VideoWidget

from app.common.signal_bus import signal_bus
from app.components.video_cache import video_cache

_SPINNER_SIZE = 40
_PORTRAIT_RATIO = 3 / 4  # 收藏集动态卡是竖版；元数据还没到位时按它估画面宽度
_BAR_ROW_H = 108  # 控制条一行占的高度（playBar 固定 102 + 布局间距 6）
# 画面区参与布局协商时报的尺寸：一个中性的小常量。真实高度由外层布局的 stretch 决定，
# 让 QGraphicsView 自己报尺寸只会把单调增长的场景矩形捅进布局（见 _VideoView 注释）。
_VIEW_HINT = QSize(240, 180)
_VIEW_MIN = QSize(80, 60)


class _VideoView(VideoWidget):
    """三处改造，都是为了让画面区老老实实待在外层布局给的格子里。

    1. 场景背景钉成纯黑，抵消上游的 `CompositionMode_Difference`（见模块注释）；
    2. 覆写 `resizeEvent` / `enterEvent` / `leaveEvent`：上游把 `playBar` 绝对定位在
       画面底部、并按 hover 淡入淡出——控制条盖在画面上会挡住内容。这里不再摆它、
       也不再淡出，由外层布局把它排在画面下方常显。
    3. **不参与尺寸协商**：钉死场景矩形 + 覆写 `sizeHint` / `minimumSizeHint`。

    第 3 点是「视频页把窗口顶高」的根因修复，别改回去：`QGraphicsScene` 没显式设过
    sceneRect 时返回的是 `growingItemsBoundingRect`——**只涨不落**；而
    `QGraphicsView.sizeHint()` 正是 `transform.mapRect(sceneRect())`。上游
    `resizeEvent` 里 `videoItem.setSize(self.size())` 会把窗口放大时的尺寸永久写进
    那个矩形，等到播放器真的加载视频（`updateGeometry` 生效）时，这个虚高的 sizeHint
    就一路顶到 `videoPane → contentStack → previewCard → detailPage`：实测收藏集详情页
    的 sizeHint 从 663x707 涨到 853x967 且**缩窗口也回不来**。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 用 backgroundBrush（QGraphicsView 属性）而不是 setStyleSheet：VideoWidget
        # 构造里 FluentStyleSheet.MEDIA_PLAYER.apply(self) 已把自己注册进
        # styleSheetManager，每次切主题都会 updateStyleSheet 把自定义样式表冲掉
        self.setBackgroundBrush(QColor(0, 0, 0))
        self._pin_scene_rect()

    def _pin_scene_rect(self) -> None:
        """把场景矩形钉成当前视口大小，切断 growingItemsBoundingRect 的单调增长。"""
        self.graphicsScene.setSceneRect(QRectF(QPointF(0, 0), QSizeF(self.size())))

    def sizeHint(self) -> QSize:
        return _VIEW_HINT

    def minimumSizeHint(self) -> QSize:
        return _VIEW_MIN

    def resizeEvent(self, e) -> None:
        # 跳过 VideoWidget.resizeEvent（它会把 playBar 摆到画面底部并改其尺寸），
        # 只保留画面本身的自适应，所以直接调祖父类的实现
        QGraphicsView.resizeEvent(self, e)
        self.videoItem.setSize(QSizeF(self.size()))
        self._pin_scene_rect()
        self.fitInView(self.videoItem, Qt.AspectRatioMode.KeepAspectRatio)

    def enterEvent(self, e) -> None:
        QGraphicsView.enterEvent(self, e)  # 上游会 fadeIn 控制条，这里常显不需要

    def leaveEvent(self, e) -> None:
        QGraphicsView.leaveEvent(self, e)  # 上游会起定时器 fadeOut 控制条


class _HintLabel(BodyLabel):
    """覆盖层提示文字：失败态时整条可点（用来重试）。

    **不覆写 `__init__`**：`FluentLabelBase.__init__` 是 `singledispatchmethod`，
    `(text, parent)` 那个重载内部会再调一次 `self.__init__(parent)`，
    子类改签名直接 TypeError（同 `PushButton` / `InfoBadge` 的坑）。
    """

    clicked = Signal()

    def mousePressEvent(self, e) -> None:
        super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class CollectionVideoPlayer(QWidget):
    """按下标播放一组视频，自带「缓冲中 / 加载失败」覆盖层。

    items 为 `[(name, url), ...]`；`currentChanged(index)` 供缩略图选择条同步高亮。
    """

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self._index = -1
        self._pending_url: str | None = None
        self._lightbox = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.view = _VideoView(self)
        layout.addWidget(self.view, 1)
        # 控制条从画面里挪出来单独占一行：上游把它绝对定位在画面底部，
        # 竖屏视频下正好压在内容上。addWidget 会顺手重设父子关系。
        self.playBar = self.view.playBar
        layout.addWidget(self.playBar)
        self._rebuild_play_bar()

        # 覆盖层：加载环与提示文字都盖在画面上，不参与布局（resizeEvent 里居中）
        self.spinner = IndeterminateProgressRing(self, start=False)
        self.spinner.setFixedSize(_SPINNER_SIZE, _SPINNER_SIZE)
        self.spinner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.spinner.hide()
        self.hintLabel = _HintLabel("", self)
        self.hintLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # 画面是黑底，提示文字固定用白色（不随主题变，否则亮色下白底黑字看不见）
        self.hintLabel.setStyleSheet("color: white; background: transparent;")
        self.hintLabel.hide()
        # 失败态时这条提示放开鼠标事件，整条可点重试（右键菜单是隐藏功能，靠不住）
        self.hintLabel.clicked.connect(self.reload_current)

        signal_bus.videoReady.connect(self._on_video_ready)
        # 播放/暂停按钮跟着真实播放状态走。上游只在 mediaStatusChanged 时刷图标，
        # 于是「被 hideEvent 暂停」（切页、全屏搬家）之后按钮还停在暂停图标上
        self.view.player.playbackStateChanged.connect(self._sync_play_button)

    # ---- 控制条改造 ----

    def _rebuild_play_bar(self) -> None:
        """把上游的「后退 10 秒 / 前进 30 秒」改成「上一个 / 下一个视频」，并补全屏按钮。

        收藏集动态卡都是几秒的循环短片，±10s/30s 毫无意义；播放列表里前后切换才是
        真需求。上游在 `StandardMediaPlayBar.__initWidgets` 里已经把 skip 接到了
        `skipBack/skipForward`，必须先 `disconnect()` 再接自己的槽。
        """
        bar = self.playBar
        self.prevBtn, self.nextBtn = bar.skipBackButton, bar.skipForwardButton
        for button, icon, tip, slot in (
            (self.prevBtn, FluentIcon.CARE_LEFT_SOLID, "上一个", self.play_prev),
            (self.nextBtn, FluentIcon.CARE_RIGHT_SOLID, "下一个", self.play_next),
        ):
            try:
                button.clicked.disconnect()
            except (RuntimeError, TypeError):  # 没连过就算了
                pass
            button.setIcon(icon)
            button.setToolTip(tip)
            button.clicked.connect(slot)

        self.fullscreenBtn = MediaPlayBarButton(FluentIcon.FULL_SCREEN, bar)
        self.fullscreenBtn.setToolTip("全屏播放")
        self.fullscreenBtn.clicked.connect(self.toggle_fullscreen)
        # StandardMediaPlayBar 的右侧容器本来是空的，正好放全屏按钮
        bar.rightButtonLayout.addWidget(self.fullscreenBtn)
        self._sync_nav_buttons()

    def _sync_play_button(self, *_) -> None:
        self.playBar.playButton.setPlay(self.view.player.isPlaying())

    def _sync_nav_buttons(self) -> None:
        """首尾禁用，省得点了没反应；空列表时连全屏一起禁掉。"""
        last = len(self._items) - 1
        self.prevBtn.setEnabled(self._index > 0)
        self.nextBtn.setEnabled(0 <= self._index < last)
        self.fullscreenBtn.setEnabled(bool(self._items))

    # ---- 画面比例 ----

    def aspect_ratio(self) -> float:
        """画面宽高比：元数据到位就用真实值，否则按竖版 3:4 估。

        只有全屏遮罩在**打开的那一刻**用它算容器尺寸。内嵌态的宽度完全交给布局的
        stretch，**不要**再改回「在 resizeEvent 里按比例 setMaximumWidth」——
        那会在拖拽窗口时每帧触发多轮「改宽 → 重新布局 → 又一次 resize →
        fitInView + 整条选择条 setGridSize 重排」，实测表现为画面畸形 + 明显卡顿。
        """
        native = self.view.videoItem.nativeSize()
        if native.isValid() and native.height() > 0:
            return native.width() / native.height()
        return _PORTRAIT_RATIO

    # ---- 数据 ----

    def set_videos(self, items) -> None:
        """换一组视频（不自动播放，由页面在切到视频页时调 play）。"""
        self.release()
        self._items = [(name, url) for name, url in items if url]
        self._index = -1
        self._sync_nav_buttons()

    def count(self) -> int:
        return len(self._items)

    def current_index(self) -> int:
        return self._index

    def is_idle(self) -> bool:
        """既没在播也没在缓冲——`release()` 之后就是这个状态。

        页面据此判断「切回视频页要不要重新加载」：正在播时再点一次 tab 不该重头来。
        """
        return self._pending_url is None and self.view.player.source().isEmpty()

    # ---- 播放 ----

    def play(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        name, url = self._items[index]
        self._index = index
        self._sync_nav_buttons()
        self.currentChanged.emit(index)

        path = video_cache.local_path(url)
        if path is not None:
            self._pending_url = None
            self._start(path)
            return
        if video_cache.failed(url):
            self._pending_url = None
            self._show_hint("视频加载失败", retry=True)
            return
        # 未就绪：转加载环并排队下载，回来时在 _on_video_ready 里对 url 做校验
        self._pending_url = url
        self._stop_playback()
        self._show_spinner(f"正在缓冲「{name}」…" if name else "正在缓冲…")
        video_cache.request(url)

    def play_prev(self) -> None:
        """上一个视频；已经是第一个（或列表为空）就什么都不做。"""
        if self._index > 0:
            self.play(self._index - 1)

    def play_next(self) -> None:
        """下一个视频；已经是最后一个（或列表为空）就什么都不做。"""
        if 0 <= self._index < len(self._items) - 1:
            self.play(self._index + 1)

    def reload_current(self) -> None:
        """作废当前视频的缓存与失败标记后重播。

        `video_cache` 失败一次就本会话不再重试（防请求风暴），没有这个入口的话
        网络抖一下就只能一直盯着「视频加载失败」。
        """
        if not (0 <= self._index < len(self._items)):
            return
        video_cache.forget(self._items[self._index][1])
        self.play(self._index)

    def is_playing(self) -> bool:
        return self.view.player.isPlaying()

    def resume(self) -> None:
        """继续播放当前源（重新挂载父控件后用，不影响进度）。"""
        if not self.view.player.source().isEmpty():
            self.view.play()

    # ---- 全屏 ----

    def toggle_fullscreen(self) -> None:
        """进 / 出遮罩全屏。已在全屏时按钮变成「退出全屏」。"""
        if self._lightbox is not None:
            self._lightbox.reject()
            return
        if not self._items:
            return
        window = self.window()
        if window is None:
            return
        self._lightbox = VideoLightbox(self, window)
        self.fullscreenBtn.setIcon(FluentIcon.BACK_TO_WINDOW)
        self.fullscreenBtn.setToolTip("退出全屏")
        self._lightbox.exec()

    def _on_lightbox_closed(self) -> None:
        self._lightbox = None
        self.fullscreenBtn.setIcon(FluentIcon.FULL_SCREEN)
        self.fullscreenBtn.setToolTip("全屏播放")

    def _on_video_ready(self, url: str, path) -> None:
        # 必须校验：用户可能已经切到别的视频，晚到的信号不能顶掉当前画面
        if url != self._pending_url:
            return
        self._pending_url = None
        if path is None:
            self._show_hint("视频加载失败", retry=True)
            return
        self._start(path)

    def _start(self, path: str) -> None:
        self._hide_overlay()
        self.view.setVideo(QUrl.fromLocalFile(path))
        self.view.play()

    def release(self) -> None:
        """停播并释放文件句柄（Windows 上占用中的文件删不掉）。"""
        self._pending_url = None
        self._stop_playback()
        self._hide_overlay()

    def _stop_playback(self) -> None:
        player = self.view.player
        player.stop()
        player.setSource(QUrl())

    # ---- 覆盖层 ----

    def _show_spinner(self, text: str) -> None:
        self.hintLabel.setText(text)
        self._set_hint_clickable(False)  # 缓冲中点了没意义
        self.hintLabel.show()
        self.spinner.show()
        self.spinner.start()
        self._place_overlay()

    def _show_hint(self, text: str, *, retry: bool = False) -> None:
        self.spinner.stop()
        self.spinner.hide()
        self.hintLabel.setText(text + "，点击重试" if retry else text)
        self._set_hint_clickable(retry)
        self.hintLabel.show()
        self._place_overlay()

    def _set_hint_clickable(self, clickable: bool) -> None:
        self.hintLabel.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, not clickable
        )
        self.hintLabel.setCursor(
            Qt.CursorShape.PointingHandCursor
            if clickable
            else Qt.CursorShape.ArrowCursor
        )

    def _hide_overlay(self) -> None:
        self.spinner.stop()
        self.spinner.hide()
        self.hintLabel.hide()
        self._set_hint_clickable(False)  # 状态别留到下一次

    def _place_overlay(self) -> None:
        # 以画面区（不含下方控制条）为基准居中。覆盖层不进布局，所以一律用
        # setGeometry 摆位——写 setFixedWidth/Height 等于给它加尺寸约束，没必要
        rect = self.view.geometry()
        cx, cy = rect.center().x(), rect.center().y()
        spinning = not self.spinner.isHidden()
        if spinning:
            self.spinner.move(cx - _SPINNER_SIZE // 2, cy - _SPINNER_SIZE - 4)
            self.spinner.raise_()
        w = max(120, rect.width() - 32)
        # 换行 Label 的高度必须问 heightForWidth，sizeHint 不反映实际折行
        h = max(24, self.hintLabel.heightForWidth(w))
        self.hintLabel.setGeometry(
            cx - w // 2, cy + (4 if spinning else -h // 2), w, h
        )
        self.hintLabel.raise_()

    def contextMenuEvent(self, event) -> None:
        """右键 →「重新加载」：与失败态的「点击重试」同一条路径。"""
        if not (0 <= self._index < len(self._items)):
            return
        menu = RoundMenu(parent=self)
        action = QAction(FluentIcon.SYNC.icon(), "重新加载", menu)
        action.triggered.connect(self.reload_current)
        menu.addAction(action)
        menu.exec(event.globalPos())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 只有覆盖层可见时才重摆：拖拽窗口期间 resizeEvent 会连发，这里不做几何写入
        if not self.hintLabel.isHidden() or not self.spinner.isHidden():
            self._place_overlay()


class VideoLightbox(MaskDialogBase):
    """遮罩全屏播放：把**现有**播放器整个搬进来，关闭时原样搬回。

    不新建播放器：那会多一个 `QMediaPlayer` / `QAudioOutput`，声音重叠、进度还从头开始。
    搬动会触发 `VideoWidget.hideEvent` 里的 `pause()`，所以搬完按原状态 `resume()`
    （pause 不重置进度，位置不丢）。

    遮罩层的上游坑与 `image_viewer.py` 完全一致，改动前请先读 `docs/image_viewer.md`：
    `setMaskColor` 的 B/G 参数写反（用纯黑绕过）、`self.widget` 无对齐地铺满整个
    dialog（须 removeWidget 后重新居中，否则「点空白处关闭」永远判不出来）。
    """

    def __init__(self, player: CollectionVideoPlayer, parent: QWidget) -> None:
        super().__init__(parent=parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMaskColor(QColor(0, 0, 0, 200))

        self._hBoxLayout.removeWidget(self.widget)
        self._hBoxLayout.addWidget(self.widget, 1, Qt.AlignmentFlag.AlignCenter)
        self.widget.setGraphicsEffect(None)  # 透明容器上的投影只会糊在子控件周围
        self.widget.setStyleSheet("background: transparent;")

        self._player = player
        home = player.parentWidget().layout()
        self._home = home
        self._home_index = home.indexOf(player)
        self._home_stretch = home.stretch(self._home_index)
        self._was_playing = player.is_playing()

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(player)
        self._resize_content()
        if self._was_playing:
            player.resume()  # 换父控件触发了 hideEvent 里的 pause

        self.closeBtn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeBtn.setFixedSize(36, 36)
        self.closeBtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.closeBtn.clicked.connect(self.reject)
        self._place_close_button()  # 基类已 setGeometry 过，未必再触发 resizeEvent

        self.finished.connect(self._restore)

    def _resize_content(self) -> None:
        """容器尺寸先按遮罩高度定，再按画面比例反推宽度——黑边不会铺满整个遮罩。"""
        h = max(320, int(self.height() * 0.88))
        view_h = max(120, h - _BAR_ROW_H)
        w = max(240, min(int(self.width() * 0.9), round(view_h * self._player.aspect_ratio())))
        if self.widget.size() != QSize(w, h):
            self.widget.setFixedSize(w, h)

    def showEvent(self, e) -> None:
        # 跳过上游的淡入：它给整个 dialog 挂 QGraphicsOpacityEffect，而 dialog 里是
        # 一路在刷帧的 QGraphicsVideoItem —— 特效会把整棵子树走离屏合成，明显卡顿
        QDialog.showEvent(self, e)

    def done(self, code) -> None:
        # 同上，跳过上游的淡出动画。顺带在真正隐藏之前记住播放状态：
        # 隐藏会触发 VideoWidget.hideEvent 里的 pause()，等到 finished 时已经是暂停了
        self._was_playing = self._player.is_playing()
        QDialog.done(self, code)

    def _restore(self) -> None:
        """把播放器搬回原来的布局位置（下标 + stretch 都还原）。"""
        self._home.insertWidget(self._home_index, self._player, self._home_stretch)
        if self._was_playing:
            self._player.resume()
        self._player._on_lightbox_closed()

    def keyPressEvent(self, e) -> None:
        # 与图片查看器一致：方向键切上一个 / 下一个
        if e.key() == Qt.Key.Key_Left:
            self._player.play_prev()
            return
        if e.key() == Qt.Key.Key_Right:
            self._player.play_next()
            return
        super().keyPressEvent(e)  # Esc 由 QDialog 默认处理成 reject

    def mousePressEvent(self, e) -> None:
        if not self.widget.geometry().contains(e.pos()):
            self.reject()
            return
        super().mousePressEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # 遮罩尺寸由外部窗口驱动（基类的 eventFilter），容器只跟着它走，不会反向影响
        self._resize_content()
        self._place_close_button()

    def _place_close_button(self) -> None:
        self.closeBtn.move(self.width() - self.closeBtn.width() - 16, 16)
        self.closeBtn.raise_()
