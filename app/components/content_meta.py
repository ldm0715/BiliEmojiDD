"""下载项内容概要（图片 / 视频数量）：会话级内存缓存 + 后台懒加载。

队列里的项大多不带明细：`all_packages()` 只返回包元信息（`emote` 为空），
收藏集搜索只给 summary。要显示「多少图片 / 多少视频」必须再调一次详情接口，
因此本模块按缩略图（`thumb.py`）的同款结构做懒加载：

- `cached()` 能同步推导就同步推导（详情页加入的完整 `EmotePackage` 自带 emote）；
- `request()` 只在卡片可见时调用，走独立线程池（不占 `task_manager` 的 4 个线程）；
- worker 线程只发 `signal_bus.contentMetaRaw`，主线程槽写缓存后再广播
  `signal_bus.contentMetaLoaded`（载荷 None = 取不到）。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool

from app.common.signal_bus import signal_bus
from app.components import api_cache
from app.components.download_queue import item_key, item_kind
from app.components.dress_helpers import dlc_ids, is_collection


@dataclass(frozen=True)
class ContentMeta:
    """一个下载项会产出多少文件（口径与 download_runner 的建任务逻辑一致）。"""

    images: int
    videos: int

    def text(self) -> str:
        if self.images and self.videos:
            return f"{self.images} 张图片 · {self.videos} 个视频"
        if self.videos:
            return f"{self.videos} 个视频"
        return f"{self.images} 张图片"


def _package_meta(pkg) -> ContentMeta:
    """表情包：能下的表情数（gif_url 或 url 有其一）。"""
    return ContentMeta(sum(1 for em in pkg.emote if em.gif_url or em.url), 0)


def live_meta(pack) -> ContentMeta:
    """直播间表情：房间内全部专属表情（列表本身就是全量，无需联网）。"""
    return ContentMeta(len(pack.emotes), 0)


def collection_meta(coll) -> ContentMeta:
    """收藏集：有图片的项数 + 有视频的项数（视频每项只下第一个）。"""
    images = sum(1 for it in coll.item_list if it.card_img_download)
    videos = sum(1 for it in coll.item_list if it.video_list)
    return ContentMeta(images, videos)


class _MetaTask(QRunnable):
    """拉一个下载项的详情并算出内容数量，经 signal_bus 返回（失败发 None）。

    详情走 `api_cache`：与两个详情页共用同一份磁盘缓存，进过详情的项零请求。
    """

    def __init__(self, item) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._item = item
        self._key = item_key(item)

    def run(self) -> None:
        meta = None
        try:
            kind = item_kind(self._item)
            if kind == "live":
                # 直播间表情自带全量列表，cached() 已经同步推导过，走不到这里；
                # 万一走到（emotes 为空）显示「未知」即可，别掉进收藏集分支。
                meta = None
            elif kind == "package":
                meta = _package_meta(api_cache.emoji_package(self._item.id))
            else:
                act_id, lottery_id = dlc_ids(self._item)
                if is_collection(self._item) and act_id and lottery_id:
                    meta = collection_meta(
                        api_cache.dress_collection(act_id, lottery_id)
                    )
        except Exception:  # noqa: BLE001 取不到就显示「未知」，不打扰用户
            meta = None
        # 应用关闭时信号对象可能已销毁，忽略该阶段的 RuntimeError
        try:
            signal_bus.contentMetaRaw.emit(self._key, meta)
        except RuntimeError:
            return


class ContentMetaManager(QObject):
    """内容概要请求统一入口。cached/remember/request 均须在主线程调用。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._cache: dict[tuple, ContentMeta] = {}
        self._inflight: set[tuple] = set()
        self._failed: set[tuple] = set()  # 本会话不再重试，防请求风暴
        self._enabled = True
        signal_bus.contentMetaRaw.connect(self._on_raw)

    def set_enabled(self, enabled: bool) -> None:
        """关掉联网懒加载。屏幕外断言脚本必须关，否则假数据会排一堆超时请求。"""
        self._enabled = bool(enabled)

    def cached(self, item) -> ContentMeta | None:
        """已知的内容数量：缓存命中 → 能同步推导 → 否则 None（需 request）。"""
        key = item_key(item)
        meta = self._cache.get(key)
        if meta is not None:
            return meta
        kind = item_kind(item)
        # 详情页加入的 EmotePackage 自带完整 emote，零请求直接算
        if kind == "package" and getattr(item, "emote", None):
            meta = _package_meta(item)
            self._cache[key] = meta
            return meta
        # 直播间表情的 emotes 就是全量，同样零请求
        if kind == "live":
            meta = live_meta(item)
            self._cache[key] = meta
            return meta
        return None

    def remember(self, item, meta: ContentMeta) -> None:
        """详情页把已经拉到的数据喂进来（省掉队列页的重复请求）。"""
        key = item_key(item)
        self._cache[key] = meta
        self._failed.discard(key)
        signal_bus.contentMetaLoaded.emit(key, meta)

    def request(self, item) -> None:
        """懒加载一个项的内容数量；已缓存 / 在途 / 失败过则直接返回。"""
        if not self._enabled:
            return
        key = item_key(item)
        if key in self._cache or key in self._inflight or key in self._failed:
            return
        if self.cached(item) is not None:  # 同步推导得出，无需联网
            return
        self._inflight.add(key)
        self._pool.start(_MetaTask(item))

    def _on_raw(self, key, meta) -> None:
        """worker 拉取完成：主线程写缓存后广播（连接顺序保证卡片读得到）。"""
        self._inflight.discard(key)
        if meta is None:
            self._failed.add(key)
        else:
            self._cache[key] = meta
        signal_bus.contentMetaLoaded.emit(key, meta)


content_meta = ContentMetaManager()
