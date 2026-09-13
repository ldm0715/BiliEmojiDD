"""屏幕外验证 Cookie 有效性状态（`app/components/cookie_status.py`）。

**不联网**：把 `cookie_status.run_task` 换成同步桩、`fetch_account` 换成假的，
「有没有发请求」的判据就是桩被叫了几次。

1. 五态映射：没有 Cookie / 有效 / 失效 / **网络失败不写记录、不判失效**；
2. 信任期：有效 7 天、失效 30 分钟，含边界，期内进主页零请求；
3. 指纹作废：换 Cookie → 未验证；重填同一个 Cookie 靠 invalidate；迟到回调不写错人；
4. 不叠任务：探针在飞时再调 `ensure_checked` 也只起一个；失败后 `_inflight` 要清；
5. `set_enabled(False)` 一个任务都不提交；
6. 预拉取：页面层幂等 + 命中缓存零请求 + 失败后按钮与标志都恢复；
7. 接线层：记录新鲜 + 主页显示 → `MainWindow` 自动预拉取一次，且**不切页**；
8. 表情包页标签顺序（全部表情包在前且默认）。

用法：QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_cookie_status.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 隔离配置目录：APP_CONFIG_DIR 在 import 时按 APPDATA 计算，必须早于 app.* 的导入，
# 否则会写脏用户真实的 config.json
_SANDBOX = tempfile.mkdtemp(prefix="biliEmojiDD-cookie-")
os.environ["APPDATA"] = _SANDBOX

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from biliemoji import AuthRequired
from qfluentwidgets import Theme, qconfig, setTheme

from app.common.config import APP_CONFIG_DIR, cfg
from app.common.signal_bus import signal_bus
from app.components import bili_login as bl
from app.components import cookie_status
from app.components.cache import cookie_fingerprint
from app.components.content_meta import content_meta
from app.components.video_cache import video_cache
from app.view.emoji_page import EmojiPage

setTheme(Theme.LIGHT)
content_meta.set_enabled(False)  # 假数据会排一堆 15s 超时请求把脚本挂住
video_cache.set_enabled(False)

_ALL_PACKAGES_FILE = APP_CONFIG_DIR / "all_packages.json"  # cache.py 的落盘位置
_TRUST_VALID = cookie_status._TRUST_VALID_SECONDS
_TRUST_INVALID = cookie_status._TRUST_INVALID_SECONDS

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def pump(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


class _Collector:
    """收集 cookieStateChanged 的载荷。

    不能用 `list.append` 直接当槽：每次 `seen.append` 都是一个新对象，
    `disconnect` 未必认得出来。用一个稳定对象，连、断都传它。
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, state: str) -> None:
        self.seen.append(state)


def collect_states() -> _Collector:
    box = _Collector()
    signal_bus.cookieStateChanged.connect(box)
    return box


def stop_collecting(box: _Collector) -> None:
    signal_bus.cookieStateChanged.disconnect(box)


class _Emote:
    text = "表情"
    url = ""
    gif_url = ""


class _Pkg:
    """最小可用的假表情包（PackageCard 读 text / id / emote / url）。"""

    def __init__(self, pid: int) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = [_Emote()]
        self.url = ""


PKGS = [_Pkg(1), _Pkg(2)]


def sync_run_task():
    """同步 `run_task` 桩：立刻执行 fn 并按真实顺序回调。

    **必须回调 `on_finished`** —— 它才是清 `_inflight` / `_loading` 的地方，
    不调的话后续断言全会卡在「正在检测」上。
    """
    calls: list[int] = []

    def fake(fn, *args, on_success=None, on_error=None, on_finished=None, **kwargs):
        calls.append(1)
        try:
            res = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 假装成任务失败
            if on_error is not None:
                on_error(exc)
            ok = False
        else:
            if on_success is not None:
                on_success(res)
            ok = True
        if on_finished is not None:
            on_finished(ok)

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def set_at(seconds_ago: float) -> None:
    qconfig.set(cfg.cookie_checked_at, int(time.time() - seconds_ago))


def record() -> tuple:
    return (
        cfg.cookie_checked_at.value,
        cfg.cookie_checked_hash.value,
        cfg.cookie_checked_state.value,
    )


# 探针与任务全部换成假的：本脚本一个请求都不发
probe_result: list = []  # 空 = 返回 Account；[None] = 没登录；["raise"] = 抛异常
probe_calls: list[int] = []


def fake_fetch_account(cookie: str, *, proxies=None):
    probe_calls.append(1)
    if probe_result and probe_result[0] == "raise":
        raise bl.LoginFailed("网络炸了")
    return bl.Account(mid=1, name="测试账号", face="") if not probe_result else None


cookie_status.fetch_account = fake_fetch_account
cookie_status.run_task = sync_run_task()
cookie_status.set_enabled(True)

# ---------------------------------------------------------------- 1. 五态映射
print("\n[1] 五态映射")
qconfig.set(cfg.cookie, "")
cookie_status.invalidate()
check(cookie_status.known_state() == cookie_status.NO_COOKIE, "没填 Cookie → no_cookie")
check(cookie_status.current_state() == cookie_status.NO_COOKIE, "current_state 同口径")
calls = cookie_status.run_task.calls
calls.clear()
cookie_status.ensure_checked()
check(calls == [], "没填 Cookie 时一个任务都不起（没什么可探的）")
check(probe_calls == [], "连探针都没调")

qconfig.set(cfg.cookie, "SESSDATA=abc")
check(cookie_status.known_state() == cookie_status.UNKNOWN, "有 Cookie 但没记录 → unknown")

probe_result.clear()
probe_calls.clear()
calls.clear()
box = collect_states()
cookie_status.ensure_checked()
stop_collecting(box)
check(calls == [1], f"unknown → 起一次探针（起了 {len(calls)} 次）")
check(
    box.seen == [cookie_status.CHECKING, cookie_status.CHECKING, cookie_status.VALID],
    f"过程中广播 checking → valid（得到 {box.seen}）",
)
check(cookie_status.known_state() == cookie_status.VALID, "探针返回账号 → valid")
check(cfg.cookie_checked_state.value == cookie_status.VALID, "结论落盘（重启用）")
check(cfg.cookie_checked_hash.value == cookie_fingerprint("SESSDATA=abc"), "指纹落盘")

probe_result[:] = [None]  # 探针返回 None = B 站明确说没登录
cookie_status.invalidate()
cookie_status.ensure_checked()
check(cookie_status.known_state() == cookie_status.INVALID, "探针返回 None → invalid")
check(cfg.cookie_checked_state.value == cookie_status.INVALID, "失效也落盘（红灯要能跨启动）")

probe_result[:] = ["raise"]  # 网络失败
cookie_status.invalidate()
probe_calls.clear()
box = collect_states()
cookie_status.ensure_checked()
stop_collecting(box)
check(probe_calls == [1], "网络失败也真的试了一次")
check(
    cookie_status.known_state() == cookie_status.UNKNOWN,
    "网络失败 → unknown（网络不通不该把灯变红）",
)
check(record() == (0, "", ""), f"网络失败不写记录（得到 {record()}）")
check(
    cookie_status.current_state() != cookie_status.CHECKING,
    "收尾后不再是「正在检测」",
)

# ---------------------------------------------------------------- 2. 信任期
print("\n[2] 信任期：有效 7 天 / 失效 30 分钟")
probe_result.clear()
qconfig.set(cfg.cookie, "SESSDATA=abc")
cookie_status.note(cookie_status.VALID, "SESSDATA=abc")

check(_TRUST_VALID == 7 * 24 * 3600, f"有效信任期是 7 天（{_TRUST_VALID}s）")
check(_TRUST_INVALID == 30 * 60, f"失效信任期是 30 分钟（{_TRUST_INVALID}s）")

for ago, expect in (
    (6 * 24 * 3600, cookie_status.VALID),  # 第 6 天
    (_TRUST_VALID - 60, cookie_status.VALID),  # 差一分钟到期
    (_TRUST_VALID + 60, cookie_status.UNKNOWN),  # 刚过期
    (8 * 24 * 3600, cookie_status.UNKNOWN),  # 第 8 天
):
    set_at(ago)
    check(
        cookie_status.known_state() == expect,
        f"有效记录距今 {ago / 3600:.1f} 小时 → {expect}",
    )

# 期内不联网 = 「不要一直检测」；过了期才重新探
set_at(_TRUST_VALID - 60)
calls = cookie_status.run_task.calls
calls.clear()
cookie_status.ensure_checked()
check(calls == [], "信任期内进主页：零请求（不一直检测就靠这条）")
set_at(_TRUST_VALID + 60)
calls.clear()
cookie_status.ensure_checked()
check(calls == [1], "过了信任期：重新探一次")

cookie_status.note(cookie_status.INVALID, "SESSDATA=abc")
for ago, expect in (
    (29 * 60, cookie_status.INVALID),
    (31 * 60, cookie_status.UNKNOWN),
):
    set_at(ago)
    check(
        cookie_status.known_state() == expect,
        f"失效记录距今 {ago / 60:.0f} 分钟 → {expect}（弱事实只信半小时）",
    )

# ---------------------------------------------------------------- 3. 指纹作废
print("\n[3] 指纹作废 / 迟到回调")
qconfig.set(cfg.cookie, "SESSDATA=a")
cookie_status.note(cookie_status.VALID, "SESSDATA=a")
set_at(60)
check(cookie_status.known_state() == cookie_status.VALID, "有效记录 + 同一个 Cookie → valid")

qconfig.set(cfg.cookie, "SESSDATA=b")
check(cookie_status.known_state() == cookie_status.UNKNOWN, "换成别的 Cookie → unknown（不认旧记录）")

cookie_status.note(cookie_status.VALID, "SESSDATA=a")  # 迟到回调：快照是旧 Cookie
check(
    cfg.cookie_checked_hash.value != cookie_fingerprint("SESSDATA=b"),
    "迟到回调不会把结论写到当前 Cookie 头上",
)
check(cookie_status.known_state() == cookie_status.UNKNOWN, "状态仍是 unknown")

qconfig.set(cfg.cookie, "SESSDATA=a")
check(
    cookie_status.known_state() == cookie_status.VALID,
    "换回去时那条记录还在信任期内 → 又认可它（指纹机制按 Cookie 各论各的）",
)
# 真实路径不依赖上面那条：_apply_cookie 无条件 invalidate（重填 = 重新验证）
cookie_status.invalidate()
check(record() == (0, "", ""), f"invalidate 清空三项（得到 {record()}）")
check(
    cookie_status.known_state() == cookie_status.UNKNOWN,
    "重填同一个 Cookie：靠 invalidate 作废，不会被指纹相同的旧记录挡住",
)

qconfig.set(cfg.cookie, "SESSDATA=a")
cookie_status.note(cookie_status.UNKNOWN, "SESSDATA=a")
check(record() == (0, "", ""), "note(unknown) 不落盘——那是「不知道」，不是结论")

# ---------------------------------------------------------------- 4. 不叠任务
print("\n[4] 不叠任务 / 失败后不卡死")
qconfig.set(cfg.cookie, "SESSDATA=abc")
cookie_status.invalidate()
cookie_status.set_enabled(True)
hanging: list[dict] = []
hang_calls: list[int] = []


def hanging_run_task(fn, *args, on_success=None, on_error=None, on_finished=None, **kw):
    hang_calls.append(1)
    hanging.append(
        {"fn": fn, "ok": on_success, "err": on_error, "done": on_finished, "args": args}
    )


cookie_status.run_task = hanging_run_task
probe_result.clear()
cookie_status.ensure_checked()
check(len(hang_calls) == 1, "第一次起了一个探针")
check(cookie_status.current_state() == cookie_status.CHECKING, "在飞时界面显示「正在检测」")
cookie_status.ensure_checked()  # 切走又切回来
check(len(hang_calls) == 1, "探针还在飞时再进主页不再叠一个（切页来回会反复触发）")

pending = hanging.pop()
pending["ok"](bl.Account(mid=1, name="n", face=""))
pending["done"](True)
check(cookie_status.known_state() == cookie_status.VALID, "回调落地后拿到结论")
check(cookie_status.current_state() == cookie_status.VALID, "不再是「正在检测」")

# 失败路径也要清 _inflight（只在成功路径清会让探针永远不再重试）
cookie_status.invalidate()
cookie_status.ensure_checked()
pending = hanging.pop()
pending["err"](bl.LoginFailed("boom"))
pending["done"](False)
check(cookie_status.current_state() == cookie_status.UNKNOWN, "失败后回到 unknown（没卡在 checking）")
cookie_status.ensure_checked()
check(len(hang_calls) == 3, f"失败后还能重新探（累计 {len(hang_calls)} 次）")
hanging.pop()["done"](False)  # 收掉在飞的那个，别留着
cookie_status.run_task = sync_run_task()

# ---------------------------------------------------------------- 5. 关联网
print("\n[5] set_enabled(False) 一个任务都不提交")
cookie_status.set_enabled(False)
cookie_status.invalidate()
calls = cookie_status.run_task.calls
calls.clear()
cookie_status.ensure_checked()
check(calls == [], "关掉后 ensure_checked 不提交任务（不是提交了再抛异常）")
check(cookie_status.known_state() == cookie_status.UNKNOWN, "关联网不影响状态推断")
cookie_status.set_enabled(True)

# ---------------------------------------------------------------- 6. 预拉取
print("\n[6] 预拉取：幂等 + 命中缓存零请求 + 失败后恢复")
from app.view import emoji_page as emoji_mod

emoji = EmojiPage()
emoji.resize(900, 700)
allTab = emoji.allTab
emu_calls: list[int] = []


def emu_ok(fn, *args, on_success=None, on_error=None, on_finished=None, **kw):
    emu_calls.append(1)
    if on_success is not None:
        on_success(PKGS)
    if on_finished is not None:
        on_finished(True)


qconfig.set(cfg.cookie, "SESSDATA=abc")
cookie_status.invalidate()
_ALL_PACKAGES_FILE.unlink(missing_ok=True)
emoji_mod.run_task = emu_ok
check(allTab._all == (), "构造后没有数据（进页面不自动拉）")
emoji.ensure_all_packages()
check(emu_calls == [1], f"第一次预拉取真的拉了一次（{len(emu_calls)} 次）")
check(allTab._all == tuple(PKGS), "数据已就位，用户进这页时列表已就绪")
check(not allTab._loading, "拉完 _loading 归位")
check(allTab.fetchBtn.isEnabled() and allTab.refreshBtn.isEnabled(), "拉完两个按钮都可用")
emoji.ensure_all_packages()
check(emu_calls == [1], "已有数据 → 再叫也不拉（每次进主页都会被叫一次）")

# 缓存命中：把读缓存换成「一定命中」，这次应该一个请求都不发。
# （不指望真走一遍 save/load 往返：假包没有 .raw，写盘会静默失败；
#   缓存本身的往返由 scripts/check_search_cache.py 用真模型覆盖。）
_real_load = emoji_mod.load_all_packages_cache
emoji_mod.load_all_packages_cache = lambda _cookie: tuple(PKGS)
allTab._all = ()
cookie_status.invalidate()
emoji.ensure_all_packages()
emoji_mod.load_all_packages_cache = _real_load
check(emu_calls == [1], "24 小时缓存命中 → 静默路径零请求")
check(allTab._all == tuple(PKGS), "命中缓存时数据同样就位")

# 失败路径：_loading 必须清（否则预拉取永远不再重试），按钮按状态恢复
_ALL_PACKAGES_FILE.unlink(missing_ok=True)


def emu_fail(fn, *args, on_success=None, on_error=None, on_finished=None, **kw):
    emu_calls.append(1)
    if on_error is not None:
        on_error(AuthRequired("nope"))
    if on_finished is not None:
        on_finished(False)


emoji_mod.run_task = emu_fail
allTab._all = ()
allTab._loading = False
cookie_status.invalidate()
set_at(0)
cookie_status.note(cookie_status.VALID, "SESSDATA=abc")
emoji.ensure_all_packages()
check(not allTab._loading, "失败后 _loading 清掉了（不然预拉取再也不重试）")
check(allTab.fetchBtn.isEnabled(), "失败后「拉取全部表情包」恢复可点")
check(not allTab.refreshBtn.isEnabled(), "失败后「强制刷新」保持禁用（还没有数据可刷）")
check(
    record() == (0, "", ""),
    f"AuthRequired 只作废记录、不直接判红（得到 {record()}）",
)

# ---------------------------------------------------------------- 7. 接线层
print("\n[7] MainWindow 接线：有效 → 自动预拉取一次且不切页")
from app.components import updater

content_meta.set_enabled(False)
video_cache.set_enabled(False)
updater.set_enabled(False)  # 启动 3 秒后的自动检查会真发网络请求

from app.MainWindow import MainWindow

cookie_status.set_enabled(True)
qconfig.set(cfg.cookie, "SESSDATA=abc")
cookie_status.invalidate()
set_at(0)
cookie_status.note(cookie_status.VALID, "SESSDATA=abc")  # 新鲜记录：showEvent 不会联网
calls = cookie_status.run_task.calls
calls.clear()
prefetches: list[int] = []

window = MainWindow()
window.emojiPage.ensure_all_packages = lambda: prefetches.append(1)  # 记下被叫了几次
window.show()
pump(20)
check(calls == [], "记录新鲜 → 主页显示时零请求（信任期在应用层也生效）")
check(prefetches == [1], f"Cookie 有效 → 自动预拉取一次（{len(prefetches)} 次）")
check(
    window.stackedWidget.currentWidget() is window.homePage,
    "预拉取不切页（用户仍停在主页）",
)
signal_bus.cookieStateChanged.emit(cookie_status.UNKNOWN)
signal_bus.cookieStateChanged.emit(cookie_status.INVALID)
pump()
check(prefetches == [1], "非 valid 的状态不会触发预拉取")

# 迟到回调：探针回来时已经登出 → 不该拿旧结论去发请求
cookie_status.invalidate()
prefetches.clear()
signal_bus.cookieStateChanged.emit(cookie_status.VALID)  # 记录已被作废
pump()
check(prefetches == [], "记录被作废后，迟到的 valid 信号不会触发预拉取")

window.close()
pump()

# ---------------------------------------------------------------- 8. 标签顺序
print("\n[8] 表情包页标签顺序与默认页")
check(
    list(emoji.pivot.items) == ["all", "byId", "live"],
    f"「全部表情包」在「按 ID 查询」「直播间表情」之前（得到 {list(emoji.pivot.items)}）",
)
check(emoji.stackedWidget.indexOf(emoji.allTab) == 0, "栈里 allTab 在第 0 位")
check(emoji.stackedWidget.currentWidget() is emoji.allTab, "默认停在「全部表情包」")
check(emoji.pivot.currentItem() is emoji.pivot.widget("all"), "Pivot 指示条同步")
emoji.query_package_id("53")
check(emoji.stackedWidget.currentWidget() is emoji.idTab, "按 ID 查询仍能切过去")
check(emoji.pivot.currentItem() is emoji.pivot.widget("byId"), "指示条跟着走")
emoji.close()
pump()

# ---------------------------------------------------------------- 收尾
print()
if FAILS:
    print(f"{len(FAILS)} 项失败：")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("全部通过")
