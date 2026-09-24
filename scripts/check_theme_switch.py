"""屏幕外验证主题切换：

1. 侧栏主题按钮点一次只切一次（曾因 clicked 被 connect 两遍，切了又切回等于没切）；
2. 设置页主题下拉闭合态显示图标，且图标随主题重新取色；
3. 网格容器（表情包 / 收藏集 / 详情 / 队列）随主题重刷 QSS；
4. 切换性能：QSS 文本按路径缓存（读文件次数不随控件数增长）+ 未绘制控件延后补刷。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA：设置页下拉切主题会真的写 cfg.theme，
# 不隔离就把用户真实的 config.json 改脏了
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from qfluentwidgets import Theme, setTheme
from qfluentwidgets.common import style_sheet as qss_mod
from qfluentwidgets.common.style_sheet import getStyleSheet, styleSheetManager

from app.common import theme as app_theme
from app.common.theme import is_dark
from app.components.widgets import PackageGrid

setTheme(Theme.LIGHT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 4) -> None:
    for _ in range(rounds):
        app.processEvents()


def wait_until(cond, timeout: float = 2.0) -> bool:
    """等属性动画 / 异步状态——光 processEvents 不推进时钟。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            break
        settle(2)
        time.sleep(0.01)
    settle(2)
    return bool(cond())


print("== 1. 侧栏主题按钮：点一次切一次 ==")
from app.components import cookie_status, updater

updater.set_enabled(False)  # MainWindow 启动后会静默查一次新版本
cookie_status.set_enabled(False)  # 主页 showEvent 会触发一次 Cookie 检测

from app.MainWindow import MainWindow

win = MainWindow()
win.show()
app.processEvents()

before = is_dark()
win.themeNavBtn.click()
app.processEvents()
check(is_dark() != before, f"点一次后主题翻转（{before} -> {is_dark()}）")
win.themeNavBtn.click()
app.processEvents()
check(is_dark() == before, f"再点一次翻回原主题（当前 {is_dark()}）")

# 直接数 clicked 的接收方个数：重复 connect 会让一次点击跑两遍 _toggle_theme
calls = []
win.themeNavBtn.clicked.connect(lambda *_: calls.append(1))
win.themeNavBtn.click()
app.processEvents()
check(len(calls) == 1, f"clicked 每次点击只发一次（实际 {len(calls)}）")

print("== 2. 设置页主题下拉：闭合态显示图标且随主题换色 ==")
sp = win.settingPage
check(sp.themeCombo.count() == 3, f"主题下拉三项（实际 {sp.themeCombo.count()}）")
check(not sp.themeCombo.icon().isNull(), "闭合态图标非空（ComboBox 自身只 setText 不 setIcon）")

# 一律经下拉切换：_on_theme_changed 会同时 setTheme + 写 cfg.theme，
# 直接调 setTheme 会让「生效主题」与 cfg.theme 脱节，后面的同步断言就不成立了
sp.themeCombo.setCurrentIndex(1)  # 浅色
app.processEvents()
check(not is_dark(), "下拉切到浅色已生效")
light_key = sp.themeCombo.icon().cacheKey()

sp.themeCombo.setCurrentIndex(2)  # 深色
app.processEvents()
check(is_dark(), "下拉切到深色已生效")
check(not sp.themeCombo.icon().isNull(), "切深色后闭合态图标仍非空")
check(
    sp.themeCombo.icon().cacheKey() != light_key,
    "切深色后图标已重新取色（FluentIcon 按调用瞬间主题取黑/白 svg）",
)

# 侧栏切主题 -> configChanged -> _sync_theme_combo（blockSignals 内需手动补图标）
win.themeNavBtn.click()  # 深色 -> 浅色
app.processEvents()
check(not is_dark(), "侧栏按钮把主题切回浅色")
check(
    sp.themeCombo.currentIndex() == 1,
    f"侧栏切换后下拉同步到浅色（实际 {sp.themeCombo.currentIndex()}）",
)
check(
    not sp.themeCombo.icon().isNull(),
    "_sync_theme_combo 的 blockSignals 块内也补上了图标",
)

print("== 3. 网格容器随主题重刷 QSS ==")
setTheme(Theme.LIGHT)
grid = PackageGrid()
grid.resize(800, 400)
grid.show()
app.processEvents()
light_qss = grid.styleSheet()
check(bool(light_qss.strip()), "网格已注册组件库 QSS（裸 QListWidget 拿不到任何 QSS）")
setTheme(Theme.DARK)
app.processEvents()
dark_qss = grid.styleSheet()
check(dark_qss != light_qss, "切主题后网格 QSS 已重刷（容器背景随主题变化）")
setTheme(Theme.LIGHT)
app.processEvents()
check(grid.styleSheet() != dark_qss, "切回浅色后网格 QSS 再次重刷")

print("== 4. 主题切换的性能 ==")

# 4.1 缓存补丁幂等：重复安装不能套第二层
content_before = qss_mod.StyleSheetBase.content
app_theme._patch_qss_content_cache()
check(
    qss_mod.StyleSheetBase.content is content_before,
    "重复安装 QSS 缓存补丁是幂等的（没套第二层）",
)

# 4.2 往表情包网格塞 100 张假卡，再数「重刷了几个控件」「读了几次 QSS 文件」
urls = [f"https://x.invalid/perf{i}.png" for i in range(100)]
thumb = QPixmap(64, 64)
thumb.fill(QColor("#3a7bd5"))
for url in urls:
    # 不预置的话每个 URL 会排一个 15s 超时任务，脚本退不出去
    QPixmapCache.insert(url, thumb)

win.switchTo(win.emojiPage)
wait_until(lambda: win._slide_overlay is None)
grid300 = max(win.findChildren(PackageGrid), key=lambda g: g.count(), default=None)
grid300.set_packages([
    SimpleNamespace(id=i, text=f"包{i}", emote=(), meta=None, url=urls[i], is_gif=False)
    for i in range(100)
])
settle()
check(grid300.count() == 100, f"假卡已注入（{grid300.count()} 张）")

registered = len(styleSheetManager.widgets)
real_set_qss = qss_mod.setStyleSheet
calls: list[int] = []


def counted(widget, source, theme=Theme.AUTO, register=True):
    calls.append(1)
    return real_set_qss(widget, source, theme, register)


def timed_switch(theme, lazy: bool) -> float:
    """量一次切换，返回毫秒；`calls` 里攒的是这次的 setStyleSheet 次数。"""
    calls.clear()
    qss_mod.setStyleSheet = counted
    try:
        started = time.perf_counter()
        setTheme(theme, lazy=lazy)
        return (time.perf_counter() - started) * 1000
    finally:
        qss_mod.setStyleSheet = real_set_qss


# 全量切换（不 lazy）：每个注册控件都要刷到，但 QSS 文件按路径缓存后只读几次
app_theme._qss_content_cache.cache_clear()  # 清空才好量「到底读了几次文件」
info_before = app_theme._qss_content_cache.cache_info()
full_ms = timed_switch(Theme.DARK, lazy=False)
info_after = app_theme._qss_content_cache.cache_info()
full_calls = len(calls)
reads = info_after.misses - info_before.misses
check(
    full_calls >= registered,
    f"全量切换把 {registered} 个注册控件都刷了一遍（实际 {full_calls} 次）",
)
check(
    0 < reads <= 40,
    f"{full_calls} 次重刷只读了 {reads} 次 QSS 文件——按路径缓存，不随控件数增长",
)

# 延后切换（lazy）：没在画的控件留到它下次绘制
lazy_ms = timed_switch(Theme.LIGHT, lazy=True)
check(
    len(calls) < registered // 4,
    f"lazy 只当场刷了 {len(calls)}/{registered} 个控件（没在画的不当场刷）",
)
print(
    f"  ---- 参考值：全量 {full_ms:.0f} ms / lazy {lazy_ms:.0f} ms"
    f"（{registered} 个注册控件）"
)

# 4.3 延后补刷不丢正确性：隐藏的控件下次绘制时就换成新主题那份
deferred = PackageGrid()
deferred.resize(600, 400)
deferred.show()  # 先显示一次拿到正确几何，再藏起来当「没在画」的控件
settle()
deferred.hide()
settle()
light_qss = deferred.styleSheet()
setTheme(Theme.DARK, lazy=True)
check(deferred.property("dirty-qss") is True, "隐藏控件被标脏，不当场重刷")
check(deferred.styleSheet() == light_qss, "隐藏控件此刻仍留着旧主题的 QSS")
deferred.show()
settle()
check(deferred.property("dirty-qss") is False, "它下一次绘制时脏标记被清掉")
check(
    deferred.styleSheet() == getStyleSheet(styleSheetManager.source(deferred), Theme.DARK),
    "补刷用的正是暗色那份 QSS（延后不丢正确性）",
)
deferred.hide()

# 4.4 快照是「渲染」出来的，渲到谁就把谁补刷掉（所以不必额外整页补刷）
# （这条是 4.5 那个底色断言的前提：控件本身也必须是当前主题）
def count_dirty(root) -> int:
    return sum(
        1 for w in [root, *root.findChildren(QWidget)]
        if w in styleSheetManager.widgets and w.property("dirty-qss")
    )


win.switchTo(win.homePage)
wait_until(lambda: win._slide_overlay is None)
setTheme(Theme.LIGHT, lazy=True)  # 主页可见立刻刷；设置页留着脏
settle()
dirty_before = count_dirty(win.settingPage)
check(dirty_before > 0, f"设置页留着 {dirty_before} 个被 lazy 推迟的控件（前提成立）")
started = time.perf_counter()
win.switchTo(win.settingPage)  # 内部渲染快照；渲染路径会走 Paint 事件
render_ms = (time.perf_counter() - started) * 1000
dirty_after = count_dirty(win.settingPage)
check(
    dirty_after < dirty_before,
    f"渲染快照时顺带补刷了 {dirty_before - dirty_after} 个控件"
    f"（render 走 Paint 事件，上游 DirtyStyleSheetWatcher 会把要画的那批补上）",
)
print(f"  ---- 参考值：切页（渲染快照 + 起动画）{render_ms:.0f} ms")
wait_until(lambda: win._slide_overlay is None)

# 4.5 快照底色必须跟着主题走
# 不能用 QWidget.grab() 抓快照：它拿控件自己的 palette().window() 铺底，而 QSS 接管过的
# 子树里 palette 是缓存值（app.setPalette 进不去），亮色切暗色后整张快照还是浅灰。
def snapshot_brightness(page) -> float:
    """走真实切页路径取快照，按「叠在窗口底色上」之后的亮度打分（0~255）。"""
    win.switchTo(page)
    app.processEvents()
    overlay = win._slide_overlay
    if overlay is None or overlay.pixmap().isNull():
        return -1.0
    canvas = QImage(overlay.pixmap().size(), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QApplication.palette().color(QPalette.ColorRole.Window))
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, overlay.pixmap())
    painter.end()
    c = canvas.pixelColor(canvas.width() // 2, 18)  # 取顶部一点，避开内容
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


setTheme(Theme.LIGHT)
settle()
light_bright = snapshot_brightness(win.emojiPage)
wait_until(lambda: win._slide_overlay is None)
win.switchTo(win.homePage)
wait_until(lambda: win._slide_overlay is None)
setTheme(Theme.DARK, lazy=True)  # 此刻表情包页是脏的，正是当初「先白后黑」的场景
settle()
dark_bright = snapshot_brightness(win.emojiPage)
wait_until(lambda: win._slide_overlay is None)
check(
    light_bright > 180,
    f"亮色主题下快照底色是浅的（亮度 {light_bright:.0f}）",
)
check(
    dark_bright < 120,
    f"暗色主题下快照底色是深的（亮度 {dark_bright:.0f}，用 grab() 抓会是 ~239 的浅灰）",
)
win.close()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
