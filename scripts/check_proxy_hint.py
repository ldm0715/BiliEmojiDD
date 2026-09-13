"""屏幕外验证代理相关逻辑（不联网）。

1. `normalize_proxy` / `parse_proxy` / `redact_proxy` 的规范化与打码；
2. 为旧「配代理软件」UI 写的那批函数确已删除；
3. **每个联网入口的 Session 都 `trust_env = False`**——否则 requests 会读
   Windows 系统代理 / `HTTP_PROXY` 并覆盖显式传入的 proxies；
4. 代理开关：关 → `current_proxies()` 为 None；改代理不写任何代理环境变量；
5. 设置页：开关关着地址框不可编辑、`_current_proxy()` 的规范化与拦截；
5b. **即时生效**（下载组没有「保存」按钮，开关 / 地址框 / 下载目录 / 线程数都是改完即落库）
    + 副标题显示生效值 + 清空地址框会真的把地址从配置里清掉；
5c. 「测试」失败提示报的是被测地址与接口，不是 `cfg.proxy`；
6. `cause_hint` 仍能沿异常链认出常见代理故障；
7. **配置：代理一律默认关**——不再有「老配置里有地址就自动置开」的迁移
   （那是「装新版本后代理开关默认是打开的」的根因）；布尔项的非法值回落各自默认值，
   不会被上游 `BoolValidator` 兜成 `True`。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_proxy_hint.py
"""
from __future__ import annotations

import json
import os
import subprocess
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

from qfluentwidgets import qconfig

from app.common.config import cfg
from app.common.exception import cause_hint
from app.common.net import (
    current_proxies,
    make_client,
    make_downloader,
    make_dress,
    make_emoji,
    make_session,
)
from app.common.notify import NEVER_DISMISS
from app.common.proxy import (
    PROXY_PLACEHOLDER,
    normalize_proxy,
    parse_proxy,
    redact_proxy,
)
from app.components.proxy_probe import PROBE_URL
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


print("== 1. 地址规范化 ==")
check(normalize_proxy("  127.0.0.1:7890 ") == "http://127.0.0.1:7890", "无协议时补 http:// 并去空白")
check(normalize_proxy("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080", "已有协议原样保留")
check(normalize_proxy("") == "" and normalize_proxy("   ") == "", "空串 / 全空白 -> 空串")
proxies = parse_proxy("socks5h://1.2.3.4:1080")
check(
    proxies == {"http": "socks5h://1.2.3.4:1080", "https": "socks5h://1.2.3.4:1080"},
    f"parse_proxy 两个键同值、保留 socks5h（{proxies}）",
)
check(parse_proxy("") is None, "空地址 -> None（直连）")
check(
    redact_proxy("http://u:p@ss@1.2.3.4:8080") == "http://u:***@1.2.3.4:8080",
    f"密码打码，且认证段按最后一个 @ 切（{redact_proxy('http://u:p@ss@1.2.3.4:8080')}）",
)
check(redact_proxy("http://1.2.3.4:8080") == "http://1.2.3.4:8080", "无认证段原样返回")
check(redact_proxy("") == "", "空地址不产生噪音")
check(PROXY_PLACEHOLDER.startswith("http://"), f"占位符是个完整地址（{PROXY_PLACEHOLDER}）")

print("== 2. 旧「配代理软件」UI 的遗留 API 已删除 ==")
import app.common.proxy as proxy_mod

dead = [
    "ProxyEnvManager",
    "proxy_env",
    "PROXY_SCHEMES",
    "build_proxy",
    "split_proxy",
    "split_proxy_auth",
    "proxy_scheme",
    "is_socks",
    "pysocks_available",
]
alive = [n for n in dead if hasattr(proxy_mod, n)]
check(not alive, f"proxy.py 只剩地址工具（残留 {alive}）")

print("== 3. 所有 Session 都不吃环境变量 / 系统代理 ==")
# requests 默认 trust_env=True：merge_environment_settings 会读 HTTP_PROXY，
# 读不到就读 Windows 注册表里的系统代理，并且**覆盖** session.proxies
check(requests.Session().trust_env is True, "前提：requests 默认 trust_env=True（所以必须显式关掉）")
check(make_client().session.trust_env is False, "make_client 的 session 关掉了 trust_env")
check(make_emoji()._client.session.trust_env is False, "make_emoji 同理")
check(make_dress()._client.session.trust_env is False, "make_dress 同理")
check(
    make_downloader(max_workers=1)._build_session().trust_env is False,
    "make_downloader 建出来的 worker-local session 同理",
)
check(make_session().trust_env is False, "make_session（检查更新走它）同理")
probe = {"http": "http://1.2.3.4:9", "https": "http://1.2.3.4:9"}
check(
    dict(make_client(proxies=probe).session.proxies) == probe,
    "显式 proxies 确实落到了 session.proxies 上",
)

print("== 4. 代理开关 ==")
cfg.proxy_enabled.value = False
cfg.proxy.value = "http://127.0.0.1:7890"
check(current_proxies() is None, "开关关闭 -> 直连，哪怕地址还留着")
cfg.proxy_enabled.value = True
check(
    current_proxies() == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
    f"开关打开 -> 用配置里的地址（{current_proxies()}）",
)
cfg.proxy.value = ""
check(current_proxies() is None, "开着但地址为空也是直连")

# 应用只走显式 proxies=，绝不写 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
env_before = {
    k: os.environ.get(k)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy")
}
page = SettingPage()
page.resize(900, 700)
page.show()
app.processEvents()
page.proxySwitch.setChecked(True)
page.proxyEdit.setText("127.0.0.1:7890")
page.dirEdit.setText(str(Path(os.environ["APPDATA"]) / "dl"))
# 下载组没有「保存」按钮了：地址框与目录都靠 editingFinished（回车 / 失焦）落库
page.proxyEdit.editingFinished.emit()
page.dirEdit.editingFinished.emit()
app.processEvents()
env_after = {k: os.environ.get(k) for k in env_before}
check(env_before == env_after, f"改代理不写任何代理环境变量（{env_after}）")
check(cfg.proxy.value == "http://127.0.0.1:7890", f"地址被规范化后落库（{cfg.proxy.value!r}）")
check(cfg.proxy_enabled.value is True, "开关状态一并落库")
check(
    page.proxyEdit.text() == "http://127.0.0.1:7890",
    f"规范化结果回填到输入框（{page.proxyEdit.text()!r}）",
)
check(
    cfg.download_dir.value == str(Path(os.environ["APPDATA"]) / "dl"),
    f"下载目录也即时落库（{cfg.download_dir.value!r}）",
)

print("== 5. 设置页取值与校验 ==")
check(hasattr(page, "proxySwitch") and hasattr(page, "proxyEdit"), "代理行 = 开关 + 地址框")
check(hasattr(page, "proxyTestBtn"), "代理卡上有「测试」按钮")
check(
    not hasattr(page, "protoCombo")
    and not hasattr(page, "portSpin")
    and not hasattr(page, "proxyAuthCard"),
    "协议下拉 / 端口 / 认证行都已移除",
)
page.proxySwitch.setChecked(False)
app.processEvents()
check(not page.proxyEdit.isEnabled(), "开关关着 -> 地址框不可编辑（连填都填不了）")
check(not page.proxyTestBtn.isEnabled(), "开关关着 -> 「测试」也禁用")
check(page._current_proxy() == "", "开关关着 -> 取值为空串（不使用代理）")
page.proxySwitch.setChecked(True)
app.processEvents()
check(page.proxyEdit.isEnabled(), "开关打开 -> 地址框恢复可编辑")
page.proxyEdit.setText(" 127.0.0.1:7890 ")
check(
    page._current_proxy() == "http://127.0.0.1:7890",
    f"取值时去空白并补协议（{page._current_proxy()!r}）",
)
page.proxyEdit.setText("http://1.2.3.4 :8080")
check(page._current_proxy() is None, "地址里有空格被拦下")
page.proxyEdit.setText("")
check(page._current_proxy() is None, "开着开关却没填地址被拦下（不会静默存成直连）")
check("系统代理" in page.proxyCard.toolTip(), "tooltip 点明应用不读系统代理")
check(PROBE_URL in page.proxyCard.toolTip(), f"tooltip 写明测试打哪个接口（{PROBE_URL}）")

print("== 5b. 即时生效：下载组没有「保存」按钮 ==")
# 真实踩过的坑：在框里换了 IP、按了「测试」，但没点保存 → 其它请求还在用旧地址，
# 报错里显示的又是配置里那个旧值，看起来像「代理没接进请求」。
# 现在整个下载组都是即时落库（代理开关 / 地址框 / 下载目录 / 线程数），没有保存按钮。
qconfig.set(cfg.proxy, "http://old.example:1")
page.proxySwitch.setChecked(True)
page.proxyEdit.setText("new.example:8888")
page.proxyEdit.editingFinished.emit()  # = 回车 / 焦点移开
app.processEvents()
check(
    cfg.proxy.value == "http://new.example:8888",
    f"地址框失焦即落库，无需点保存（{cfg.proxy.value!r}）",
)
check(
    current_proxies() == {"http": "http://new.example:8888", "https": "http://new.example:8888"},
    "新地址立刻对所有联网入口生效",
)
check(
    page.proxyEdit.text() == "http://new.example:8888",
    f"顺手回填规范化后的地址（{page.proxyEdit.text()!r}）",
)
check("new.example:8888" in page.proxyCard.contentLabel.text(),
      f"副标题显示当前生效的代理（{page.proxyCard.contentLabel.text()!r}）")
page.proxySwitch.setChecked(False)
app.processEvents()
check(cfg.proxy_enabled.value is False, "开关一拨就落库")
check(current_proxies() is None, "关掉开关立刻直连")
check("直连" in page.proxyCard.contentLabel.text(),
      f"副标题改说直连（{page.proxyCard.contentLabel.text()!r}）")

# 清空地址框后失焦要**真的把地址从配置里清掉**——「界面看着是空的、文件里还留着
# 老地址」正是代理开关被自动置开那类问题的源头（见 config.py::_migrate 的说明）
page.proxyEdit.setText("")
page.proxyEdit.editingFinished.emit()
app.processEvents()
check(cfg.proxy.value == "", f"清空地址框后失焦 → 配置里也清掉（{cfg.proxy.value!r}）")

page.proxySwitch.setChecked(True)
app.processEvents()
# 密码只在副标题里打码，配置里存的仍是可用的完整地址
qconfig.set(cfg.proxy, "http://u:secret@1.2.3.4:8080")
page._refresh_proxy_content()
check(
    ":***@" in page.proxyCard.contentLabel.text()
    and "secret" not in page.proxyCard.contentLabel.text(),
    f"副标题里的密码打码（{page.proxyCard.contentLabel.text()!r}）",
)

print("== 5c. 「测试」失败提示报的是被测地址与接口，不是配置里的值 ==")
# 通用 show_bili_error 报的是「网络错误 + cfg.proxy」，测试要报「你刚填的那个 + 打了哪个接口」
cfg.proxy.value = "http://saved.example:1"  # 配置里是另一个值，故意与被测值不同
bars: list[tuple] = []
import app.view.setting_page as setting_page_mod

setting_page_mod.notify_error = lambda title, content, **kw: bars.append((title, content, kw))
page._probed_proxy = "http://u:p@18.162.158.218:80"
page._on_proxy_failed(
    wrapped(requests.exceptions.ProxyError("Tunnel connection failed: 400 Bad Request"))
)
check(len(bars) == 1, f"失败弹一条提示（实际 {len(bars)}）")
title, content, kwargs = bars[0] if bars else ("", "", {})
check(title == "代理测试失败", f"标题点明是测试失败而不是「网络错误」（实际 {title!r}）")
check("18.162.158.218:80" in content, "正文回显被测地址")
check("saved.example" not in content, "不报配置里那个未被测试的地址")
check(":***@" in content, f"被测地址里的密码打码（{content.splitlines()[-2]!r}）")
check(PROBE_URL in content, "正文写明打的是哪个接口")
check("CONNECT" in content, "正文仍带 cause_hint 的因果")
# 上游 InfoBar.showEvent: `if self.duration >= 0: singleShot(duration, fadeOut)`，
# 所以「不自动消失」是负数；写 0 会在下一轮事件循环立刻淡出（一闪而过，真踩过）
check(
    kwargs.get("duration", 0) < 0,
    f"诊断提示不自动消失（duration={kwargs.get('duration')!r}，0 会立刻淡出）",
)
check(NEVER_DISMISS < 0, f"NEVER_DISMISS 是负数（{NEVER_DISMISS}）")
page.close()
cfg.proxy.value = ""


print("== 6. 因果翻译 ==")
cases = [
    (
        requests.exceptions.ProxyError(
            "Unable to connect to proxy: Tunnel connection failed: "
            "407 Proxy Authentication Required"
        ),
        "认证",
    ),
    (
        requests.exceptions.ProxyError(
            "Cannot connect to proxy. NewConnectionError: [WinError 10061] "
            "由于目标计算机积极拒绝，无法连接。"
        ),
        "连不上代理服务器",
    ),
    (
        requests.exceptions.ProxyError(
            "HTTPSConnectionPool(host='api.bilibili.com', port=443): "
            "Max retries exceeded (Caused by ProxyError('Unable to connect to proxy', "
            "OSError('Tunnel connection failed: 400 Bad Request')))"
        ),
        "CONNECT",
    ),
    (requests.exceptions.InvalidSchema("No connection adapters"), "格式"),
    (requests.exceptions.ConnectTimeout("timed out"), "超时"),
    (requests.exceptions.SSLError("certificate verify failed"), "TLS"),
]
for inner, keyword in cases:
    hint = cause_hint(wrapped(inner))
    check(
        keyword in hint,
        f"{type(inner).__name__} → 提示含「{keyword}」（实际：{hint[:36]}…）",
    )
check(cause_hint(ValueError("随便什么")) == "", "认不出来的异常返回空串，不硬编中文")
# 断言链路真的走到了 __cause__：外层消息本身不含这些关键字
outer = wrapped(cases[1][0])
check(
    "ProxyError" in str(outer) and "10061" not in str(outer),
    "外层 NetworkError 消息本身没有原因，确实是从 __cause__ 挖出来的",
)

cfg.proxy_enabled.value = False
cfg.proxy.value = ""

# ---------------------------------------------------------------- 7. 配置默认值
print("\n[7] 配置：代理一律默认关 + 布尔项的非法值不会变「开」")

# 迁移在 import app.common.config 时就跑完了，只能开子进程按不同的初始文件重来。
_PROBE = (
    "import json;"
    "from app.common.config import cfg, CONFIG_FILE;"
    "raw = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))"
    " if CONFIG_FILE.is_file() else {};"
    "print('RESULT', json.dumps({"
    "'mem': cfg.proxy_enabled.value,"
    "'disk': raw.get('Download', {}).get('proxyEnabled'),"
    "'schema': cfg.schema_version.value,"
    "'gif': cfg.default_gif.value,"
    "'auto': cfg.auto_check_update.value,"
    "'proxy': cfg.proxy.value,"
    "'hasFile': CONFIG_FILE.is_file(),"
    "}))"
)
_OLD_ADDRESS = "http://127.0.0.1:7890"


def _boot(raw: dict | None, *, with_file: bool = True) -> dict:
    """按给定的 config.json 内容起一次配置模块，返回结果字典。

    `with_file=False` 连文件都不写，用来验「真·全新安装」那条路径。
    子进程崩了不抛异常，而是返回 `{"crash": stderr 尾巴}`——断言会看到缺键。
    """
    home = Path(tempfile.mkdtemp(prefix="biliEmojiDD-migrate-")) / "biliEmojiDD"
    home.mkdir(parents=True)
    if with_file:
        (home / "config.json").write_text(json.dumps(raw), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        check=False,
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, "APPDATA": str(home.parent), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for line in result.stdout.splitlines():
        if line.startswith("RESULT"):
            return json.loads(line.split(" ", 1)[1])
    return {"crash": (result.stderr or "")[-200:]}


# 真·全新安装：家目录里连 config.json 都没有（这条路径以前从没被测过，
# 而「默认关」恰恰依赖它）
fresh = _boot(None, with_file=False)
check(fresh.get("mem") is False, f"完全没有 config.json → 代理关（{fresh}）")
check(fresh.get("disk") is False, "全新安装落盘的也是 false")
check(fresh.get("hasFile") is True, "首次启动会把全量配置写进文件（_ensure_persisted）")

# 老配置（有地址、没有 proxyEnabled 键）：**不再**被自动置开——这是本次修的根因
old = _boot({"Download": {"proxy": _OLD_ADDRESS}})
check(
    old.get("mem") is False,
    f"老配置里有代理地址也不再自动置开（迁移已删，得到 {old.get('mem')!r}）",
)
check(old.get("disk") is False, "落盘同样是关")
check(old.get("proxy") == _OLD_ADDRESS, "地址本身保留（要用时拨一下开关就行）")
check(old.get("schema") == 1, "schema 熄火标记仍会就位（以后加迁移还得靠它）")

# 用户关掉的开关，重启后仍是关的
kept = _boot(
    {"App": {"schema": 1}, "Download": {"proxy": _OLD_ADDRESS, "proxyEnabled": False}}
)
check(kept.get("mem") is False, "用户关掉的开关，重启后仍是关的")

# 非法值不再被兜成 True：上游 BoolValidator = OptionsValidator([True, False])，
# 它的 correct() 回落 options[0]，也就是**永远 True**
for bad in ("false", None, "True", 0):
    got = _boot({"Download": {"proxy": _OLD_ADDRESS, "proxyEnabled": bad}})
    check(
        got.get("mem") is False,
        f"proxyEnabled 写成 {bad!r} → 读成关（得到 {got.get('mem')!r}）",
    )
    check(got.get("disk") is False, f"非法值在固化前就被纠正成 false（{bad!r}）")

# 默认 True 的两项：非法值回落它们**自己的默认值**，行为不变
defaults = _boot({"Update": {"autoCheck": "false"}, "Download": {"gif": "no"}})
check(defaults.get("auto") is True, "autoCheck 写成 'false' 仍回落它的默认值 True（行为不变）")
check(defaults.get("gif") is True, "gif 写成 'no' 回落它的默认值 True（行为不变）")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
