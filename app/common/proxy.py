"""代理工具：把设置页填的代理地址转成 requests 的 `proxies=` 参数。

**只走显式 `proxies=`，不碰环境变量。** 应用不设 `HTTP_PROXY` / `HTTPS_PROXY` /
`ALL_PROXY`——那是进程级的全局副作用，而且 requests 的
`Session.merge_environment_settings` 会把环境变量塞进**请求级** proxies，再由
`merge_setting(请求级, 会话级)` 让请求级覆盖 `session.proxies`，反倒把显式传入的值顶掉。
所有联网入口（`api_cache` / `download_runner` / `thumb` / `video_cache` /
`proxy_probe` / 设置页验证 / 全部表情包）一律显式带上 `proxies=`。

三个容易踩的点：

- **地址里的 scheme 指的是「代理自身说什么协议」**，不是「被代理的流量是什么协议」。
  绝大多数 HTTP 代理只讲明文，写成 `https://` 会让 requests 去跟代理做 TLS 握手，
  报 `ProxyError: Your proxy appears to only use HTTP, not HTTPS`。
- **B 站接口全是 HTTPS，走 HTTP 代理时必须靠 `CONNECT` 建隧道**。只会转发明文
  `http://` 的代理会拒掉 CONNECT（`Tunnel connection failed: 4xx`），这类代理用不了。
- **要认证的代理得把用户名 / 密码写进地址**（`scheme://user:pass@host:port`），
  否则代理回 407，requests 同样抛 ProxyError。用户名密码里的特殊字符必须百分号转义，
  所以拼装/拆解统一走本模块的 `build_proxy` / `split_proxy_auth`。

socks5 需要 PySocks（已在 `pyproject.toml` 的 dependencies 里）；`socks5h` 表示
域名解析也交给代理做（远程 DNS）。
"""
from __future__ import annotations

from importlib.util import find_spec
from typing import NamedTuple
from urllib.parse import quote, unquote

# 支持的代理协议（设置页下拉与校验共用这一份）
PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")


class ProxyParts(NamedTuple):
    """代理地址的各个字段（用户名 / 密码已解码成明文）。"""

    scheme: str
    username: str
    password: str
    host: str
    port: int


def pysocks_available() -> bool:
    """PySocks 是否可用（socks 代理的硬依赖）。"""
    return find_spec("socks") is not None


def is_socks(scheme: str | None) -> bool:
    return bool(scheme) and scheme.lower().startswith("socks")


def parse_proxy(text: str) -> dict[str, str] | None:
    """把单个代理地址转成 requests 的 proxies 字典；空串返回 None。

    无 scheme 时自动补 http://。
    """
    text = (text or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "http://" + text
    return {"http": text, "https": text}


def proxy_scheme(text: str) -> str | None:
    """取代理地址的 scheme（小写）；无 scheme 视为 http；空串返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    return (text.split("://", 1)[0] if "://" in text else "http").lower()


def split_proxy_auth(text: str) -> ProxyParts:
    """把代理地址拆成各字段；空串返回 ('http', '', '', '', 0)。

    不用 `urlsplit`：密码里出现 `@`（合法且常见）会让它按第一个 `@` 切错，
    这里统一按**最后一个 `@`** 切认证段，与 requests / urllib3 的做法一致。
    """
    text = (text or "").strip()
    if not text:
        return ProxyParts("http", "", "", "", 0)
    scheme = "http"
    rest = text
    if "://" in text:
        scheme, rest = text.split("://", 1)
    username = password = ""
    if "@" in rest:
        auth, rest = rest.rsplit("@", 1)
        username, _, password = auth.partition(":")
        username, password = unquote(username), unquote(password)
    if ":" in rest:
        host, port = rest.rsplit(":", 1)
    else:
        host, port = rest, ""
    return ProxyParts(
        scheme.lower(), username, password, host, int(port) if port.isdigit() else 0
    )


def split_proxy(text: str) -> tuple[str, str, int]:
    """把代理地址拆成 (scheme, host, port)（不含认证段）。"""
    parts = split_proxy_auth(text)
    return parts.scheme, parts.host, parts.port


def build_proxy(
    scheme: str, host: str, port: int, username: str = "", password: str = ""
) -> str:
    """由各字段拼代理地址；host 为空返回空串（不使用代理）。

    用户名 / 密码里的 `:@/` 等字符必须百分号转义，否则 requests 会把地址切错。
    """
    scheme = (scheme or "http").strip().lower()
    host = (host or "").strip()
    if not host:
        return ""
    auth = ""
    username = (username or "").strip()
    password = password or ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    port = int(port) if port else 0
    tail = f":{port}" if port > 0 else ""
    return f"{scheme}://{auth}{host}{tail}"


def redact_proxy(text: str) -> str:
    """把代理地址里的密码换成 ***，供日志 / 提示展示。"""
    parts = split_proxy_auth(text)
    if not parts.host:
        return ""
    # 不复用 build_proxy：它会把 *** 也百分号转义成 %2A%2A%2A
    base = build_proxy(parts.scheme, parts.host, parts.port)
    if not parts.username:
        return base
    auth = quote(parts.username, safe="") + (":***" if parts.password else "")
    return base.replace("://", f"://{auth}@", 1)
