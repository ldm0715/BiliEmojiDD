"""屏幕外验证扫码登录：状态映射、Cookie 拼装、二维码渲染、对话框状态机、设置页接线。

**不联网**：开头就 `bili_login.set_enabled(False)`，对话框那节再把
`generate_qrcode` / `poll_qrcode` 换成脚本化的假函数。

**真实扫码（手机 App 扫屏幕上的码）没法自动化**，这个脚本能证明的只有
「状态怎么翻、码怎么画、线下之后界面怎么变」——真机扫一次得人工来。

1. poll 的 `data.code` → `LoginState`（含认不出的码当失效）；
2. Cookie 拼装：`Set-Cookie` 与 crossDomain URL 两条路径结果一致，且不做 URL 解码；
3. `set_enabled(False)` 后三个联网函数抛 `LoginDisabled`，一个 session 都不建；
4. 二维码矩阵带 quiet zone；`_QrCodeView` 烤出的位图是白底黑块；
5. `LoginDialog` 状态机：未扫码 → 已扫码 → 成功；失效停轮询；关窗后迟到的回调不生效；
6. 设置页账号卡的三态显隐（未登录两个入口 / 登录后只剩退出 / 退出后复原）、退出只清
   登录态、手动填写对话框的空输入禁用与去空白；
7. `AccountAvatar`：没图整个隐藏；喂非正方形大图后仍是 40x40 且真的渲染成圆形。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_login.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 必须在 import app.* 之前：APP_CONFIG_DIR 在导入时按 APPDATA 算，不隔离就会
# 写脏用户真实的 config.json（本脚本第 6 节会改 cookie 与账号信息）。
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliemoji-check-login-")

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import MessageBox

app = QApplication(sys.argv)

from app.common.config import cfg
from app.components import bili_login as bl
from app.components import login_dialog
from app.view.setting_page import SettingPage

# 全程关联网：任何漏网的请求都会在这里直接抛，而不是挂 15 秒超时
bl.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def pump(rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.005)


def pump_until(cond, timeout: float = 3.0) -> bool:
    """等后台任务回到主线程（run_task 的信号是 QueuedConnection，要真跑事件循环）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(cond())


class _FakeCookies(dict):
    """够 `response.cookies.get(name)` 用。"""


class _FakeResponse:
    def __init__(self, payload, cookies=None, status=200) -> None:
        self._payload = payload
        self.cookies = _FakeCookies(cookies or {})
        self.status_code = status

    def json(self):
        return self._payload


# ---------------------------------------------------------------- 1
print("== 1. poll 的 data.code → 状态 ==")
for code, expected, label in (
    (86101, bl.LoginState.WAITING, "未扫码"),
    (86090, bl.LoginState.SCANNED, "已扫码未确认"),
    (0, bl.LoginState.CONFIRMED, "登录成功"),
    (86038, bl.LoginState.EXPIRED, "二维码已失效"),
):
    got = bl._state_from_payload({"code": code})
    check(got is expected, f"code={code} → {expected.name}（{label}）")
check(
    bl._state_from_payload({"code": 99999}) is bl.LoginState.EXPIRED,
    "认不出的码当失效（卡在「等待扫码」比误判失效更难排查）",
)
check(
    bl._state_from_payload({}) is bl.LoginState.EXPIRED,
    "data 里没有 code 也当失效",
)

# ---------------------------------------------------------------- 2
print("== 2. Cookie 拼装的两条路径 ==")
_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
_EXPECTED_COOKIE = (
    "SESSDATA=sd%2Cxx; bili_jct=jc; DedeUserID=123; "
    "DedeUserID__ckMd5=ab%2Ccd; sid=si"
)

from_headers = bl._cookie_from_headers(
    _FakeResponse(
        {},
        cookies={
            "SESSDATA": "sd%2Cxx",
            "bili_jct": "jc",
            "DedeUserID": "123",
            "DedeUserID__ckMd5": "ab%2Ccd",
            "sid": "si",
            "buvid3": "ignore-me",  # 不认识的字段不该混进来
        },
    )
)
check(
    bl._join_cookie(from_headers) == _EXPECTED_COOKIE,
    f"Set-Cookie 路径拼装正确（{bl._join_cookie(from_headers)}）",
)

from_url = bl._cookie_from_cross_domain(
    {
        "url": (
            "https://passport.biligame.com/crossDomain?"
            "DedeUserID=123&DedeUserID__ckMd5=ab%2Ccd&Expires=1700000000"
            "&SESSDATA=sd%2Cxx&bili_jct=jc&sid=si"
            "&gourl=https%3A%2F%2Fpassport.bilibili.com"
        )
    }
)
check(
    bl._join_cookie(from_url) == _EXPECTED_COOKIE,
    f"crossDomain URL 路径与上面结果一致（{bl._join_cookie(from_url)}）",
)
check(
    from_url["SESSDATA"] == "sd%2Cxx",
    "URL 路径刻意不解码：cookie 值在 URL 里就是编码形式，解了会和 Set-Cookie 对不上",
)
check(bl._cookie_from_cross_domain({"url": ""}) == {}, "url 为空时返回空")
check(
    bl._join_cookie({}) == "" and bl._join_cookie({"SESSDATA": ""}) == "",
    "空字段不产生 `=;` 这种垃圾片段",
)

# ---------------------------------------------------------------- 3
print("== 3. set_enabled(False) 一个 session 都不建 ==")
_built: list[int] = []
_real_make = bl.make_bili_session


def _spy_make(*args, **kwargs):
    _built.append(1)
    return _real_make(*args, **kwargs)


bl.make_bili_session = _spy_make
bl.set_enabled(False)
for label, call in (
    ("generate_qrcode", lambda: bl.generate_qrcode()),
    ("poll_qrcode", lambda: bl.poll_qrcode("k" * 32)),
    ("fetch_account", lambda: bl.fetch_account("SESSDATA=x")),
):
    try:
        call()
        check(False, f"{label} 应抛 LoginDisabled")
    except bl.LoginDisabled:
        check(True, f"{label} 抛 LoginDisabled")
check(not _built, "关联网后一次会话都没建（请求根本没发出去）")
bl.make_bili_session = _real_make
# 关联网是「全关」：先过一道开关再谈参数（与 updater 的 set_enabled 同一套语义），
# 所以空 Cookie 的早退要走正常开关态才看得到
bl.set_enabled(True)
check(bl.fetch_account("   ") is None, "空 Cookie 直接返回 None")
check(bl.fetch_account("") is None, "空字符串同样返回 None")
bl.set_enabled(False)

# ---------------------------------------------------------------- 4
print("== 4. 二维码矩阵与绘制 ==")
_QR_CONTENT = (
    "https://passport.bilibili.com/h5-app/passport/login/scan"
    "?navhide=1&qrcode_key=" + "a" * 32 + "&from="
)
matrix = login_dialog.qr_matrix(_QR_CONTENT)
size = len(matrix)
check(size > 21, f"矩阵是真实二维码尺寸（{size}x{size}）")
check(
    all(row == (0,) * size for row in matrix[:4])
    and all(row == (0,) * size for row in matrix[-4:]),
    "上下各留 4 行 quiet zone（贴边画的码手机扫不出来）",
)
check(
    all(row[c] == 0 for row in matrix for c in range(4)),
    "左右各留 4 列 quiet zone",
)
check(sum(sum(row) for row in matrix) > 0, "矩阵里有定位黑块")

qr_view = login_dialog._QrCodeView()
qr_view.set_matrix(matrix)
pixmap = qr_view._pixmap
check(not pixmap.isNull(), "矩阵喂进去后烤出了位图")
image = pixmap.toImage()
check(
    image.pixelColor(1, 1).name() == "#ffffff"
    and image.pixelColor(image.width() - 2, image.height() - 2).name() == "#ffffff",
    "四角是白底（二维码固定配色，不跟主题）",
)
check(
    image.pixelColor(image.width() // 2, image.height() // 2).name() != "#ffffff",
    "中心有黑块（不是一张白图）",
)
qr_view.clear()
check(qr_view._pixmap.isNull(), "clear() 后位图作废（失效态不再显示旧码）")

# ---------------------------------------------------------------- 5
print("== 5. LoginDialog 状态机 ==")
win = QWidget()
win.resize(800, 600)
win.show()

_scripted: list = []


def _fake_generate(*, proxies=None):
    return bl.QrCode(url=_QR_CONTENT, key="k" * 32)


def _fake_poll(key, *, proxies=None):
    return _scripted.pop(0) if _scripted else (bl.LoginState.WAITING, "")


bl.generate_qrcode = _fake_generate
bl.poll_qrcode = _fake_poll


def _tick_now(dialog) -> None:
    """立刻触发一次轮询：把 `_last_poll` 归零，免得等满 2 秒间隔。"""
    dialog._last_poll = 0.0
    dialog._tick()


def _poll_once(dialog) -> None:
    pump_until(lambda: not dialog._polling)
    dialog._polling = False


won: list[str] = []
dialog = login_dialog.LoginDialog(win, on_success=won.append)
check(pump_until(lambda: dialog._timer.isActive()), "申请到二维码后开始轮询")
check(not dialog.qrView._pixmap.isNull(), "二维码已画到控件上")
check("扫码" in dialog.hint_text(), f"初始提示扫码（{dialog.hint_text()!r}）")
check(
    dialog.yesButton.text() == "刷新二维码" and dialog.cancelButton.text() == "关闭",
    "按钮文案：刷新二维码 / 关闭（yesButton 已从上游的 accept 断开）",
)

_poll_once(dialog)
check(
    "扫码" in dialog.hint_text() and "确认" not in dialog.hint_text(),
    f"未扫码时文案不变（{dialog.hint_text()!r}）",
)

_scripted.append((bl.LoginState.SCANNED, ""))
_tick_now(dialog)
_poll_once(dialog)
check("确认" in dialog.hint_text(), f"已扫码后提示去手机确认（{dialog.hint_text()!r}）")

_scripted.append((bl.LoginState.CONFIRMED, "SESSDATA=abc; bili_jct=def"))
_tick_now(dialog)
check(pump_until(lambda: bool(won)), "确认登录后回调 on_success")
check(
    won == ["SESSDATA=abc; bili_jct=def"], f"回调拿到拼好的 Cookie（{won}）"
)
check(not dialog._timer.isActive() and dialog._closed, "成功后停轮询并关窗")

# 失效路径
_scripted.clear()
expired: list[str] = []
dialog2 = login_dialog.LoginDialog(win, on_success=expired.append)
pump_until(lambda: dialog2._timer.isActive())
_poll_once(dialog2)  # 先等构造时那次 poll 落地，否则 _tick 会被 _polling 挡住
_scripted.append((bl.LoginState.EXPIRED, ""))
_tick_now(dialog2)
_poll_once(dialog2)
check("失效" in dialog2.hint_text(), f"失效后提示可刷新（{dialog2.hint_text()!r}）")
check(not dialog2._timer.isActive(), "失效后停止轮询（不再白跑请求）")

# 关窗后迟到的回调
dialog3 = login_dialog.LoginDialog(win, on_success=expired.append)
pump_until(lambda: dialog3._timer.isActive())
dialog3.reject()
dialog3._on_poll((bl.LoginState.CONFIRMED, "SESSDATA=late"))
dialog3._on_qr_ready(bl.QrCode(url=_QR_CONTENT, key="x"))
check(not expired, "关窗后迟到的成功回调被丢弃（不会去动已析构的控件）")
check(dialog3._closed, "reject 之后 _closed 为真")

# 被隐藏也要收摊：父窗口关闭时 Qt 是把子窗口隐藏掉，**根本不发 closeEvent**。
# 先 show 再 hide —— hide() 对没显示过的控件是 no-op，不 show 就测了个寂寞
dialog4 = login_dialog.LoginDialog(win, on_success=expired.append)
dialog4.show()
pump_until(lambda: dialog4._timer.isActive())
dialog4.hide()
check(
    dialog4._closed and not dialog4._timer.isActive(),
    "被隐藏后停轮询（只挂 closeEvent 会漏掉这条，定时器会继续空跑）",
)

# ---------------------------------------------------------------- 6
print("== 6. 设置页接线（账号卡按登录态切换） ==")
# 预置内存缓存：否则 request() 会排一个真实的 15s 超时下载，脚本退不出去
_face_url = "https://i0.hdslb.com/bfs/face/fake-avatar.jpg"
_face_pm = QPixmap(200, 120)
_face_pm.fill(QColor("#3366cc"))
QPixmapCache.insert(_face_url, _face_pm)

page = SettingPage()
page.resize(900, 760)
page.show()
pump()

# ---- 未登录：两个入口 ----
check(
    page.loginCard.contentLabel.text().startswith("未登录"),
    f"未登录时副标题（{page.loginCard.contentLabel.text()!r}）",
)
check(
    page.scanLoginBtn.isVisible() and page.manualCookieBtn.isVisible(),
    "未登录时给两条路（扫码为主、手动填写为退路）",
)
check(not page.logoutBtn.isVisible(), "未登录时没有「退出登录」")
check(
    not page.avatar.isVisible() and not page.avatar.has_url(),
    "未登录时头像不显示（没有账号就没有头像位，不留占位图）",
)
check(
    not hasattr(page, "cookieCard") and not hasattr(page, "saveBtn"),
    "Cookie 卡与保存按钮已并进账号卡，不再单独出现",
)

# ---- 登录：入口换成退出 ----
page._on_login_ok("SESSDATA=abc; bili_jct=def")
pump()
check(
    cfg.cookie.value == "SESSDATA=abc; bili_jct=def",
    f"登录成功后 Cookie 写入配置（{cfg.cookie.value!r}）",
)
check(
    page.logoutBtn.isVisible()
    and not page.scanLoginBtn.isVisible()
    and not page.manualCookieBtn.isVisible(),
    "登录后只剩「退出登录」，两个登录入口同时消失",
)
check(
    page.loginCard.contentLabel.text() == "已登录",
    f"有 Cookie 但还没拿到账号信息时的文案（{page.loginCard.contentLabel.text()!r}）",
)

# ---- 账号信息回来 ----
page._on_account(bl.Account(mid=12345, name="测试账号", face=_face_url))
pump()
check(
    page.loginCard.contentLabel.text() == "测试账号 · UID 12345",
    f"账号信息回来后副标题变昵称（{page.loginCard.contentLabel.text()!r}）",
)
check(
    page.avatar.isVisible() and page.avatar.has_url(),
    "拿到头像 URL 后头像显示出来（命中缓存，同步到位）",
)
check(
    (page.avatar.width(), page.avatar.height()) == (40, 40),
    f"卡片里的头像也是 40x40（实际 {page.avatar.width()}x{page.avatar.height()}）",
)
check(
    cfg.account_name.value == "测试账号" and cfg.account_mid.value == 12345,
    "账号信息落盘",
)
page._on_account(None)
pump()
check(
    page.loginCard.contentLabel.text() == "测试账号 · UID 12345",
    "拿不到账号信息时不覆盖已有昵称",
)

# ---- 退出登录 ----
# `MessageBox.exec()` 会阻塞（离屏下更是直接把脚本挂住），替它作答「点了退出」
MessageBox.exec = lambda self: True
try:
    page._on_logout()
finally:
    del MessageBox.exec
pump()
check(cfg.cookie.value == "", "退出后 Cookie 被清空")
check(
    cfg.account_name.value == "" and cfg.account_mid.value == 0,
    "退出后账号信息一并清掉",
)
check(
    page.scanLoginBtn.isVisible() and page.manualCookieBtn.isVisible(),
    "退出后回到未登录态：两个登录入口回来",
)
check(
    not page.logoutBtn.isVisible() and not page.avatar.isVisible(),
    "退出后「退出登录」与头像一起收起",
)
check(
    page.loginCard.contentLabel.text().startswith("未登录"),
    f"退出后副标题（{page.loginCard.contentLabel.text()!r}）",
)

# ---- 手动填写对话框 ----
saved: list[str] = []
cookie_dialog = login_dialog.show_cookie_dialog(win, cookie="", on_save=saved.append)
check(
    not cookie_dialog.yesButton.isEnabled(),
    "Cookie 为空时「保存」禁用（组件库 LineEdit 没有 setError，做不了错误态）",
)
cookie_dialog.cookieEdit.setText("  SESSDATA=xyz  ")
check(cookie_dialog.yesButton.isEnabled(), "填了内容后「保存」可用")
cookie_dialog._on_yes()
check(saved == ["SESSDATA=xyz"], f"保存时去掉首尾空白（{saved}）")
# 关窗要走完上游的淡出动画，不能立即断言 —— 那是 `hide()` 之后才发生的
check(
    pump_until(lambda: not cookie_dialog.isVisible()),
    "保存后对话框关闭（等淡出动画走完）",
)
cookie_dialog.deleteLater()

# ---------------------------------------------------------------- 7
print("== 7. 头像控件 ==")
avatar = login_dialog.AccountAvatar()
check(not avatar.isVisible(), "没 URL 时整个藏起来（不显示占位头像）")
check(
    (avatar.width(), avatar.height()) == (40, 40) and avatar.getRadius() == 20,
    f"固定 40x40、半径 20（实际 {avatar.width()}x{avatar.height()} r={avatar.getRadius()}）",
)

avatar._on_thumb(_face_url, _face_pm)  # 还没 set_url
check(avatar.width() == 40, "没设 url 时忽略缩略图信号（尺寸也没被图撑走）")

avatar.set_url(_face_url)  # 命中 QPixmapCache，request() 同步 emit
check(avatar.isVisible() and avatar.has_url(), "set_url 后显示出来（命中缓存，同步到位）")
check(
    (avatar.width(), avatar.height()) == (40, 40),
    "喂图之后控件仍是 40x40 —— 上游 setImage 会 setFixedSize(图片尺寸)，"
    f"不钉回去这里就会变成 200x120（实际 {avatar.width()}x{avatar.height()}）",
)
check(
    avatar.image.size() == QSize(200, 120),
    f"内部存的是原图、不预缩放（{avatar.image.size()}）",
)

# 真正渲染一次：量「画出来什么」而不是「内部存了什么」。
# 上面几条只保证尺寸对，圆形裁剪到底有没有生效得看图。
avatar.show()
pump()
shot = avatar.grab().toImage()
dpr = avatar.devicePixelRatioF()
side = round(40 * dpr)
check(
    (shot.width(), shot.height()) == (side, side),
    f"渲染出来就是头像控件那么大（{shot.width()}x{shot.height()}，期望 {side}）",
)
# 四角不是透明的——控件有自己的 QSS 背景。圆形裁剪的判据是「圆外没被头像染上」
corner = shot.pixelColor(1, 1).name()
check(
    shot.pixelColor(side // 2, side // 2).name() == "#3366cc",
    f"圆内是头像本体（实际 {shot.pixelColor(side // 2, side // 2).name()}）",
)
check(
    corner != "#3366cc",
    f"圆外没被头像染上（圆形裁剪生效，角落实际 {corner}）",
)

avatar.set_url("")
check(
    not avatar.isVisible() and avatar.image.isNull(),
    "清空 url 后重新藏起来并丢掉旧图",
)

# ---------------------------------------------------------------- 收尾
dialog2.reject()
page.close()
win.close()
pump(20)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for item in FAILS:
        print("  - " + item)
    sys.exit(1)
print("ALL PASSED")
