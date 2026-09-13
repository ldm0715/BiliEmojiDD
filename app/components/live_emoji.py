"""直播间专属表情（纯网络层 + 数据模型，只在 worker 线程调用）。

`biliemoji==2.0.0` 完全不覆盖直播间接口（`Business` 只有 REPLY / DYNAMIC），
所以这一套自己解析。涉及的三个接口**都是社区逆向记录下来的**
（bilibili-API-collect），不是官方公开 API，随时可能变：

    GetEmoticons   房间的全部表情包（含各包内 emoticons[]）
    Room/get_info  room_id → 主播 uid
    Master/info    uid → 主播昵称与头像

**为什么主播信息要走两步而不是 `xlive/web-room/v1/index/getInfoByRoom`**：
后者一次就能给出 `data.anchor_info.base_info.uname`，但实测匿名一律返回
`code:-352` 风控（带上 buvid3 也照样拦）；上面这两个是 `code:0`，稳。
代价只是多一次请求，且失败可以静默降级（只是展示信息）。

**GetEmoticons 需要登录**：匿名返回 `code:-101 账号未登录`，因此这里把它翻成
`AuthRequired`，交给 `show_bili_error` 走「需要登录 / 请在设置页填写 Cookie」那条提示。

响应是一份很长的嵌套 JSON（实测 `data` 下按包分组，包内是 `emoticons[]`），
而只有 `emoticon_unique` 以 `room_<room_id>_` 开头的才是该直播间的专属表情——
同一份响应里还混着 B 站全局表情。解析见 `parse_emoticons`。

**只在 worker 线程调用**：本模块不 import 任何 Qt 控件，异常原样抛出、由调用方
组装提示。`cookie` / `proxies` 一律由主线程读好再显式传进来。
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from biliemoji.errors import AuthRequired, BiliError

from app.common.net import ProxiesArg, make_bili_session

EMOTICON_URL = (
    "https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons"
)
ROOM_INFO_URL = "https://api.live.bilibili.com/room/v1/Room/get_info"
ANCHOR_INFO_URL = "https://api.live.bilibili.com/live_user/v1/Master/info"

# 客户端档位固定成 pc：接口按它给不同的表情集合，不暴露给用户。
PLATFORM = "pc"

_TIMEOUT = 10

# 未登录 / 认证失效。与 biliemoji 的 AuthRequired 同一个码。
_AUTH_CODE = -101

_IMAGE_SUFFIXES = (".gif", ".png", ".webp", ".jpg", ".jpeg")


class LiveEmojiError(Exception):
    """直播间表情相关错误的基类（`str(e)` 即可直接展示给用户）。"""


class LiveEmojiDisabled(LiveEmojiError):
    """联网被 `set_enabled(False)` 关掉了（只在屏幕外断言脚本里出现）。"""


class LiveEmojiFailed(LiveEmojiError):
    """接口没给出预期结果：HTTP 非 200、不是 JSON、业务 code 非 0、结构异常。"""


@dataclass(frozen=True)
class LiveEmote:
    """一张直播间表情。字段名与 biliemoji 的 `Emote` 不完全一致，故不共用。"""

    text: str  # 接口的 `emoji`，也就是表情名
    url: str  # 已归一化成 https
    unique: str  # `emoticon_unique`，如 room_5236391_109774
    is_gif: bool
    raw: dict

    def ext(self) -> str:
        """下载目标文件的后缀：**照 URL 原样，别按 `is_gif` 反推**。

        `Downloader` 拿到 `expected_ext` 后若与实际内容的魔数不符，会直接判
        FAILED（不是自动改正后缀，见 `biliemoji/downloader.py` 的 `download`），
        猜错就等于该文件永远下不下来。URL 后缀是 CDN 上的真实类型。
        """
        return self._suffix() or ".png"

    def expected_ext(self) -> str | None:
        """给 `DownloadTask` 的格式断言；**认不出的后缀必须给 None**。

        给 None 且目标后缀也不在 `KNOWN_FORMATS` 里时，下载器才不校验格式、
        转而按实际内容嗅探并改正后缀（`_resolve_target` 只改后缀不动父目录，
        所以逐项归属不受影响）。
        """
        suffix = self._suffix()
        return suffix if suffix in _IMAGE_SUFFIXES else None

    def _suffix(self) -> str:
        return Path(urlsplit(self.url).path).suffix.lower()


@dataclass(frozen=True)
class LiveEmotePack:
    """一个直播间的专属表情（= 一个队列项 / 一个下载项）。

    `room_name` 拿不到时退回「直播间 <room_id>」、`anchor_face` 拿不到时是空串——
    两者都只是展示信息，不影响表情本身的获取与下载。
    """

    room_id: str
    room_name: str
    anchor_face: str
    emotes: tuple[LiveEmote, ...]

    def display_name(self) -> str:
        """队列卡 / 详情头的名称。"""
        return self.room_name or f"直播间 {self.room_id}"

    def to_dict(self) -> dict:
        """缓存落盘用（存表情的原始 dict，`from_dict` 无损重建）。"""
        return {
            "room_id": self.room_id,
            "room_name": self.room_name,
            "face": self.anchor_face,
            "emoticons": [em.raw for em in self.emotes],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LiveEmotePack:
        emotes = tuple(
            em
            for em in (_build_emote(raw) for raw in data.get("emoticons") or ())
            if em is not None
        )
        return cls(
            room_id=str(data.get("room_id") or ""),
            room_name=str(data.get("room_name") or ""),
            anchor_face=str(data.get("face") or ""),
            emotes=emotes,
        )


def is_live_pack(item) -> bool:
    """队列项判别用（`download_queue.item_kind` 调）。"""
    return isinstance(item, LiveEmotePack)


# 屏幕外断言脚本把它关掉：否则构造页面就会排真实网络请求
_enabled = True


def set_enabled(flag: bool) -> None:
    """关掉后 `fetch_live_emotes` 直接抛 `LiveEmojiDisabled`，一个请求都不发。"""
    global _enabled
    _enabled = flag


def _ensure_enabled() -> None:
    if not _enabled:
        raise LiveEmojiDisabled("直播间表情已被屏幕外脚本关闭")


def normalize_url(url: str) -> str:
    """`http://*.hdslb.com/...` → `https://...`。

    接口给的是 http 地址，而缩略图与下载都走 https：不归一化的话每次请求都要多
    一个 301 往返。顺带让 `image_cache` 的键（就是 URL）与缩略图请求的键一致。
    只动 B 站自己的 CDN，别的地址原样返回。
    """
    url = (url or "").strip()
    if not url.startswith("http://"):
        return url
    host = urlsplit(url).hostname or ""
    if host == "hdslb.com" or host.endswith(".hdslb.com"):
        return "https://" + url[len("http://") :]
    return url


def emote_is_gif(url: str, is_dynamic) -> bool:
    """两条判据取并集：接口的 `is_dynamic` 标记与 URL 的 `.gif` 后缀。"""
    if is_dynamic:
        return True
    return Path(urlsplit(url or "").path).suffix.lower() == ".gif"


def _build_emote(raw: Mapping[str, Any]) -> LiveEmote | None:
    """一条原始 emoticon → `LiveEmote`；没有可用图片地址的丢掉。"""
    url = normalize_url(str(raw.get("url") or ""))
    if not url:
        return None
    return LiveEmote(
        text=str(raw.get("emoji") or ""),
        url=url,
        unique=str(raw.get("emoticon_unique") or ""),
        is_gif=emote_is_gif(url, raw.get("is_dynamic")),
        raw=dict(raw),
    )


def _iter_emoticon_dicts(node: Any) -> Iterator[Mapping[str, Any]]:
    """深度遍历，逐个吐出所有 `emoticons` 列表里的元素。

    刻意不假定 `data` 的形状（实测是按包分组，但也见过直接给列表／换个包壳的版本），
    凡是键名是 `emoticons` 的列表一律收下。**收下后不再往里递归**——列表元素里
    不会再有嵌套的表情包；而 `recently_used_emoticons` 这类别的键名会继续往下走，
    它们内部没有 `emoticons` 键，所以自然什么都不会收到。
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "emoticons" and isinstance(value, list):
                for em in value:
                    if isinstance(em, Mapping):
                        yield em
            else:
                yield from _iter_emoticon_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_emoticon_dicts(item)


def room_prefix(room_id) -> str:
    """该直播间专属表情的 `emoticon_unique` 前缀（如 `room_5236391_`）。"""
    return f"room_{str(room_id).strip()}_"


def parse_emoticons(payload: Mapping[str, Any], room_id) -> tuple[LiveEmote, ...]:
    """从响应里挑出该直播间的专属表情（纯函数，便于断言脚本喂真实 JSON）。

    一份响应里混着 B 站全局表情，只有 `emoticon_unique` 以 `room_<room_id>_`
    开头的才是这个房间的。按遇到顺序保留、按 `unique` 去重。
    """
    prefix = room_prefix(room_id)
    seen: set[str] = set()
    result: list[LiveEmote] = []
    for raw in _iter_emoticon_dicts(payload.get("data") if payload else None):
        unique = str(raw.get("emoticon_unique") or "")
        if not unique.startswith(prefix) or unique in seen:
            continue
        em = _build_emote(raw)
        if em is None:
            continue
        seen.add(unique)
        result.append(em)
    return tuple(result)


def _request(session: requests.Session, url: str, *, params=None) -> Mapping[str, Any]:
    """GET + HTTP 层校验 + JSON 解析（业务 code 由调用点自己判）。"""
    try:
        response = session.get(url, params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise LiveEmojiFailed(f"请求 {url} 失败：{exc}") from exc
    if response.status_code != 200:
        raise LiveEmojiFailed(f"接口返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LiveEmojiFailed("接口返回的不是 JSON（可能被风控拦了）") from exc
    if not isinstance(payload, Mapping):
        raise LiveEmojiFailed("接口返回结构异常")
    return payload


def _fetch_anchor(session: requests.Session, room_id: str) -> tuple[str, str]:
    """(主播名, 头像 URL)。**任何一步失败都静默返回空串**。

    它们只是展示信息（命令卡上的头像 + 昵称），不该因为房间信息接口抽风就
    把已经拿到的表情一起废掉。
    """
    try:
        info = _request(session, ROOM_INFO_URL, params={"room_id": room_id})
        if info.get("code") != 0:
            return "", ""
        uid = (info.get("data") or {}).get("uid")
        if not uid:
            return "", ""
        payload = _request(session, ANCHOR_INFO_URL, params={"uid": uid})
        if payload.get("code") != 0:
            return "", ""
        base = (payload.get("data") or {}).get("info") or {}
        return str(base.get("uname") or ""), normalize_url(str(base.get("face") or ""))
    except (LiveEmojiError, BiliError, requests.RequestException, AttributeError, TypeError, ValueError):
        return "", ""


def fetch_live_emotes(
    room_id,
    *,
    cookie: str = "",
    proxies: ProxiesArg | None = None,
) -> LiveEmotePack:
    """拉一个直播间的专属表情。

    过滤后为空**不算错误**（该房间确实可能没有专属表情），返回空 `emotes` 的 pack，
    由界面显示空态。`-101` 抛 `AuthRequired`（`show_bili_error` 有现成分支）。
    """
    _ensure_enabled()
    room_id = str(room_id).strip()
    with make_bili_session(cookie=cookie, proxies=proxies) as session:
        payload = _request(
            session, EMOTICON_URL, params={"platform": PLATFORM, "room_id": room_id}
        )
        code = payload.get("code")
        if code == _AUTH_CODE:
            raise AuthRequired(
                "直播间表情需要登录后获取", api_code=_AUTH_CODE, url=EMOTICON_URL
            )
        if code != 0:
            reason = payload.get("message") or payload.get("msg") or "未知错误"
            raise LiveEmojiFailed(f"获取直播间表情失败：{reason}（code={code}）")
        emotes = parse_emoticons(payload, room_id)
        room_name, face = _fetch_anchor(session, room_id)

    return LiveEmotePack(
        room_id=room_id,
        room_name=room_name or f"直播间 {room_id}",
        anchor_face=face,
        emotes=emotes,
    )
