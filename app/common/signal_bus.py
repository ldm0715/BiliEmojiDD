"""全局信号总线。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    """跨组件通信信号。

    - thumbRawLoaded / thumbRawFailed：由缩略图 worker 线程发射（在常驻对象上发，
      避免 worker 持有的 QObject 被提前释放）；
    - thumbLoaded：主线程发射，携带已缓存的 QPixmap，广播给所有网格/卡片。
    - contentMetaRaw / contentMetaLoaded：下载项内容概要（图片/视频数），同样是
      worker 发原始信号、主线程写完缓存再广播；载荷 None 表示「取不到」。
    """

    thumbRawLoaded = Signal(str, object)  # url, QImage（worker 线程）
    thumbRawFailed = Signal(str)  # url（worker 线程）
    thumbLoaded = Signal(str, object)  # url, QPixmap（主线程）
    contentMetaRaw = Signal(object, object)  # item_key, ContentMeta|None（worker 线程）
    contentMetaLoaded = Signal(object, object)  # item_key, ContentMeta|None（主线程）
    configChanged = Signal()


signal_bus = SignalBus()
