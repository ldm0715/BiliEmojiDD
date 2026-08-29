"""BiliError 异常 → InfoBar 中文提示 的统一映射。

`biliemoji.client` 把所有 requests 异常压成 `NetworkError(f"网络错误：{类型名}")`，
真正的原因（连不上代理 / 代理不讲 TLS / socks 缺依赖…）只留在 `__cause__` 里。
所以这里额外沿异常链取一次因果，翻成可行动的中文——不然用户看到的就是一句
「网络错误：ProxyError」，无从下手。
"""
from __future__ import annotations

from biliemoji import (
    AuthRequired,
    BiliError,
    DownloadError,
    DressNotFound,
    NetworkError,
    NotFoundError,
    ValidationError,
)
from qfluentwidgets import InfoBarPosition

from app.common.config import cfg
from app.common.notify import notify_error, notify_warning
from app.common.proxy import redact_proxy

_MAX_CAUSE_DEPTH = 6  # 异常链一般两三层，给点余量即可


def _chain(exc: BaseException) -> list[tuple[str, str]]:
    """异常链上的 (类名, 消息)，从最外层往里走。"""
    out: list[tuple[str, str]] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and len(out) < _MAX_CAUSE_DEPTH and id(cur) not in seen:
        seen.add(id(cur))
        out.append((type(cur).__name__, str(cur)))
        cur = cur.__cause__ or cur.__context__
    return out


def _proxy_suffix() -> str:
    proxy = redact_proxy(cfg.proxy.value or "")
    return f"当前代理：{proxy}" if proxy else "当前未使用代理"


def cause_hint(exc: BaseException) -> str:
    """把底层网络异常翻成一句可行动的中文；认不出来返回空串。"""
    chain = _chain(exc)
    names = {name for name, _ in chain}
    text = " ".join(msg for _, msg in chain).lower()

    if "ProxyError" in names:
        # 407 优先判：隧道失败的消息里往往同时带着 "Tunnel connection failed: 407"
        if "407" in text or "proxy authentication required" in text:
            return (
                "代理要求认证。请到「设置 → 下载 → 代理」填写用户名与密码。"
            )
        if "tunnel connection failed" in text:
            return (
                "代理拒绝建立 HTTPS 隧道（CONNECT）。B 站接口全是 HTTPS，"
                "只能转发明文 http:// 的代理用不了——需要换一个支持 CONNECT 的代理。"
            )
        if "only use http" in text:
            return (
                "该代理只讲明文 HTTP，不接受 TLS 握手。请到「设置 → 下载 → 代理」"
                "把协议改成 HTTP（这里选的是代理自身的协议，不是被代理流量的协议）。"
            )
        if "socks" in text and "missing dependencies" in text:
            return "socks 代理需要 PySocks，请执行 uv sync 后重启应用。"
        if (
            "refused" in text
            or "cannot connect to proxy" in text
            or "10061" in text
            or "unreachable" in text
        ):
            return "连不上代理服务器。请确认代理在运行、端口填对（ping 通只说明主机在，不代表该端口上有代理）。"
        if "timed out" in text or "timeout" in text:
            return "连接代理超时。请确认端口正确、代理允许本机访问。"
        return "代理连接失败。请到「设置 → 下载 → 代理」检查协议 / 地址 / 端口 / 账号，或先清空代理试试。"

    if "InvalidSchema" in names or "InvalidProxyURL" in names:
        if "socks" in text:
            return "socks 代理需要 PySocks，请执行 uv sync 后重启应用。"
        return "代理地址格式不对，请到「设置 → 下载 → 代理」重填。"

    if "SSLError" in names:
        return "TLS 握手失败。若走了代理，多半是协议选成了 HTTPS 而代理只讲 HTTP。"

    if "ConnectTimeout" in names or "ReadTimeout" in names or "Timeout" in names:
        return "连接超时。请检查网络；若走了代理，确认代理可用。"

    if "ConnectionError" in names or "NewConnectionError" in names:
        return "无法连接到服务器。请检查网络与代理设置。"

    return ""


def _network_content(exc: Exception, fallback: str) -> str:
    """网络类异常的提示正文：原始消息 + 因果中文 + 当前代理。"""
    parts = [str(exc) or fallback]
    hint = cause_hint(exc)
    if hint:
        parts.append(hint)
    parts.append(_proxy_suffix())
    return "\n".join(parts)


def show_bili_error(exc: Exception, parent=None) -> None:
    """把 worker 线程冒出的异常映射为中文 InfoBar 提示。"""
    if isinstance(exc, AuthRequired):
        notify_error(
            "需要登录",
            "Cookie 缺失或已过期，请在「设置」页填写 Cookie",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )
    elif isinstance(exc, DressNotFound):
        notify_warning(
            "没有结果",
            "未找到相关收藏集",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, NotFoundError):
        notify_error(
            "未找到",
            str(exc) or "请求的对象不存在",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, NetworkError):
        notify_error(
            "网络错误",
            _network_content(exc, "网络请求失败，请检查网络后重试"),
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=8000,  # 带诊断信息，给足阅读时间
        )
    elif isinstance(exc, DownloadError):
        notify_error(
            "下载失败",
            _network_content(exc, "文件下载失败"),
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=8000,
        )
    elif isinstance(exc, ValidationError):
        notify_warning(
            "参数错误",
            str(exc) or "输入参数不合法",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, BiliError):
        notify_error(
            "B 站接口错误",
            str(exc) or type(exc).__name__,
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )
    else:
        # 未知异常保留详情供排查，但 UI 不崩溃
        notify_error(
            type(exc).__name__,
            str(exc) or repr(exc),
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=0,
        )
