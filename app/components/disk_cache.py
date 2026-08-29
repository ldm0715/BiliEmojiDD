"""通用磁盘缓存：图片字节与接口响应落盘复用，按 LRU 淘汰、总量用户可控。

分层关系（图片）：内存 `QPixmapCache` → 本模块的 `image_cache` → 网络。
在此之前只有内存那一层，且 Qt 默认上限仅 10 MB——翻几页卡片就被挤掉重下，重启后全丢。

实现取舍：
- **不写索引文件**。LRU 时间戳直接用文件 `mtime`（读命中时 `os.utime` 刷新），
  没有索引就没有「索引与实际文件不一致 / 索引损坏」这类问题，代价只是淘汰时扫一次目录。
- **落盘用 `.part` + `os.replace`**：写一半被杀不会留下半截文件被后续读到。
- **所有异常吞掉**（沿用 `app/components/cache.py` 的约定）：缓存坏掉最多多一次网络请求，
  绝不能把主流程带崩。
- 方法会被多个 worker 线程并发调用，全程 `threading.RLock` 保护（纯 Python 锁，不涉及 Qt 对象）。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

from app.common.config import APP_CONFIG_DIR, cfg

MB = 1024 * 1024
CACHE_ROOT = APP_CONFIG_DIR / "cache"

_EVICT_RATIO = 0.9  # 超限后淘汰到上限的 90%，避免每次 put 都触发扫描


def _digest(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class DiskCache:
    """一个缓存子目录。key 任意字符串（内部取 sha1 做文件名）。"""

    def __init__(
        self,
        name: str,
        *,
        limit_fn=None,
        ttl: float | None = None,
        touch_on_read: bool = True,
    ) -> None:
        self._root = CACHE_ROOT / name
        self._limit_fn = limit_fn or (lambda: cfg.cache_limit_mb.value * MB)
        self._ttl = ttl
        self._touch = touch_on_read
        self._lock = threading.RLock()
        self._bytes: int | None = None  # running total，None 表示还没扫过

    # ---- 读写 ----
    def get(self, key: str, *, ttl: float | None = None) -> bytes | None:
        """读缓存；缺失 / 过期 / 读失败一律返回 None（过期文件顺手删掉）。"""
        path = self._root / _digest(key)
        ttl = self._ttl if ttl is None else ttl
        with self._lock:
            try:
                stat = path.stat()
            except OSError:
                return None
            if ttl is not None and time.time() - stat.st_mtime > ttl:
                self._unlink(path, stat.st_size)
                return None
            try:
                data = path.read_bytes()
            except OSError:
                return None
            if self._touch:
                # mtime 即 LRU 时间戳：读命中就刷新，淘汰时才知道谁最久没用
                try:
                    os.utime(path, None)
                except OSError:
                    pass
            return data

    def put(self, key: str, data: bytes) -> None:
        """写缓存（原子落盘），超过上限则触发淘汰。"""
        if not data:
            return
        path = self._root / _digest(key)
        # 同一 key 可能被多个 worker 同时写，临时名带线程标识避免互相踩
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
        with self._lock:
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                old = path.stat().st_size if path.exists() else 0
                tmp.write_bytes(data)
                os.replace(tmp, path)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return
            if self._bytes is None:
                self._bytes = self._scan_size()
            else:
                self._bytes += len(data) - old
            if self._bytes > self._limit_fn():
                self._evict()

    # ---- 容量 ----
    def size(self) -> int:
        """当前占用字节数（扫目录，同时刷新 running total）。"""
        with self._lock:
            self._bytes = self._scan_size()
            return self._bytes

    def clear(self) -> None:
        with self._lock:
            shutil.rmtree(self._root, ignore_errors=True)
            self._bytes = 0

    # ---- 内部 ----
    def _scan_size(self) -> int:
        total = 0
        try:
            for entry in os.scandir(self._root):
                try:
                    if entry.is_file():
                        total += entry.stat().st_size
                except OSError:
                    continue
        except OSError:  # 目录还不存在
            return 0
        return total

    def _unlink(self, path: Path, size: int) -> None:
        try:
            path.unlink()
        except OSError:
            return
        if self._bytes is not None:
            self._bytes = max(0, self._bytes - size)

    def _evict(self) -> None:
        """按 mtime 升序删到上限的 90%（最久没读到的先走）。"""
        entries = []
        try:
            for entry in os.scandir(self._root):
                try:
                    if entry.is_file():
                        stat = entry.stat()
                        entries.append((stat.st_mtime, stat.st_size, entry.path))
                except OSError:
                    continue
        except OSError:
            return
        total = sum(e[1] for e in entries)
        target = int(self._limit_fn() * _EVICT_RATIO)
        entries.sort()  # 元组首项 mtime，最老在前
        for _, size, path in entries:
            if total <= target:
                break
            try:
                os.unlink(path)
            except OSError:
                continue
            total -= size
        self._bytes = total


# 图片字节：无 TTL（CDN URL 不变即内容不变），纯 LRU，占满用户设定的上限
image_cache = DiskCache("images")
# 接口响应：TTL 由调用方按接口给（api_cache.py），读不刷新 mtime 以免永不过期；
# 体积很小，单独封顶避免挤占图片配额
api_store = DiskCache(
    "api",
    limit_fn=lambda: max(8 * MB, min(64 * MB, cfg.cache_limit_mb.value * MB // 8)),
    touch_on_read=False,
)


def total_size() -> int:
    """整个缓存目录的占用（设置页展示用）。"""
    return image_cache.size() + api_store.size()


def clear_all() -> None:
    """清空全部磁盘缓存（设置页「清除缓存」）。"""
    image_cache.clear()
    api_store.clear()
