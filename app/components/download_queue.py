"""会话级下载队列：内存存储，混合表情包 / 收藏集 / 直播间表情，按类型+ID 去重，重启后清空。"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal

from app.components.dress_helpers import dlc_ids
from app.components.live_emoji import is_live_pack


def item_kind(item) -> str:
    """'package'（表情包）/ 'collection'（收藏集）/ 'live'（直播间表情）。

    **live 必须最先判**：下面的 `emote` 二分是有 `.emote` 就当表情包、否则一律
    收藏集，直播间表情一旦漏进来就会被静默当成收藏集（下载走错分支、卡片渲染
    读错字段），不会报错，所以判别顺序是有意义的。
    """
    if is_live_pack(item):
        return "live"
    return "package" if getattr(item, "emote", None) is not None else "collection"


def item_key(item) -> tuple[str, object]:
    """去重键。表情包 ("pkg", id)；收藏集 ("coll", ...)；直播间表情 ("live", room_id)。

    收藏集**不能只用 item_id**：搜索结果里 `item_id == properties.dlc_act_id`，
    而一个 dlc 活动下有多期 lottery（如「2233的MBTI-能量之源」act=112667 lot=112709
    与「2233的MBTI-ENFP」act=112667 lot=113521），每期都是独立的可下载收藏集。
    按 item_id 去重会把同活动的不同期判成同一项——多选加入时被悄悄丢掉，进详情页
    却因为 contains() 命中而显示「已加入」。act + lottery 才是唯一键，也正是
    certain_lottery_typed / 下载用的那一对 id。

    非收藏集的装扮（type='ip'，无 dlc id）退回 item_id / id / 名称，各自带前缀
    防跨方案撞车。summary.id 因 biliemoji 解析 bug 恒为 None，只能读 raw。

    三种类型的键前缀互不相同——`download_mixed_batch` 合并三个子批的 `per_item`
    时靠的就是「键不撞车」。
    """
    kind = item_kind(item)
    if kind == "live":
        return ("live", str(item.room_id))
    if kind == "package":
        return ("pkg", item.id)
    act_id, lottery_id = dlc_ids(item)
    if act_id and lottery_id:
        return ("coll", f"dlc:{act_id}:{lottery_id}")
    raw = getattr(item, "raw", None) or {}
    item_id = raw.get("item_id")
    if item_id is None:  # 防御：字段位置不同版本可能有差异
        item_id = (raw.get("properties") or {}).get("item_id")
    if item_id is not None:
        return ("coll", f"item:{item_id}")
    raw_id = raw.get("id")
    if raw_id is not None:
        return ("coll", f"id:{raw_id}")
    return ("coll", "name:" + (getattr(item, "name", None) or ""))


def item_cover_url(item) -> str | None:
    """队列项封面 URL：表情包取包内第一张表情（动图优先），收藏集取 image_cover，
    直播间表情取房间内的第一张。

    下载页队列卡与主页队列预览共用，保证两处显示同一张图。
    """
    kind = item_kind(item)
    if kind == "live":
        emotes = item.emotes or ()
        return emotes[0].url if emotes else None
    if kind == "collection":
        return getattr(item, "image_cover", None)
    emote = getattr(item, "emote", None) or ()
    if emote:
        first = emote[0]
        if first.gif_url:
            return first.gif_url
        if first.url:
            return first.url
    return getattr(item, "url", None)


class DownloadQueue(QObject):
    """按 (类型, ID) 去重的内存下载队列。

    存 EmotePackage / DressCollectionSummary / LiveEmotePack；前两者下载时会重新
    拉取全量，因此不依赖对象是否完整（LiveEmotePack 自带全部表情，不需要再取）。
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
