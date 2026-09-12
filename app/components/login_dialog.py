"""扫码登录对话框：二维码 + 轮询状态机，外加一个圆形头像控件。

流程：申请二维码 → 画出来 → 每秒 tick 一次（每 2 秒真发一次 poll）→ 分四种状态处理。
二维码编码用 `segno` 算矩阵、`QPainter` 画方块——不引 Pillow，也不做 PNG 解码，
所以缩放不糊、尺寸随便调。

四条必须这么写的地方：

1. **`yesButton` 要先 `disconnect()`**。上游 `MessageBoxBase` 把它连到了 `accept()`，
   不断开的话点「刷新二维码」弹窗当场消失。改成刷新是这里唯一的用法。
2. **关窗后迟到的轮询回调要判 `_closed`**。`run_task` 起来了就取消不掉，关窗那一刻
   在飞的那次请求还会回来；不判就会去动已经析构的控件。所以 `_shutdown()` 要挂在
   **`reject` / `accept` / `closeEvent` / `hideEvent` 四个出口**上：前者是正常关闭
   （必须同步收，淡出动画让 `hide()` 晚一拍），而**父窗口关闭时 Qt 只是把子窗口隐藏
   掉、那几个回调一个都不走**（实测 `_closed` 仍为 False），少了 `hideEvent` 就会留下
   一个看不见、却还在每 2 秒轮询 B 站的定时器。
3. **轮询失败不弹 `show_bili_error`**。网络抖一下就弹一条全局 InfoBar 太吵，而且会
   盖住对话框；在对话框里换成一行重试文案，下一次 tick 自然重试。
4. **二维码配色恒为白底黑块，不跟主题**。扫码靠固定对比度，深色主题下把底调暗
   有扫不出来的风险，别"顺手"接上主题化。
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping

import segno
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    AvatarWidget,
    CaptionLabel,
    MessageBoxBase,
    PasswordLineEdit,
    SubtitleLabel,
)

from app.common.signal_bus import signal_bus
from app.common.theme import SECONDARY_TEXT
from app.components import bili_login
from app.components.task import run_task
from app.components.thumb import thumb_manager

_DIALOG_W = 360
_COOKIE_DIALOG_W = 440  # Cookie 字符串很长，输入框给宽一点
_QR_SIZE = 220
# quiet zone：码区四周留白的模块数。**不能省**——手机靠它把码区和背景分开，
# 贴边画的码经常扫不出来。
_QR_BORDER = 4

_AVATAR_SIZE = 40

_TICK_MS = 1000  # 倒计时刷新间隔
_POLL_EVERY_S = 2.0  # 真正发 poll 的间隔

# 二维码固定配色（见模块 docstring 第 4 条）
_QR_BG = QColor(255, 255, 255)
_QR_FG = QColor(0, 0, 0)

_HINT_WAITING = "请使用 B 站手机客户端扫码"
_HINT_SCANNED = "已扫码，请在手机上确认登录"
_HINT_LOADING = "正在申请二维码…"
_HINT_EXPIRED = "二维码已失效，点「刷新二维码」重来"


def qr_matrix(content: str) -> tuple[tuple[int, ...], ...]:
    """把二维码内容编成 0/1 矩阵（**含 quiet zone**）。

    单独拎出来是为了能被屏幕外脚本直接断言——不必去截控件画面。
    """
    rows = segno.make(content, error="m").matrix_iter(scale=1, border=_QR_BORDER)
    return tuple(tuple(row) for row in rows)


class _QrCodeView(QWidget):
    """二维码绘制区。

    矩阵先预渲染进一张 `QPixmap`（按 `devicePixelRatio` 放大），`paintEvent` 因此
    只剩一次 blit——不然一帧要画上千个小方块。方块边长取整到整数像素，
    避免边缘发虚。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_QR_SIZE, _QR_SIZE)
        self._pixmap = QPixmap()

    def set_matrix(self, rows: Iterable[Iterable[int]]) -> None:
        self._pixmap = self._render(tuple(tuple(row) for row in rows))
        self.update()

    def clear(self) -> None:
        self._pixmap = QPixmap()
        self.update()

    def _render(self, rows: tuple[tuple[int, ...], ...]) -> QPixmap:
        dpr = self.devicePixelRatioF()
        width = max(1, round(self.width() * dpr))
        height = max(1, round(self.height() * dpr))
        pixmap = QPixmap(width, height)
        pixmap.fill(_QR_BG)
        if not rows or not rows[0]:
            return pixmap

        cols = len(rows[0])
        edge = min(width // cols, height // len(rows))
        if edge < 1:
            return pixmap

        painter = QPainter(pixmap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_QR_FG))
        x0 = (width - edge * cols) // 2
        y0 = (height - edge * len(rows)) // 2
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if value:
                    painter.drawRect(x0 + c * edge, y0 + r * edge, edge, edge)
        painter.end()
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._pixmap.isNull():
            painter.fillRect(self.rect(), _QR_BG)
            return
        painter.drawPixmap(0, 0, self._pixmap)


class AccountAvatar(AvatarWidget):
    """账号头像：组件库 `AvatarWidget`（圆形裁剪 + 中心裁切）+ 「没图就整个藏起来」。

    未登录时**不显示占位** —— 没有账号就没有头像位，卡片上只剩「未登录」和扫码按钮。
    「有 Cookie 但还没拿到头像 URL」的中间态同理（等 `nav` 回来才显形）。

    **不覆写 `__init__`**：`ImageLabel.__init__` 是库自实现的 `singledispatchmethod`，
    子类加必填位置参数会在它内部第二次调用时 `TypeError`。初始化走 `_postInit()`。
    """

    SIZE = _AVATAR_SIZE

    def _postInit(self) -> None:
        self.setRadius(self.SIZE // 2)
        self._url = ""
        self.setVisible(False)
        # 先 connect 再 set_url：命中 QPixmapCache 时 request() 是同步 emit
        signal_bus.thumbLoaded.connect(self._on_thumb)

    def set_url(self, url: str) -> None:
        """换头像；空串表示未登录，整个藏起来。"""
        url = (url or "").strip()
        if url == self._url:
            return
        self._url = url
        # 先清掉上一张：换账号时旧头像不该在新图到位前继续挂着
        self._adopt(QImage())
        self.setVisible(bool(url))
        if url:
            thumb_manager.request(url)

    def has_url(self) -> bool:
        """当前是「有头像要显示」还是隐藏态（断言脚本用）。"""
        return bool(self._url)

    def _adopt(self, image) -> None:
        """喂图，并**把控件尺寸钉回去**。

        上游 `ImageLabel.setImage` 无条件 `setFixedSize(self.image.size())`
        （`label.py:300`），而 `AvatarWidget` 的整套绘制都建立在
        「控件边长 = 2*radius」上。不钉回去，一张 500x320 的头像会把控件撑成
        500x320 —— 圆形裁剪与等比缩放全部失效，头像变成一块长方形的原图。
        """
        self.setImage(image)
        self.setFixedSize(self.SIZE, self.SIZE)

    def _on_thumb(self, url: str, pixmap) -> None:
        if self._url and url == self._url and pixmap is not None:
            self._adopt(pixmap.toImage())


class LoginDialog(MessageBoxBase):
    """扫码登录对话框。

    `on_success(cookie)` 在扫码确认后、关窗**之前**调用，由调用方负责落盘与刷界面。
    `proxies` 由调用方在主线程读好 `current_proxies()` 再传进来（worker 不碰 `cfg`）。

    **`parent` 是必填的顶层窗口**：上游 `MaskDialogBase.__init__` 直接读
    `parent.width()` 来铺遮罩，传 `None` 会在构造里 `AttributeError`。设成必填位置
    参数是为了让这种误用在 Python 层就报错，而不是崩在库内部。
    """

    def __init__(
        self,
        parent: QWidget,
        *,
        on_success: Callable[[str], None] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._on_success = on_success
        self._proxies = proxies
        self._key = ""
        self._closed = False
        self._polling = False
        self._started_at = time.monotonic()
        self._last_poll = 0.0

        self.titleLabel = SubtitleLabel("扫码登录 B 站", self)
        self.qrView = _QrCodeView(self)
        self.hintLabel = CaptionLabel(_HINT_LOADING, self)
        self.hintLabel.setTextColor(*SECONDARY_TEXT)
        self.hintLabel.setWordWrap(True)
        # 居中交给 label 自己：给布局项加对齐标志会让它只拿 sizeHint 宽度，
        # 换行文案会被挤成细长一条（开屏面板踩过）
        self.hintLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 二维码固定尺寸，居中靠子项自己的对齐标志
        self.viewLayout.addWidget(
            self.titleLabel, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.viewLayout.addSpacing(4)
        self.viewLayout.addWidget(self.qrView, 0, Qt.AlignmentFlag.AlignHCenter)
        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(self.hintLabel)

        self.cancelButton.setText("关闭")
        self.yesButton.setText("刷新二维码")
        # 上游已把 yesButton 连到 accept()，不断开就是「一点就关窗」
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._start)

        self.widget.setMinimumWidth(_DIALOG_W)

        self._hint = _HINT_LOADING
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._start()

    # ---- 流程 ----

    def _start(self) -> None:
        """申请（或重新申请）一个二维码。"""
        if self._closed:
            return
        self._timer.stop()
        self._key = ""
        self._polling = False
        self._last_poll = 0.0
        self._started_at = time.monotonic()
        self.qrView.clear()
        self._set_hint(_HINT_LOADING)
        run_task(
            lambda: bili_login.generate_qrcode(proxies=self._proxies),
            on_success=self._on_qr_ready,
            on_error=self._on_qr_failed,
        )

    def _on_qr_ready(self, qr) -> None:
        if self._closed:
            return
        try:
            matrix = qr_matrix(qr.url)
        except segno.DataOverflowError as exc:  # 内容长到编不下（正常不会）
            self._set_hint(f"二维码生成失败：{exc}")
            return
        self._key = qr.key
        self._started_at = time.monotonic()
        self._last_poll = 0.0  # 立刻 poll 一次，不用等满一个间隔
        self.qrView.set_matrix(matrix)
        self._set_hint(_HINT_WAITING)
        self._timer.start()
        self._tick()

    def _on_qr_failed(self, error) -> None:
        if self._closed:
            return
        self._timer.stop()
        self._set_hint(f"申请二维码失败：{error}")

    def _tick(self) -> None:
        if self._closed or not self._key:
            return
        now = time.monotonic()
        remaining = bili_login.QRCODE_TTL_SECONDS - (now - self._started_at)
        if remaining <= 0:
            self._expire()
            return
        self._refresh_hint(remaining)
        # 上一次还没回来就别再排一个：网络慢时任务会堆起来
        if self._polling or now - self._last_poll < _POLL_EVERY_S:
            return
        self._last_poll = now
        self._polling = True
        key = self._key
        run_task(
            lambda: bili_login.poll_qrcode(key, proxies=self._proxies),
            on_success=self._on_poll,
            on_error=self._on_poll_failed,
            on_finished=self._on_poll_finished,
        )

    def _on_poll(self, result) -> None:
        if self._closed:
            return
        state, cookie = result
        if state is bili_login.LoginState.CONFIRMED:
            self._finish(cookie)
        elif state is bili_login.LoginState.EXPIRED:
            self._expire()
        elif state is bili_login.LoginState.SCANNED:
            self._set_hint(_HINT_SCANNED)
        # WAITING：保持原文案，只有倒计时在动

    def _on_poll_failed(self, _error) -> None:
        if self._closed:
            return
        # 不弹全局提示：抖一下就弹太吵，而且会盖住对话框。下一个 tick 自然重试。
        self._set_hint("网络不稳，正在重试…")

    def _on_poll_finished(self, _ok: bool) -> None:
        self._polling = False

    def _finish(self, cookie: str) -> None:
        self._timer.stop()
        if self._on_success is not None:
            self._on_success(cookie)
        self.accept()

    def _expire(self) -> None:
        self._timer.stop()
        self.qrView.clear()
        self._set_hint(_HINT_EXPIRED)

    # ---- 文案 ----

    def hint_text(self) -> str:
        """当前提示文案（不含倒计时后缀）。断言脚本用。"""
        return self._hint

    def _set_hint(self, text: str) -> None:
        self._hint = text
        self._refresh_hint()

    def _refresh_hint(self, remaining: float | None = None) -> None:
        suffix = ""
        if self._timer.isActive():
            if remaining is None:
                remaining = bili_login.QRCODE_TTL_SECONDS - (
                    time.monotonic() - self._started_at
                )
            suffix = f"（{max(0, int(remaining))} 秒后失效）"
        self.hintLabel.setText(self._hint + suffix)

    # ---- 关闭 ----

    def _shutdown(self) -> None:
        self._closed = True
        self._timer.stop()

    # 四个出口，全都要挂（`_shutdown()` 幂等，重复调用无害）：
    # - reject / accept：正常关闭。必须在这里同步收摊——上游 `done()` 给整个 dialog
    #   挂了淡出动画，`hide()` 是动画之后才发生的，等 `hideEvent` 会晚一拍。
    # - closeEvent：`close()` 这条路。
    # - hideEvent：**父窗口关闭时 Qt 只是把子窗口隐藏掉，既不发 `closeEvent` 也不走
    #   `accept`/`reject`**（实测 `_closed` 仍为 False）。少了这一个就会留下一个
    #   看不见、却还在每 2 秒轮询 B 站的定时器。

    def reject(self) -> None:
        self._shutdown()
        super().reject()

    def accept(self) -> None:
        self._shutdown()
        super().accept()

    def closeEvent(self, event) -> None:
        self._shutdown()
        super().closeEvent(event)

    def hideEvent(self, event) -> None:
        self._shutdown()
        super().hideEvent(event)


def show_login_dialog(
    parent: QWidget,
    *,
    on_success: Callable[[str], None] | None = None,
    proxies: Mapping[str, str] | None = None,
) -> LoginDialog:
    """开一个扫码登录对话框（`parent` 传顶层窗口，如 `page.window()`）。

    这里统一用 `show()` 而不是 `exec()`：轮询是异步的，`exec()` 会阻塞到关窗为止，
    离屏脚本下更会直接把脚本挂住（与更新弹窗同一处理）。
    """
    dialog = LoginDialog(parent, on_success=on_success, proxies=proxies)
    dialog.show()
    return dialog


class CookieDialog(MessageBoxBase):
    """手动填写 Cookie 的小对话框 —— 扫码那条路的退路。

    做得尽量短：一行「去哪儿复制」的提示 + 一个输入框。校验只看非空——
    组件库的 `LineEdit` **没有 `setError`**，做不了红框错误态，所以空输入直接用
    「保存」禁用表达，比弹提示更少打扰。

    `parent` 同 `LoginDialog`：必须是顶层窗口（`MaskDialogBase` 读 `parent.width()`）。
    """

    def __init__(
        self,
        parent: QWidget,
        *,
        cookie: str = "",
        on_save: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._on_save = on_save

        self.titleLabel = SubtitleLabel("手动填写 Cookie", self)
        self.hintLabel = CaptionLabel(
            "浏览器登录 bilibili.com → 按 F12 → Network → "
            "任意请求的请求头里复制 Cookie 字段。",
            self,
        )
        self.hintLabel.setTextColor(*SECONDARY_TEXT)
        self.hintLabel.setWordWrap(True)

        self.cookieEdit = PasswordLineEdit(self)
        self.cookieEdit.setPlaceholderText("SESSDATA=...; bili_jct=...")
        self.cookieEdit.setText(cookie)
        self.cookieEdit.textChanged.connect(self._sync_save_enabled)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.hintLabel)
        self.viewLayout.addSpacing(4)
        self.viewLayout.addWidget(self.cookieEdit)

        self.cancelButton.setText("取消")
        self.yesButton.setText("保存")
        # 上游已把 yesButton 连到 accept()，不断开就是「空内容也能存进去并关窗」
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._on_yes)
        self.yesButton.setEnabled(bool(cookie.strip()))

        self.widget.setMinimumWidth(_COOKIE_DIALOG_W)

    def _sync_save_enabled(self, text: str) -> None:
        self.yesButton.setEnabled(bool(text.strip()))

    def _on_yes(self) -> None:
        text = self.cookieEdit.text().strip().strip('"\'')
        if not text:  # 按钮本来就是禁用的，这里只是兜底
            return
        if self._on_save is not None:
            self._on_save(text)
        self.accept()


def show_cookie_dialog(
    parent: QWidget,
    *,
    cookie: str = "",
    on_save: Callable[[str], None] | None = None,
) -> CookieDialog:
    """开一个手动填写 Cookie 的对话框（`parent` 传顶层窗口，如 `page.window()`）。"""
    dialog = CookieDialog(parent, cookie=cookie, on_save=on_save)
    dialog.show()
    return dialog
