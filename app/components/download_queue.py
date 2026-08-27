"""会话级下载队列：内存存储，混合表情包 / 收藏集，按类型+ID 去重，重启后清空。"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal


def item_kind(item) -> str:
    """'package'（表情包）或 'collection'（收藏集）。

    EmotePackage 必有 emote 字段；DressCollectionSummary 无该字段。
    """
    return "package" if getattr(item, "emote", None) is not None else "collection"


def item_key(item) -> tuple[str, int | str]:
    """去重键。表情包 ("pkg", id)；收藏集 ("coll", raw['item_id'])。

    注意：summary.id 因 biliemoji 解析 bug 恒为 None，收藏集只能取 raw。
    """
    if item_kind(item) == "package":
        return ("pkg", item.id)
    raw = getattr(item, "raw", None) or {}
    item_id = raw.get("item_id")
    if item_id is None:  # 防御：字段位置不同版本可能有差异
        item_id = (raw.get("properties") or {}).get("item_id")
    if item_id is None:
        item_id = raw.get("id") or getattr(item, "name", None) or ""
    return ("coll", item_id)


class DownloadQueue(QObject):
    """按 (类型, ID) 去重的内存下载队列。

    存 EmotePackage 或 DressCollectionSummary；下载时会重新拉取全量，
    因此不依赖对象是否完整。
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list = []
        self._by_key: dict[tuple, object] = {}

    def add(self, item) -> bool:
        """加入一项；已存在（同类型同 ID）返回 False 不重复加入。"""
        key = item_key(item)
        if key in self._by_key:
            return False
        self._items.append(item)
        self._by_key[key] = item
        self.changed.emit()
        return True

    def add_many(self, items: Iterable) -> int:
        """批量加入；返回实际新增数量。"""
        added = 0
        for item in items:
            key = item_key(item)
            if key in self._by_key:
                continue
            self._items.append(item)
            self._by_key[key] = item
            added += 1
        if added:
            self.changed.emit()
        return added

    def remove(self, keys: Iterable[tuple]) -> int:
        """按 item_key() 返回的去重键移除；返回移除数量。"""
        key_set = set(keys)
        removed = 0
        for key in key_set:
            if key in self._by_key:
                self._by_key.pop(key, None)
                removed += 1
        if removed:
            self._items = [it for it in self._items if item_key(it) not in key_set]
            self.changed.emit()
        return removed

    def clear(self) -> None:
        if not self._items:
            return
        self._items.clear()
        self._by_key.clear()
        self.changed.emit()

    def items(self) -> list:
        """当前队列副本（按加入顺序），混合类型。"""
        return list(self._items)

    def contains(self, item) -> bool:
        return item_key(item) in self._by_key

    def __len__(self) -> int:
        return len(self._items)


download_queue = DownloadQueue()
