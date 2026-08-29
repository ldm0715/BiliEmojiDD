"""屏幕外验证代理相关逻辑（不联网）。

1. `cause_hint` 能沿异常链认出常见代理故障并给出可行动的中文；
2. `parse_proxy` / `split_proxy_auth` / `build_proxy` 对 socks 与认证段往返正确；
3. **应用不写任何代理环境变量**——代理只以 `proxies=` 参数显式传给 requests；
4. 每个联网入口（Emoji / Dress / 缩略图）建 `BiliClient` 时都带上了 proxies；
5. 设置页的协议下拉给全了四种协议、`_current_proxy()` 会拦掉非法主机名与缺依赖的 socks。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_proxy_hint.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA，否则会写脏真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

import requests
from biliemoji import NetworkError
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.common.config import cfg
from app.common.exception import cause_hint
from app.common.proxy import (
    PROXY_SCHEMES,
    build_proxy,
    is_socks,
    parse_proxy,
    proxy_scheme,
    pysocks_available,
    redact_proxy,
    split_proxy,
    split_proxy_auth,
)
from app.view.setting_page import SettingPage

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def wrapped(inner: Exception) -> NetworkError:
    """复刻 biliemoji.client 的包法：raise NetworkError(...) from requests 异常。"""
    try:
        raise inner
    except Exception as exc:  # noqa: BLE001 这里就是要把它当 cause
        try:
            raise NetworkError(
                f"网络错误：{type(exc).__name__}",
                url="https://api.bilibili.com/x/vas/dlc_act/lottery_home_detail",
            ) from exc
        except NetworkError as outer:
            return outer


print("== 1. 因果翻译 ==")
cases = [
    (
        requests.exceptions.ProxyError(
            "HTTPSConnectionPool(host='api.bilibili.com', port=443): "
            "Max retries exceeded (Caused by ProxyError('Unable to connect to proxy', "
            "OSError('Tunnel connection failed: 400 Bad Request')))"
        ),
        "CONNECT",
    ),
    (
        requests.exceptions.ProxyError(
            "Unable to connect to proxy: Tunnel connection failed: "
            "407 Proxy Authentication Required"
        ),
        "认证",
    ),
    (
        requests.exceptions.ProxyError(
            "HTTPSConnectionPool(host='api.bilibili.com', port=443): "
            "Max retries exceeded (Caused by ProxyError('Unable to connect to proxy', "
            "SSLError('Your proxy appears to only use HTTP, not HTTPS')))"
        ),
        "协议改成 HTTP",
    ),
    (
        requests.exceptions.ProxyError(
            "Cannot connect to proxy. NewConnectionError: [WinError 10061] "
            "由于目标计算机积极拒绝，无法连接。"
        ),
        "连不上代理服务器",
    ),
    (
        requests.exceptions.InvalidSchema(
            "Missing dependencies for SOCKS support."
        ),
        "PySocks",
    ),
    (requests.exceptions.ConnectTimeout("timed out"), "超时"),
    (requests.exceptions.SSLError("certificate verify failed"), "TLS"),
]
for inner, keyword in cases:
    hint = cause_hint(wrapped(inner))
    check(
        keyword in hint,
        f"{type(inner).__name__} → 提示含「{keyword}」（实际：{hint[:40]}…）",
    )
check(cause_hint(ValueError("随便什么")) == "", "认不出来的异常返回空串，不硬编中文")
# 断言链路真的走到了 __cause__：外层消息本身不含这些关键字
outer = wrapped(cases[0][0])
check(
    "ProxyError" in str(outer) and "Tunnel" not in str(outer),
    "外层 NetworkError 消息本身没有原因，确实是从 __cause__ 挖出来的",
)

print("== 2. 地址往返（含 socks 与认证）==")
check(PROXY_SCHEMES == ("http", "https", "socks5", "socks5h"), "支持四种协议")
proxies = parse_proxy("socks5://1.2.3.4:1080")
check(
    proxies == {"http": "socks5://1.2.3.4:1080", "https": "socks5://1.2.3.4:1080"},
    f"parse_proxy 保留 socks5 scheme（{proxies}）",
)
check(proxy_scheme("socks5h://h:1") == "socks5h", "proxy_scheme 认得 socks5h")
check(split_proxy("socks5://1.2.3.4:1080") == ("socks5", "1.2.3.4", 1080), "split_proxy 拆分正确")
check(build_proxy("socks5h", "h", 1080) == "socks5h://h:1080", "build_proxy 拼回原样")
check(build_proxy("socks5", "", 1080) == "", "主机名为空 = 不使用代理")
check(is_socks("socks5") and is_socks("socks5h") and not is_socks("http"), "is_socks 判别正确")
check(pysocks_available(), "PySocks 已安装（socks 代理可用）")

# 认证段：密码里带 @ / : 是合法的，必须转义 + 按最后一个 @ 切回来
built = build_proxy("http", "1.2.3.4", 8080, "u@ser", "p:a@ss")
check(built == "http://u%40ser:p%3Aa%40ss@1.2.3.4:8080", f"用户名/密码百分号转义（{built}）")
parts = split_proxy_auth(built)
check(
    parts == ("http", "u@ser", "p:a@ss", "1.2.3.4", 8080),
    f"含特殊字符的认证段能原样拆回来（{tuple(parts)}）",
)
check(
    split_proxy(built) == ("http", "1.2.3.4", 8080),
    "split_proxy 只给 scheme/host/port，不把认证段混进 host",
)
check(
    redact_proxy(built) == "http://u%40ser:***@1.2.3.4:8080",
    f"展示用地址把密码打码（{redact_proxy(built)}）",
)
check(redact_proxy("") == "", "空地址不产生噪音")
check(
    split_proxy_auth("1.2.3.4:8080") == ("http", "", "", "1.2.3.4", 8080),
    "无 scheme 时按 http 处理",
)

print("== 3. 没有全局代理副作用 ==")
# 应用只走显式 proxies=，绝不写 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
import app.common.proxy as proxy_mod

check(
    not hasattr(proxy_mod, "ProxyEnvManager") and not hasattr(proxy_mod, "proxy_env"),
    "ProxyEnvManager / proxy_env 已移除",
)
env_before = {
    k: os.environ.get(k)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy")
}
page = SettingPage()
page.resize(900, 700)
page.show()
app.processEvents()
page.protoCombo.setCurrentIndex(0)
page.hostEdit.setText("127.0.0.1")
page.portSpin.setValue(7890)
page._on_save_download()
app.processEvents()
env_after = {k: os.environ.get(k) for k in env_before}
check(env_before == env_after, f"保存代理不写任何代理环境变量（{env_after}）")
check(cfg.proxy.value == "http://127.0.0.1:7890", f"代理只落在配置里（{cfg.proxy.value!r}）")

print("== 4. 每个联网入口都显式带 proxies ==")
# 抓 BiliClient 的构造参数，确认 proxies 真的传到了 requests 那一层
import biliemoji
from biliemoji.client import BiliClient

seen: list[dict | None] = []
orig_init = BiliClient.__init__


def spy_init(self, *a, **kw):
    seen.append(kw.get("proxies"))
    return orig_init(self, *a, **kw)


BiliClient.__init__ = spy_init
try:
    biliemoji.Emoji(cookie="", proxies=parse_proxy(cfg.proxy.value))
    biliemoji.Dress(cookie="", proxies=parse_proxy(cfg.proxy.value))
    # 缩略图 worker：以前它 new BiliClient 时漏了 proxies，只能靠全局环境变量兜底
    from app.components.thumb import ThumbLoadTask

    ThumbLoadTask("https://x.invalid/a.png", "", parse_proxy(cfg.proxy.value)).run()
finally:
    BiliClient.__init__ = orig_init
expected = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
check(len(seen) == 3, f"三个入口各建了一个 BiliClient（实际 {len(seen)}）")
check(
    all(p == expected for p in seen),
    f"Emoji / Dress / 缩略图都显式传了 proxies（实际 {seen}）",
)

print("== 5. 设置页校验 ==")
check(
    [page.protoCombo.itemData(i) for i in range(page.protoCombo.count())]
    == list(PROXY_SCHEMES),
    "协议下拉的 userData 与 PROXY_SCHEMES 一致（addItem 第二位置参是 icon，必须用关键字）",
)
page.protoCombo.setCurrentIndex(0)
page.hostEdit.setText("127.0.0.1")
page.portSpin.setValue(7890)
check(
    page._current_proxy() == "http://127.0.0.1:7890",
    f"合法输入拼出代理地址（{page._current_proxy()!r}）",
)
page.hostEdit.setText("http://127.0.0.1")
check(page._current_proxy() is None, "主机名带协议前缀被拦下")
page.hostEdit.setText("")
check(page._current_proxy() == "", "主机名留空 = 不使用代理")
check(hasattr(page, "proxyTestBtn"), "代理卡上有「测试」按钮")
check(
    "CONNECT" in page.proxyCard.toolTip(),
    "tooltip 点明 B 站是 HTTPS、代理必须支持 CONNECT",
)
check(
    hasattr(page, "proxyUserEdit") and hasattr(page, "proxyPassEdit"),
    "有代理认证的用户名 / 密码输入框",
)
page.hostEdit.setText("1.2.3.4")
page.proxyUserEdit.setText("u")
page.proxyPassEdit.setText("p@ss")
check(
    page._current_proxy() == "http://u:p%40ss@1.2.3.4:7890",
    f"认证信息拼进代理地址（{page._current_proxy()!r}）",
)
page.close()

cfg.proxy.value = ""

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
