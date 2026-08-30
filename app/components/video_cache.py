"""收藏集视频的会话级本地缓存：后台下到临时目录，播放器只播本地文件。

为什么不直接 `QMediaPlayer.setSource(远程 URL)`：`QMediaPlayer` 在 Windows 上走
Media Foundation 自己的网络栈，**读系统代理、不读应用内「设置 → 代理」**，也无法
自定义 UA。那会出现「下载能用、播放却失败且毫无线索」的割裂。改为复用 biliemoji 的
`Downloader`（显式 proxies + 重试 + `.part` 原子落盘 + mp4 魔数校验），播本地文件。

结构与 `content_meta.py` / `thumb.py` 完全一致：
- worker 线程只下载，经常驻的 `signal_bus` 发 `videoRawReady`；
- 主线程槽写缓存后再广播 `signal_bus.videoReady`（载荷 None = 取不到）；
- 失败记入 `_failed`，本会话不重试。
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from biliemoji import DownloadStatus, DownloadTask
from PySide6.QtCore import QObject, QRunnable, QThreadPool

from app.common.net import current_proxies, make_downloader
from app.common.signal_bus import signal_bus

_TEMP_PREFIX = "biliEmojiDD-video-"
_temp_dir: Path | None = None


def _cache_dir() -> Path:
    """会话临时目录，首次用到时才建（退出时由 cleanup() 整个删掉）。"""
    global _temp_dir
    if _temp_dir is None:
        _temp_dir = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
    return _temp_dir


def _cache_path(url: str) -> Path:
    """URL 指纹做文件名（同 cache.py 的 cookie 指纹写法），避免非法字符与超长名。"""
    return _cache_dir() / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".mp4")


class _VideoTask(QRunnable):
    """下载一个视频到临时目录，经 signal_bus 返回本地路径（失败发 None）。"""

    def __init__(self, url: str, target: Path, proxies) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._url = url
        self._target = target
        self._proxies = proxies

    def run(self) -> None:
        path = None
        try:
            result = make_downloader(max_workers=1, proxies=self._proxies).download(
                DownloadTask(url=self._url, target=self._target, expected_ext=".mp4")
            )
            # SKIPPED = 目标文件已存在，同样可播
            if result.status in (DownloadStatus.SUCCESS, DownloadStatus.SKIPPED):
                path = str(result.target)
        except Exception:  # noqa: BLE001 取不到就显示「加载失败」，不打扰用户
            path = None
        # 应用关闭时信号对象可能已销毁，忽略该阶段的 RuntimeError
        try:
            signal_bus.videoRawReady.emit(self._url, path)
        except RuntimeError:
            return


class VideoCacheManager(QObject):
    """视频缓存统一入口。local_path / remember / request 均须在主线程调用。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)  # 独立线程池，不占 task_manager 的 4 线程
        self._cache: dict[str, str] = {}
        self._inflight: set[str] = set()
        self._failed: set[str] = set()  # 本会话不再重试，防请求风暴
        self._enabled = True
        signal_bus.videoRawReady.connect(self._on_raw)

    def set_enabled(self, enabled: bool) -> None:
        """关掉联网下载。屏幕外断言脚本必须关，否则假 URL 会排一堆超时任务。"""
        self._enabled = bool(enabled)

    def local_path(self, url: str | None) -> str | None:
        """已就绪的本地文件路径；未就绪 / 文件被外部删掉都返回 None。"""
        if not url:
            return None
        path = self._cache.get(url)
        if path is None:
            return None
        if not Path(path).is_file():  # 外部删了就当没缓存过，允许重下
            self._cache.pop(url, None)
            return None
        return path

    def remember(self, url: str, path) -> None:
        """把已有的本地文件登记进来（如该收藏集之前已完整下载过），省掉重下。"""
        if not url:
            return
        self._cache[url] = str(path)
        self._failed.discard(url)

    def failed(self, url: str | None) -> bool:
        return bool(url) and url in self._failed

    def request(self, url: str | None) -> None:
        """后台下载一个视频；已缓存 / 在途 / 失败过则直接返回。"""
        if not self._enabled or not url:
            return
        if url in self._inflight or url in self._failed:
            return
        if self.local_path(url) is not None:
            return
        self._inflight.add(url)
        self._pool.start(_VideoTask(url, _cache_path(url), current_proxies()))

    def _on_raw(self, url: str, path) -> None:
        """worker 下载完成：主线程写缓存后广播（连接顺序保证播放器读得到）。"""
        self._inflight.discard(url)
        if path is None:
            self._failed.add(url)
        else:
            self._cache[url] = path
        signal_bus.videoReady.emit(url, path)

    def cleanup(self) -> None:
        """退出时删掉本会话的临时目录（只删自己 mkdtemp 出来的那个）。"""
        global _temp_dir
        if _temp_dir is None:
            return
        # 播放中的文件在 Windows 上可能仍被占用，删不掉就交给系统临时清理
        shutil.rmtree(_temp_dir, ignore_errors=True)
        _temp_dir = None
        self._cache.clear()


video_cache = VideoCacheManager()
