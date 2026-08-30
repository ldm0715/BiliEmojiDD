"""异步缩略图加载：独立线程池 + 按 URL 去重 + 内存/磁盘两级缓存。

线程规则：worker 线程只下载字节并构造 QImage，绝不碰 QPixmap；
QPixmap 转换与 QPixmapCache 读写全部在主线程（信号队列回来的槽内）完成。

缓存分三层：内存 `QPixmapCache`（本会话，命中即同步返回）→ 磁盘 `image_cache`
（跨会话，worker 线程读写）→ 网络。

worker 直接向常驻的 signal_bus 发射原始信号（thumbRawLoaded/thumbRawFailed），
避免任务对象持有的 QObject 在 worker 线程运行期间被释放。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool
from PySide6.QtGui import QImage, QPixmap, QPixmapCache

from app.common.config import cfg
from app.common.net import current_proxies, make_client
from app.common.signal_bus import signal_bus
from app.components.disk_cache import image_cache

# Qt 默认只给 QPixmapCache 10 MB：翻几页卡片就被挤掉、回头再看又要重下。
# 单位是 KB。
_PIXMAP_CACHE_KB = 64 * 1024


class ThumbLoadTask(QRunnable):
    """取一个图片的字节（磁盘缓存优先）并解码为 QImage，经 signal_bus 返回。"""

    def __init__(self, url: str, cookie: str, proxies: dict | None) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._url = url
        self._cookie = cookie
        self._proxies = proxies

    def run(self) -> None:
        image = None
        try:
            data = image_cache.get(self._url)
            if data is None:
                # 工厂保证显式代理 + 不读系统代理，与其余联网入口一致
                client = make_client(cookie=self._cookie, proxies=self._proxies)
                data = client.get_bytes(self._url, timeout=15)
                image_cache.put(self._url, data)
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
        QPixmapCache.setCacheLimit(_PIXMAP_CACHE_KB)
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
        # cookie / proxies 都在主线程读一次再交给 worker（worker 不碰 cfg）
        self._pool.start(
            ThumbLoadTask(url, cfg.cookie.value, current_proxies())
        )

    def _on_raw_loaded(self, url: str, image: QImage) -> None:
        """worker 线程解码完成，主线程转 QPixmap 并缓存（线程规则）。"""
        self._inflight.discard(url)
        pixmap = QPixmap.fromImage(image)
        QPixmapCache.insert(url, pixmap)
        signal_bus.thumbLoaded.emit(url, pixmap)

    def _on_raw_failed(self, url: str) -> None:
        self._inflight.discard(url)


thumb_manager = ThumbManager()
