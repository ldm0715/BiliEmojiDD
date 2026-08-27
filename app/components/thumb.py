"""异步缩略图加载：独立线程池 + 按 URL 去重 + QPixmapCache 主线程缓存。

线程规则：worker 线程只下载字节并构造 QImage，绝不碰 QPixmap；
QPixmap 转换与 QPixmapCache 读写全部在主线程（信号队列回来的槽内）完成。

worker 直接向常驻的 signal_bus 发射原始信号（thumbRawLoaded/thumbRawFailed），
避免任务对象持有的 QObject 在 worker 线程运行期间被释放。
"""
from __future__ import annotations

from biliemoji import BiliClient
from PySide6.QtCore import QObject, QRunnable, QThreadPool
from PySide6.QtGui import QImage, QPixmap, QPixmapCache

from app.common.config import cfg
from app.common.signal_bus import signal_bus


class ThumbLoadTask(QRunnable):
    """下载一个图片并解码为 QImage，经 signal_bus 返回。"""

    def __init__(self, url: str, cookie: str) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._url = url
        self._cookie = cookie

    def run(self) -> None:
        image = None
        try:
            client = BiliClient(cookie=self._cookie)
            data = client.get_bytes(self._url, timeout=15)
            img = QImage()
            if img.loadFromData(data):
                image = img
        except Exception:  # noqa: BLE001 网络错误/非图片均视为失败
            image = None
        # 应用关闭时信号对象可能已被销毁，忽略该阶段的 RuntimeError
        try:
            if image is not None:
                signal_bus.thumbRawLoaded.emit(self._url, image)
            else:
                signal_bus.thumbRawFailed.emit(self._url)
        except RuntimeError:
            return


class ThumbManager(QObject):
    """缩略图请求统一入口。request() 必须在主线程调用。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(3)
        self._inflight: set[str] = set()
        signal_bus.thumbRawLoaded.connect(self._on_raw_loaded)
        signal_bus.thumbRawFailed.connect(self._on_raw_failed)

    def request(self, url: str | None) -> None:
        if not url:
            return
        cached = QPixmap()
        if QPixmapCache.find(url, cached):
            signal_bus.thumbLoaded.emit(url, cached)
            return
        if url in self._inflight:
            return
        self._inflight.add(url)
        self._pool.start(ThumbLoadTask(url, cfg.cookie.value))

    def _on_raw_loaded(self, url: str, image: QImage) -> None:
        """worker 线程解码完成，主线程转 QPixmap 并缓存（线程规则）。"""
        self._inflight.discard(url)
        pixmap = QPixmap.fromImage(image)
        QPixmapCache.insert(url, pixmap)
        signal_bus.thumbLoaded.emit(url, pixmap)

    def _on_raw_failed(self, url: str) -> None:
        self._inflight.discard(url)


thumb_manager = ThumbManager()
