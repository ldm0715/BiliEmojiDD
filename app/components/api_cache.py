"""带磁盘缓存的 B 站取数入口：搜索结果 / 表情包详情 / 收藏集详情。

在此之前每次搜索、每次进详情都是一次网络请求——同一个关键词搜两次就请求两次。
本模块在 `biliemoji` 调用外面套一层 TTL 磁盘缓存：

- 三个模型（`EmotePackage` / `DressCollection` / `DressCollectionSummary`）都带
  `raw` 原始 dict 与 `from_dict`，所以缓存存 raw、读回来无损重建；
- **只缓存成功结果**：`AuthRequired` / `DressNotFound` 等照常抛给 `show_bili_error`；
- key 不掺 cookie 指纹——这三个接口的返回与账号无关（`all_packages` 是例外，仍在 `cache.py`）。

**只在 worker 线程调用**（都在 `run_task` 的 task 闭包 / `_MetaTask.run` 里）。
"""
from __future__ import annotations

import json

from biliemoji import Dress, Emoji
from biliemoji.models import DressCollection, DressCollectionSummary, EmotePackage

from app.common.config import cfg
from app.common.proxy import parse_proxy
from app.components.disk_cache import api_store

_SEARCH_TTL = 6 * 3600  # 搜索结果：新品上架要能看到，给短一点
_DETAIL_TTL = 24 * 3600  # 详情：内容基本不变


def _load(key: str, ttl: float):
    data = api_store.get(key, ttl=ttl)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:  # noqa: BLE001 缓存损坏当作未命中
        return None


def _save(key: str, payload) -> None:
    try:
        api_store.put(key, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except Exception:  # noqa: BLE001 写失败不阻塞主流程
        return


def search_dress(num: int, keyword: str) -> tuple[DressCollectionSummary, ...]:
    """收藏集 / 装扮搜索（空结果由 biliemoji 抛 DressNotFound）。"""
    key = f"dress:search:{num}:{keyword}"
    cached = _load(key, _SEARCH_TTL)
    if isinstance(cached, list):
        return tuple(DressCollectionSummary.from_dict(d) for d in cached)
    result = Dress(
        cookie=cfg.cookie.value, proxies=parse_proxy(cfg.proxy.value)
    ).search_dress_typed(num, keyword=keyword)
    _save(key, [s.raw for s in result])
    return tuple(result)


def emoji_package(pid: int) -> EmotePackage:
    """表情包详情（含完整 emote）。"""
    key = f"emoji:pkg:{pid}"
    cached = _load(key, _DETAIL_TTL)
    if isinstance(cached, dict):
        return EmotePackage.from_dict(cached)
    pkg = Emoji(
        cookie=cfg.cookie.value, proxies=parse_proxy(cfg.proxy.value)
    ).certain_emoji_typed(pid)
    _save(key, pkg.raw)
    return pkg


def dress_collection(act_id, lottery_id) -> DressCollection:
    """收藏集详情（图片 / 视频清单）。"""
    key = f"dress:coll:{act_id}:{lottery_id}"
    cached = _load(key, _DETAIL_TTL)
    if isinstance(cached, dict):
        return DressCollection.from_dict(cached)
    coll = Dress(
        cookie=cfg.cookie.value, proxies=parse_proxy(cfg.proxy.value)
    ).certain_lottery_typed(act_id, lottery_id)
    _save(key, coll.raw)
    return coll
