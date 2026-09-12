"""全部表情包列表的本地缓存：避免每次拉取都请求 B 站接口。

缓存按 cookie 指纹区分账号，超过 24 小时自动失效；加载/保存失败都静默，
不影响主流程（最多就是多一次网络请求）。
"""
from __future__ import annotations

import hashlib
import json
import time

from biliemoji.models import EmotePackage

from app.common.config import APP_CONFIG_DIR

_ALL_PACKAGES_FILE = APP_CONFIG_DIR / "all_packages.json"
_CACHE_TTL_SECONDS = 24 * 3600  # 24 小时


def cookie_fingerprint(cookie: str) -> str:
    """Cookie 的短指纹（sha1 前 12 位）。

    用来判断「这份记录/缓存还是不是同一个账号的」——缓存与 Cookie 有效性记录
    （`cookie_status`）共用同一个口径，改动这里等于两处一起改。
    """
    return hashlib.sha1((cookie or "").encode("utf-8")).hexdigest()[:12]


def load_all_packages_cache(cookie: str) -> tuple[EmotePackage, ...] | None:
    """读缓存；缺失 / 过期 / cookie 不匹配时返回 None。"""
    if not _ALL_PACKAGES_FILE.exists():
        return None
    try:
        data = json.loads(_ALL_PACKAGES_FILE.read_text(encoding="utf-8"))
        if data.get("cookie_hash") != cookie_fingerprint(cookie):
            return None
        saved_at = float(data.get("saved_at", 0))
        if time.time() - saved_at > _CACHE_TTL_SECONDS:
            return None
        packages = data.get("packages")
        if not isinstance(packages, list):
            return None
        return tuple(EmotePackage.from_dict(p) for p in packages)
    except Exception:  # noqa: BLE001 缓存损坏则当作未命中
        return None


def save_all_packages_cache(cookie: str, packages) -> None:
    """写缓存。EmotePackage 用其 raw dict 持久化，可无损重建。"""
    try:
        _ALL_PACKAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookie_hash": cookie_fingerprint(cookie),
            "saved_at": time.time(),
            "packages": [p.raw for p in packages],
        }
        _ALL_PACKAGES_FILE.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 写失败不阻塞主流程
        return
