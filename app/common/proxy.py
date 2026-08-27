"""代理工具：URL 解析 + HTTP(S)_PROXY 环境变量兜底（带原值快照）。

背景：biliemoji 的 download_package / download_collection 不会把 proxies 传给
内部新建的 Downloader（只作用于元数据请求），文件下载只能靠环境变量兜底——
requests Session 默认 trust_env=True，会自动读取 HTTP(S)_PROXY。
显式 proxies 优先级更高：requests 用 setdefault 合并 env，显式值不会被 env 覆盖。

注意：PySocks 未安装，socks/socks4/socks5 代理不支持，设置页需拦截。
"""
from __future__ import annotations

import os

# Windows 上 os.environ 大小写不敏感（HTTP_PROXY 与 http_proxy 是同一变量），
# 只管理大写即可覆盖小写；POSIX 大小写敏感，requests 会小写化读取，因此两边都设。
_ENV_KEYS = (
    ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    if os.name == "nt"
    else ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
)


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


def split_proxy(text: str) -> tuple[str, str, int]:
    """把代理地址拆成 (scheme, host, port)；空串返回 ('http', '', 0)。"""
    text = (text or "").strip()
    if not text:
        return "http", "", 0
    scheme = "http"
    rest = text
    if "://" in text:
        scheme, rest = text.split("://", 1)
    if ":" in rest:
        host, port = rest.rsplit(":", 1)
    else:
        host, port = rest, ""
    port_int = int(port) if port.isdigit() else 0
    return scheme.lower(), host, port_int


def build_proxy(scheme: str, host: str, port: int) -> str:
    """由 scheme/host/port 拼代理地址；host 为空返回空串（不使用代理）。"""
    scheme = (scheme or "http").strip().lower()
    host = (host or "").strip()
    if not host:
        return ""
    port = int(port) if port else 0
    if port <= 0:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


class ProxyEnvManager:
    """管理 HTTP(S)_PROXY 环境变量：启动时快照原值，清空设置时恢复而非无条件删除。"""

    def __init__(self) -> None:
        self._original: dict[str, str | None] = {}

    def remember(self) -> None:
        """启动时调用一次：快照当前环境变量原值（原本不存在的键记为 None）。"""
        self._original = {k: os.environ.get(k) for k in _ENV_KEYS}

    def apply(self, proxy: str) -> None:
        """应用代理设置：非空则设置全部大小写键；空则恢复快照原值。"""
        proxy = (proxy or "").strip()
        for key in _ENV_KEYS:
            if proxy:
                os.environ[key] = proxy
            elif key in self._original:
                original = self._original[key]
                if original is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original
            else:
                os.environ.pop(key, None)


proxy_env = ProxyEnvManager()
