"""Cookie 有效性状态：全应用共用的一个「Cookie 还能用吗」结论。

主页英雄卡的状态灯不能再只看「Cookie 填没填」——Cookie 被 B 站吊销后灯必须变红。
但**不必一直检测**：结论有信任期，期内进主页只读记录、一个请求都不发。
「每次进主页跑一次检测逻辑」与「不要一直检测」的调和点就在这里：
**逻辑每次都跑，网络探测受信任期约束**（别把 `ensure_checked` 里的早退当 bug）。

两条信任期**刻意不对称**：

| 结论 | 信任期 | 为什么 |
|---|---|---|
| 有效 `VALID` | 7 天 | 服务器确认过的强事实，期间不再打扰 |
| 失效 `INVALID` | 30 分钟 | **弱事实**：`nav` 在风控下会返回 HTTP 200 + 空 `data`，看起来就是「没登录」。锁 7 天红灯就再也纠正不过来 |
| 网络失败 | 不写记录 | 网络不通不该把灯变红，下次进主页再试 |

换号 / 手动登出 / 重新保存 Cookie 一律由调用方 `invalidate()` 作废 —— Cookie 值
变了指纹就对不上，`known_state()` 自然回到 `UNKNOWN`（这就是存指纹的意义）。

详细推导见 `docs/cookie_status.md`。
"""
from __future__ import annotations

import time

from qfluentwidgets import qconfig

from app.common.config import cfg
from app.common.net import current_proxies
from app.common.signal_bus import signal_bus
from app.components.bili_login import fetch_account
from app.components.cache import cookie_fingerprint
from app.components.task import run_task

NO_COOKIE = "no_cookie"  # 配置里没填 Cookie
CHECKING = "checking"  # 正在联网检测（只在内存里，不落盘）
VALID = "valid"
INVALID = "invalid"
UNKNOWN = "unknown"  # 没验过 / 记录已过信任期 / 上次检测网络失败

# 检测结果的信任期（秒）。失效那一档短得多，理由见模块 docstring。
_TRUST_VALID_SECONDS = 7 * 24 * 3600
_TRUST_INVALID_SECONDS = 30 * 60

# 屏幕外断言脚本把它关掉：`ensure_checked()` 直接返回，一个任务都不提交
_enabled = True
# 探针在飞。既防「切走又切回来」叠任务，也是界面显示「正在检测…」的判据
_inflight = False


def set_enabled(flag: bool) -> None:
    """关掉后 `ensure_checked()` 直接返回。

    **注意不是「提交了任务再抛异常」，是一个任务都不提交** —— 否则每个构造
    主页 / MainWindow 的离屏脚本都会留一个真线程，退出时踩「worker 还没回调、
    控件已析构」的假象。
    """
    global _enabled
    _enabled = flag


def known_state() -> str:
    """同步、零网络地推断当前状态（读配置 + 算指纹 + 比信任期）。"""
    cookie = _live_cookie()
    if not cookie:
        return NO_COOKIE
    at, recorded_hash, state = _record()
    if state not in (VALID, INVALID):
        return UNKNOWN
    if recorded_hash != cookie_fingerprint(cookie):
        return UNKNOWN  # 换号 / 登出后重登：记录不是这个 Cookie 的
    trust = _TRUST_VALID_SECONDS if state == VALID else _TRUST_INVALID_SECONDS
    if time.time() - at > trust:
        return UNKNOWN
    return state


def current_state() -> str:
    """**界面该显示的状态**：正在检测时恒为 `CHECKING`。

    英雄卡读这个，别读 `known_state()` —— 否则「正在检测…」会被任何一次
    `refresh()` 立刻盖成「未验证」。
    """
    return CHECKING if _inflight else known_state()


def ensure_checked() -> str:
    """进主页时调用：需要联网才联网，否则只把当前结论广播一次。返回当前状态。"""
    if not _enabled or _inflight:
        return current_state()
    state = known_state()
    if state == UNKNOWN:
        _start_probe()
        return current_state()
    signal_bus.cookieStateChanged.emit(state)
    return state


def note(state: str, cookie: str = "") -> None:
    """把一次外部结论（设置页「验证」/ 扫码后那次 `nav`）并进同一份记录。

    `cookie` 是**发起这次请求时的快照**：worker 回来时配置可能已经变了
    （用户在这期间登出 / 换号），拿快照算指纹才不会把结论写到别人头上。
    留空则读当前配置。

    `UNKNOWN` 不落盘（那是「不知道」，不是结论）。快照已经不是当前 Cookie 时
    也不写 —— 那条结论对眼下这个 Cookie 没有意义。
    """
    cookie = (cookie or _live_cookie()).strip()
    if state in (VALID, INVALID) and cookie and cookie == _live_cookie():
        qconfig.set(cfg.cookie_checked_at, int(time.time()))
        qconfig.set(cfg.cookie_checked_hash, cookie_fingerprint(cookie))
        qconfig.set(cfg.cookie_checked_state, state)
    _emit()


def invalidate() -> None:
    """作废记录：Cookie 值变了 / 手动登出 / **重新保存了 Cookie**。

    重填**同一个** Cookie 也要调它 —— 「我又填了一遍」的意图就是「重新验证」，
    不能因为指纹恰好没变就把上一盏红灯继续摆 7 天。
    """
    qconfig.set(cfg.cookie_checked_at, 0)
    qconfig.set(cfg.cookie_checked_hash, "")
    qconfig.set(cfg.cookie_checked_state, "")
    _emit()


# ---- 内部 ----


def _live_cookie() -> str:
    return cfg.cookie.value.strip()


def _record() -> tuple[float, str, str]:
    return (
        float(cfg.cookie_checked_at.value or 0),
        str(cfg.cookie_checked_hash.value or ""),
        str(cfg.cookie_checked_state.value or ""),
    )


def _emit() -> None:
    signal_bus.cookieStateChanged.emit(current_state())


def _start_probe() -> None:
    """起一次 `nav` 探针（全项目最轻的「Cookie 还有效吗」）。"""
    global _inflight
    cookie = _live_cookie()
    # 代理在主线程读好再交给 worker：worker 线程不碰 cfg（见 net.py 模块说明）
    proxies = current_proxies()
    _inflight = True
    signal_bus.cookieStateChanged.emit(CHECKING)
    run_task(
        lambda: fetch_account(cookie, proxies=proxies),
        # 只有「B 站明确说没登录」（返回 None）才判失效；网络异常不写记录、
        # 保持原状 —— 网络不通不该把灯变红
        on_success=lambda account: note(
            VALID if account is not None else INVALID, cookie
        ),
        on_error=lambda _exc: None,
        # 收尾必须挂在 on_finished 上：成功与两条异常路都会走它，`_inflight`
        # 才不会在失败后永久卡住（那样探针与自动预拉取就再也不重试）
        on_finished=lambda _ok: _finish_probe(),
    )


def _finish_probe() -> None:
    global _inflight
    _inflight = False
    _emit()
