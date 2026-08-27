"""会话级下载队列：内存存储，按表情包 ID 去重，重启后清空。"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal


class DownloadQueue(QObject):
    """按包 ID 去重的内存下载队列。

    存 EmotePackage 对象（来自 all_packages 的只有元信息、来自详情的含完整 emote）；
    下载时会重新拉取全量，因此不依赖 emote 是否完整。
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._packages: list = []
        self._by_id: dict[int, object] = {}

    def add(self, pkg) -> bool:
        """加入一个包；已存在（同 ID）返回 False 不重复加入。"""
        if pkg.id in self._by_id:
            return False
        self._packages.append(pkg)
        self._by_id[pkg.id] = pkg
        self.changed.emit()
        return True

    def add_many(self, packages: Iterable) -> int:
        """批量加入；返回实际新增数量。"""
        added = 0
        for pkg in packages:
            if pkg.id in self._by_id:
                continue
            self._packages.append(pkg)
            self._by_id[pkg.id] = pkg
            added += 1
        if added:
            self.changed.emit()
        return added

    def remove(self, ids: Iterable[int]) -> int:
        """按 ID 移除；返回移除数量。"""
        removed = 0
        for pid in set(ids):
            if pid in self._by_id:
                self._by_id.pop(pid, None)
                self._packages = [p for p in self._packages if p.id != pid]
                removed += 1
        if removed:
            self.changed.emit()
        return removed

    def clear(self) -> None:
        if not self._packages:
            return
        self._packages.clear()
        self._by_id.clear()
        self.changed.emit()

    def packages(self) -> list:
        """当前队列副本（按加入顺序）。"""
        return list(self._packages)

    def contains(self, package_id: int) -> bool:
        return package_id in self._by_id

    def __len__(self) -> int:
        return len(self._packages)


download_queue = DownloadQueue()
