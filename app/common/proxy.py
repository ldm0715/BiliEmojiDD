"""代理地址工具：把设置页填的那一行字转成 requests 的 `proxies=` 参数。

**应用只认设置页里的那一个地址。** 代理开关关闭 = 彻底直连；开着就只用填的那个地址。
不写任何 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量，也不读 Windows 系统代理——后者靠
`app/common/net.py` 给每个 Session 设 `trust_env = False` 实现（requests 默认会去读
注册表里的 IE 代理设置，并且**覆盖**显式传入的 `proxies`，详见 `docs/proxy_diagnostics.md`）。

地址就是 requests 认的那种 URL：`scheme://[user:pass@]host[:port]`。
scheme 指的是**代理自身说什么协议**（`http` / `https` / `socks5` / `socks5h`），
不是被代理流量的协议——绝大多数本地代理软件是 `http`。省略 scheme 时按 `http` 处理。
socks 需要 PySocks（已在 `pyproject.toml` 的 dependencies 里）。

本模块只做字符串处理，不碰配置、不建连接。取「当前该用哪个代理」请用
`app/common/net.py::current_proxies()`。
"""
from __future__ import annotations

# 设置页输入框的占位符，同时也是最常见的本地代理地址
PROXY_PLACEHOLDER = "http://127.0.0.1:7890"


def normalize_proxy(text: str) -> str:
    """规范化代理地址：去空白，无 scheme 时补 `http://`；空串原样返回。"""
    text = (text or "").strip()
    if not text:
        return ""
    return text if "://" in text else "http://" + text


def parse_proxy(text: str) -> dict[str, str] | None:
    """把代理地址转成 requests 的 proxies 字典；空串返回 None（直连）。"""
    address = normalize_proxy(text)
    if not address:
        return None
    return {"http": address, "https": address}


def redact_proxy(text: str) -> str:
    """把地址里的密码换成 `***`，供日志 / 错误提示展示；空串返回空串。

    认证段按**最后一个 `@`** 切：`@` 是合法的密码字符，按第一个切会把地址切错
    （`urlsplit` 就是这么切的，所以这里不用它）。
    """
    address = normalize_proxy(text)
    if not address:
        return ""
    scheme, _, rest = address.partition("://")
    if "@" not in rest:
        return address
    auth, host = rest.rsplit("@", 1)
    username, sep, _ = auth.partition(":")
    return f"{scheme}://{username}{':***' if sep else ''}@{host}"
