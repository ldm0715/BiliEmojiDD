"""联网对象工厂：所有 `Emoji` / `Dress` / `BiliClient` / `Downloader` 都从这里建。

存在的理由是两条必须同时成立、又都很容易漏掉的规矩：

1. **代理只来自设置页。** 每个联网入口都得显式带上 `proxies=`——工厂的默认值就是
   「从配置读」，所以漏传也不会静默变成直连。
2. **`trust_env = False`。** 这条是关键：requests 的 `Session.trust_env` 默认为 True，
   `merge_environment_settings()` 会调 `urllib.request.getproxies()`，在 Windows 上先读
   `HTTP_PROXY` 环境变量，读不到就**读注册表里的 IE / 系统代理**（Clash、v2ray 开
   「系统代理」写的就是那里）。拿到的值被 `setdefault` 进**请求级** proxies，再由
   `merge_setting(请求级, session.proxies)` 让请求级**覆盖**会话级。也就是说：不关掉
   `trust_env`，设置页留空时应用会偷偷走系统代理，填了也可能被系统代理顶掉。

`current_proxies()` 会读 `cfg`，**只能在主线程或 worker 线程里安全读取配置的场合调用**；
`thumb` / `video_cache` 这类 worker 仍按老规矩在主线程读好 proxies 再显式传进来。

详见 `docs/proxy_diagnostics.md`。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import requests
from biliemoji import Downloader, Dress, Emoji
from biliemoji.client import BiliClient

from app.common.config import APP_NAME, APP_VERSION, cfg
from app.common.proxy import parse_proxy

# 默认值哨兵：区分「没传，去读配置」与「显式传了 None，就是要直连」
_FROM_CFG: Any = object()

ProxiesArg = Mapping[str, str] | None

# 非 B 站请求（检查更新）用的 UA：GitHub API 不带 UA 直接 403
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"

# B 站 web 端接口（biliemoji 那四个之外的）用的浏览器 UA。
# **不能拿 USER_AGENT 顶**：passport 这类接口会按 UA 判客户端，"BiliEmojiDD/0.1.2"
# 大概率被风控挡掉。版本档位与 biliemoji 内部的 UA 池保持一致，免得同一账号
# 在服务端看来是两套客户端。
BILI_WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.6778.108 Safari/537.36"
)
BILI_REFERER = "https://www.bilibili.com/"


def current_proxies() -> dict[str, str] | None:
    """当前该用的代理；开关关闭或地址为空时返回 None（直连）。"""
    if not cfg.proxy_enabled.value:
        return None
    return parse_proxy(cfg.proxy.value)


def _resolve(proxies: ProxiesArg | Any) -> dict[str, str] | None:
    if proxies is _FROM_CFG:
        return current_proxies()
    return dict(proxies) if proxies else None


def _no_env(session: requests.Session) -> requests.Session:
    """断开 requests 与环境变量 / 系统代理的联系。"""
    session.trust_env = False
    return session


def make_client(
    cookie: str = "", proxies: ProxiesArg | Any = _FROM_CFG, **kwargs
) -> BiliClient:
    """建一个只认显式代理的 BiliClient。"""
    client = BiliClient(cookie=cookie, proxies=_resolve(proxies), **kwargs)
    _no_env(client.session)
    return client


def make_session(
    proxies: ProxiesArg | Any = _FROM_CFG,
    *,
    headers: Mapping[str, str] | None = None,
) -> requests.Session:
    """通用 requests 会话：检查更新这类**非 B 站**请求用它。

    `make_client` 那套（`BiliClient` + cookie + B 站签名）不适用于 GitHub，但本模块
    的两条硬规矩照守：代理只来自设置页、`trust_env = False`。
    """
    session = _no_env(requests.Session())
    session.headers["User-Agent"] = USER_AGENT
    if headers:
        session.headers.update(headers)
    resolved = _resolve(proxies)
    if resolved:
        session.proxies.update(resolved)
    return session


def make_bili_session(
    cookie: str = "",
    proxies: ProxiesArg | Any = _FROM_CFG,
) -> requests.Session:
    """B 站通用接口的会话（biliemoji 那四个接口之外的那些）。

    存在的理由：扫码登录要读 **`Set-Cookie` 响应头**，而 `BiliClient.get_json()`
    只返回 `resp.json()`，够不着响应头。本模块的两条硬规矩照守：代理只来自设置页、
    `trust_env = False`。

    cookie 挂在 session 默认头上（不是每次请求传）：`nav` 这类接口靠它认账号。
    只在 worker 线程使用。
    """
    session = make_session(
        proxies,
        headers={"User-Agent": BILI_WEB_UA, "Referer": BILI_REFERER},
    )
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def make_emoji(cookie: str = "", proxies: ProxiesArg | Any = _FROM_CFG) -> Emoji:
    """表情包接口。走 `Emoji(client=...)` 把配好的客户端塞进去。

    cookie 同时给 `Emoji` 和它内部的客户端：`all_packages()` 认的是
    `self._client.cookie`，而 `Emoji.cookie` 属性保持一致便于排查。
    """
    return Emoji(cookie=cookie, client=make_client(cookie=cookie, proxies=proxies))


def make_dress(cookie: str = "", proxies: ProxiesArg | Any = _FROM_CFG) -> Dress:
    """收藏集 / 装扮接口。"""
    return Dress(cookie=cookie, client=make_client(cookie=cookie, proxies=proxies))


class _NoEnvDownloader(Downloader):
    """`_build_session` 是上游唯一建 session 的地方（worker-local，见 downloader.py）。

    覆写它而不是自己造 session：retry 次数、backoff、连接池大小都由上游算，不必重复一遍。
    """

    def _build_session(self) -> requests.Session:
        return _no_env(super()._build_session())


def make_downloader(
    *,
    max_workers: int = 8,
    on_progress: Callable[..., None] | None = None,
    proxies: ProxiesArg | Any = _FROM_CFG,
    **kwargs,
) -> Downloader:
    """文件下载器。biliemoji 的 `download_package` / `download_collection` 不会把
    proxies 转发给内部 Downloader，需要显式代理的批量下载一律用这个工厂。
    """
    return _NoEnvDownloader(
        max_workers=max_workers,
        on_progress=on_progress,
        proxies=_resolve(proxies),
        **kwargs,
    )
