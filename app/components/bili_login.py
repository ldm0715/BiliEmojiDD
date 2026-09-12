"""B 站扫码登录：自动拿到 Cookie 的那条路（纯网络层，只在 worker 线程调用）。

设置页「扫码登录」走的流程：

    generate_qrcode()        → 二维码内容 url + 32 字符密钥
    poll_qrcode(key) 轮询    → 未扫码 / 已扫码未确认 / 成功 / 失效
    fetch_account(cookie)    → 昵称头像，让用户确认登的是哪个号

**接口是社区逆向记录下来的**（bilibili-API-collect），不是 B 站官方公开 API，
随时可能变。所以设置页必须保留手动粘贴 Cookie 的入口当退路——这里失效了还能用。

**只在 worker 线程调用**（走 `run_task`）：本模块不 import 任何 Qt 控件，异常原样
抛出、由调用方组装提示。`proxies` 一律由主线程读好 `current_proxies()` 再显式传进来，
worker 不碰 `cfg`（照 `thumb` / `video_cache` 的老规矩）。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

from app.common.net import ProxiesArg, make_bili_session

QRCODE_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
QRCODE_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# B 站侧的密钥有效期（秒）。对话框的本地倒计时照这个数走，到点自己判失效——
# 不然轮询会一直转下去。
QRCODE_TTL_SECONDS = 180

_TIMEOUT = 10

# 拼进 `cfg.cookie` 的字段与顺序。SESSDATA 是认账号的那一个，排最前便于人工排查。
_COOKIE_FIELDS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")

class LoginError(Exception):
    """扫码登录相关错误的基类（`str(e)` 即可直接展示给用户）。"""


class LoginDisabled(LoginError):
    """联网被 `set_enabled(False)` 关掉了（只在屏幕外断言脚本里出现）。"""


class LoginFailed(LoginError):
    """接口没给出预期结果：HTTP 非 200、不是 JSON、字段缺失。"""


class LoginState(Enum):
    """一次轮询的结果。"""

    WAITING = "waiting"  # 86101：还没人扫
    SCANNED = "scanned"  # 86090：扫了，但手机端没点确认
    CONFIRMED = "confirmed"  # 0：登录成功
    EXPIRED = "expired"  # 86038：密钥过期，得重新申请


# poll 响应里 `data.code` 的取值（HTTP 一律 200，状态在响应体里）。
# 表里没有的码按「失效」处理，理由见 `_state_from_payload`。
_STATE_BY_CODE: dict[int, LoginState] = {
    0: LoginState.CONFIRMED,
    86038: LoginState.EXPIRED,
    86090: LoginState.SCANNED,
    86101: LoginState.WAITING,
}


@dataclass(frozen=True)
class QrCode:
    """一次登录二维码申请的结果。`url` 是二维码的**内容**，不是图片地址。"""

    url: str
    key: str


@dataclass(frozen=True)
class Account:
    """Cookie 对应的账号。"""

    mid: int
    name: str
    face: str

    @property
    def display(self) -> str:
        """给设置页副标题用的一行文字。"""
        return f"{self.name} · UID {self.mid}" if self.mid else self.name


# 屏幕外断言脚本把它关掉：否则构造设置页就会排真实网络请求
_enabled = True


def set_enabled(flag: bool) -> None:
    """关掉后三个联网函数直接抛 `LoginDisabled`，一个请求都不发。"""
    global _enabled
    _enabled = flag


def _ensure_enabled() -> None:
    if not _enabled:
        raise LoginDisabled("扫码登录已被屏幕外脚本关闭")


def _get(session: requests.Session, url: str, *, params=None):
    """GET + 网络异常统一翻成 `LoginError`（`__cause__` 保留给 `cause_hint` 用）。"""
    try:
        return session.get(url, params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise LoginFailed(f"请求 {url} 失败：{exc}") from exc


def _payload(response) -> Mapping[str, Any]:
    """HTTP 层校验 + JSON 解析。

    **刻意不看业务 `code`**：`nav` 未登录时会返回 `code: -101` 但 HTTP 200，
    那是正常结果不是错误。每个调用点自己决定 `code` 意味着什么。
    """
    if response.status_code != 200:
        raise LoginFailed(f"接口返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LoginFailed("接口返回的不是 JSON（可能被风控拦了）") from exc
    if not isinstance(payload, Mapping):
        raise LoginFailed("接口返回结构异常")
    return payload


def _state_from_payload(data: Mapping[str, Any]) -> LoginState:
    """把 poll 的 `data` 翻成状态。

    认不出的码**一律当失效**：卡在「等待扫码」里转圈是最难排查的一种表现，
    而判失效是可恢复的（对话框上有刷新按钮）。
    """
    return _STATE_BY_CODE.get(data.get("code"), LoginState.EXPIRED)


def _cookie_from_headers(response) -> dict[str, str]:
    """主路径：从响应的 `Set-Cookie` 里挑出认识的字段。"""
    found: dict[str, str] = {}
    for name in _COOKIE_FIELDS:
        value = response.cookies.get(name)
        if value:
            found[name] = value
    return found


def _cookie_from_cross_domain(data: Mapping[str, Any]) -> dict[str, str]:
    """回退路径：成功响应里的 `data.url` 是个 crossDomain 跳转地址，
    几个 cookie 以 query 参数的形式挂在上面。

    `Set-Cookie` 要靠 cookie jar 解析，遇到 Domain 属性、重定向或 jar 被清过时
    未必留得下；这个 URL 就在同一个响应体里，两条路互为兜底。

    **不做 URL 解码**：cookie 值在这里就是 URL 编码形式，解了反而与
    `Set-Cookie` 那条路的取值对不上（SESSDATA 里含 `%2C` 这类转义）。
    """
    url = str(data.get("url") or "")
    _, _, query = url.partition("?")
    if not query:
        return {}
    raw: dict[str, str] = {}
    for pair in query.split("&"):
        name, _, value = pair.partition("=")
        if value:
            raw[name] = value
    return {name: raw[name] for name in _COOKIE_FIELDS if name in raw}


def _join_cookie(fields: Mapping[str, str]) -> str:
    """按固定顺序拼成 `Cookie` 头认得的形式。"""
    return "; ".join(
        f"{name}={fields[name]}" for name in _COOKIE_FIELDS if fields.get(name)
    )


def generate_qrcode(*, proxies: ProxiesArg | None = None) -> QrCode:
    """申请一个登录二维码。密钥 180 秒后过期。

    `proxies` 由调用方在主线程读好 `current_proxies()` 后传入；传 `None` 即直连。
    """
    _ensure_enabled()
    with make_bili_session(proxies=proxies) as session:
        payload = _payload(_get(session, QRCODE_GENERATE_URL))
    if payload.get("code") != 0:
        raise LoginFailed(
            f"申请二维码失败：{payload.get('message') or '未知错误'}"
        )
    data = payload.get("data") or {}
    url = str(data.get("url") or "")
    key = str(data.get("qrcode_key") or "")
    if not url or not key:
        raise LoginFailed("申请二维码失败：接口没有返回二维码内容")
    return QrCode(url=url, key=key)


def poll_qrcode(
    key: str, *, proxies: ProxiesArg | None = None
) -> tuple[LoginState, str]:
    """查一次扫码状态，返回 `(状态, cookie 串)`。

    cookie 只在 `CONFIRMED` 时非空；其余状态是空串。
    """
    _ensure_enabled()
    if not key:
        raise LoginFailed("二维码密钥为空")
    with make_bili_session(proxies=proxies) as session:
        response = _get(session, QRCODE_POLL_URL, params={"qrcode_key": key})
        payload = _payload(response)
        data = payload.get("data") or {}
        state = _state_from_payload(data)
        if state is not LoginState.CONFIRMED:
            return state, ""
        fields = _cookie_from_headers(response) or _cookie_from_cross_domain(data)
    cookie = _join_cookie(fields)
    if not cookie:
        raise LoginFailed("登录成功，但没能从响应里取到 Cookie")
    return state, cookie


def fetch_account(
    cookie: str, *, proxies: ProxiesArg | None = None
) -> Account | None:
    """拿 Cookie 对应的账号信息；没登录或字段不全返回 `None`。

    用 `nav` 接口：它本来就是「我登的是谁」的权威答案，且顺便能验证 Cookie
    还有没有效。
    """
    _ensure_enabled()
    if not (cookie or "").strip():
        return None
    with make_bili_session(cookie=cookie, proxies=proxies) as session:
        payload = _payload(_get(session, NAV_URL))
    data = payload.get("data") or {}
    if not data.get("isLogin"):
        return None
    name = str(data.get("uname") or "").strip()
    if not name:
        return None
    mid = data.get("mid")
    return Account(
        mid=mid if isinstance(mid, int) else 0,
        name=name,
        face=str(data.get("face") or "").strip(),
    )
