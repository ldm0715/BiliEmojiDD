"""GIF 标识与动图预览的屏幕外断言。

覆盖四块：
1. `movie_from_cache` / `package_has_gif` 两个判定入口；
2. `PackageCard` 的 GIF 徽标在图片区**左下角**，且与勾选框 / 「已下载」徽标互不重叠；
3. `EmojiCard` 悬浮播放：进入起 movie、离开停 movie 并退回静态图；
4. `ImageViewer` 打开即播，翻到非动图项后旧 movie 已停。

运行：QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_gif.py
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 要写 image_cache：必须在 import app.* 之前隔离 APPDATA，别弄脏用户真实缓存
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="bilidd_gif_")

from PySide6.QtCore import QEvent, QPointF, QSize
from PySide6.QtGui import QColor, QEnterEvent, QMovie, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget

from app.components.disk_cache import image_cache
from app.components.gif import movie_from_cache, package_has_gif
from app.components.image_viewer import ImageViewer
from app.components.widgets import EmojiGrid, PackageCard

# 1x1 单帧透明 GIF：拆开后把「GCE + 图像描述符 + LZW 数据」那段再接一份，凑成两帧
_ONE_FRAME = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
_FRAME_START = _ONE_FRAME.index(b"\x21\xf9")  # 图形控制扩展的起点
_GIF_BYTES = (
    _ONE_FRAME[:-1] + _ONE_FRAME[_FRAME_START:-1] + b"\x3b"  # 去掉 trailer 再补回
)
# 1x1 PNG：用来验证「单帧图不会被当成动图」
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

GIF_URL = "https://example.invalid/anim.gif"
PNG_URL = "https://example.invalid/still.png"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok] {label}")
    else:
        failures.append(f"{label} {detail}".strip())
        print(f"  [FAIL] {label} {detail}")


def _hover_in(widget) -> None:
    """QWidget.enterEvent 只吃 QEnterEvent（不是裸 QEvent），坐标随便给。"""
    pos = QPointF(1, 1)
    widget.enterEvent(QEnterEvent(pos, pos, pos))


class FakeMeta:
    def __init__(self, label_text=None):
        self.label_text = label_text


class FakeEmote:
    def __init__(self, text, url, gif_url=None):
        self.text, self.url, self.gif_url = text, url, gif_url


class FakePackage:
    def __init__(self, pid, text, url, emote=(), label_text=None):
        self.id, self.text, self.url = pid, text, url
        self.emote = tuple(emote)
        self.meta = FakeMeta(label_text)

    @property
    def is_gif(self) -> bool:
        return bool(self.meta and self.meta.label_text)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    image_cache.put(GIF_URL, _GIF_BYTES)
    image_cache.put(PNG_URL, _PNG_BYTES)
    # 预置内存缓存，避免任何卡片真的去联网（假地址会排 15s 超时）
    for url, color in ((GIF_URL, "#c33"), (PNG_URL, "#39c")):
        pm = QPixmap(64, 64)
        pm.fill(QColor(color))
        QPixmapCache.insert(url, pm)

    print("1. 判定入口")
    probe = movie_from_cache(GIF_URL)
    check("GIF 字节 → QMovie", probe is not None)
    check(
        "多帧",
        probe is not None and probe.frameCount() > 1,
        f"frameCount={probe.frameCount() if probe else 'n/a'}",
    )
    check("PNG 字节 → None（单帧不算动图）", movie_from_cache(PNG_URL) is None)
    check("未缓存的地址 → None", movie_from_cache("https://example.invalid/x.gif") is None)
    check("空地址 → None", movie_from_cache(None) is None)

    gif_pkg = FakePackage(1, "动图包", PNG_URL, [FakeEmote("a", PNG_URL, GIF_URL)])
    flat_pkg = FakePackage(2, "静态包", PNG_URL, [FakeEmote("a", PNG_URL)])
    label_pkg = FakePackage(3, "全量列表里的动图包", PNG_URL, [], label_text="GIF")
    check("package_has_gif：有 gif_url", package_has_gif(gif_pkg))
    check("package_has_gif：纯静态", not package_has_gif(flat_pkg))
    check("package_has_gif：只有 meta.label_text（全量列表）", package_has_gif(label_pkg))

    print("2. PackageCard 徽标位置")
    host = QWidget()
    host.resize(400, 300)
    card = PackageCard(gif_pkg, host)
    card.set_selectable(True)
    card.set_cell(QSize(160, 160))
    host.show()
    app.processEvents()

    badge = card.gifBadge
    img = card.imageBtn.geometry()
    check("GIF 徽标可见", not badge.isHidden())
    b = badge.geometry()
    check(
        "在图片区左半边",
        b.center().x() < img.center().x(),
        f"badge.x={b.center().x()} img.mid={img.center().x()}",
    )
    check(
        "在图片区下半边",
        b.center().y() > img.center().y(),
        f"badge.y={b.center().y()} img.mid={img.center().y()}",
    )
    check(
        "不与勾选框重叠",
        not b.intersects(card.checkBox.geometry()),
        f"badge={b} check={card.checkBox.geometry()}",
    )
    card.downloadedBadge.setVisible(True)
    card._pin_badge()
    check(
        "不与「已下载」徽标重叠",
        not b.intersects(card.downloadedBadge.geometry()),
        f"badge={b} downloaded={card.downloadedBadge.geometry()}",
    )
    check(
        "角标够小，不横贯封面",
        b.width() < img.width() * 0.6,
        f"badge.w={b.width()} img.w={img.width()}",
    )
    check(
        "不压住封面中心（加载环就在那儿）",
        not b.contains(img.center()),
        f"badge={b} center={img.center()}",
    )
    flat_card = PackageCard(flat_pkg, host)
    check("静态包不显示 GIF 徽标", flat_card.gifBadge.isHidden())

    print("3. EmojiCard 悬浮播放")
    grid = EmojiGrid(host)
    grid.resize(360, 200)
    grid.set_emotes([("动图", GIF_URL, True), ("静图", PNG_URL, False)])
    grid.show()
    app.processEvents()
    check("items 保留第三位", grid.items()[0][2] is True and grid.items()[1][2] is False)
    gif_card = grid.itemWidget(grid.item(0))
    still_card = grid.itemWidget(grid.item(1))
    check("动图卡挂徽标", not gif_card.gifBadge.isHidden())
    check("静图卡不挂徽标", still_card.gifBadge.isHidden())
    gb = gif_card.gifBadge.geometry()
    icon = gif_card.iconLabel.geometry()
    check(
        "表情卡角标也在图标区左下",
        gb.center().x() < icon.center().x() and gb.center().y() > icon.center().y(),
        f"badge={gb} icon={icon}",
    )
    check(
        "角标够小，不横贯图标",
        gb.width() < icon.width() * 0.6,
        f"badge.w={gb.width()} icon.w={icon.width()}",
    )
    check(
        "不压住图标中心（加载环就在那儿）",
        not gb.contains(icon.center()),
        f"badge={gb} center={icon.center()}",
    )

    gif_card.set_pixmap(QPixmap(64, 64))
    _hover_in(gif_card)
    check("悬浮起 movie", gif_card._movie is not None)
    check(
        "movie 在跑",
        gif_card._movie is not None
        and gif_card._movie.state() == QMovie.MovieState.Running,
    )
    _hover_in(still_card)
    check("静图卡不起 movie", still_card._movie is None)

    # 让鼠标"确实在卡外"：leaveEvent 里有 rect().contains(mapFromGlobal(cursor)) 判据。
    # 离屏下光标停在 (0,0)，卡片被 grid 摆到非原点位置即可满足
    gif_card.move(200, 120)
    gif_card.leaveEvent(QEvent(QEvent.Type.Leave))
    check("离开停 movie", gif_card._movie is None)
    check("退回静态图", not gif_card.iconLabel.pixmap().isNull())

    # 兼容旧的两元组调用
    grid.set_emotes([("旧调用", PNG_URL)])
    check("两元组仍可用", grid.items()[0][2] is False)

    print("4. ImageViewer 自动播放")
    viewer = ImageViewer(
        [("动图", GIF_URL, True), ("静图", PNG_URL, False)], 0, host
    )
    viewer.show()
    app.processEvents()
    check("打开即播", viewer._movie is not None and viewer._movie_index == 0)
    viewer.flipView.setCurrentIndex(1)
    app.processEvents()
    check("翻到静图项后停播", viewer._movie is None)
    viewer.flipView.setCurrentIndex(0)
    app.processEvents()
    check("翻回动图项重新播", viewer._movie is not None)
    # WA_DeleteOnClose：关闭后再摸 viewer 就是野对象，所以在 finished 里当场记一笔。
    # 这个 lambda 接在 viewer 自己的 _on_finished 之后，跑的时候已经收过尾了
    closed: dict = {}
    viewer.finished.connect(lambda *_: closed.update(movie=viewer._movie))
    viewer.reject()  # Esc / 关闭按钮 / 点遮罩都走这条
    # MaskDialogBase.done 先跑一段淡出动画才 QDialog.done，finished 是延迟发的：
    # 光 processEvents() 不推进时间，得轮询等真实时间过去
    for _ in range(200):
        if closed:
            break
        app.processEvents()
        time.sleep(0.01)
    check("关闭后 movie 已释放", closed.get("movie", "missing") is None, str(closed))

    host.close()
    print()
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("check_gif.py: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
