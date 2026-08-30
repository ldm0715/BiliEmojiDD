"""屏幕外验证应用外壳：消息提示位置 + 全局字体 + 切页无动画。

1. `notify_*` 无论从哪个页面发出，InfoBar 都挂到窗口的**内容区**
   （`FluentWindow.stackedWidget`，即标题栏以下 / 侧栏以右）的右上角；
2. 切换页面后消息仍在（挂子页的话会跟着页面一起被 QStackedWidget 藏掉）；
3. 没有 FluentWindow 时（脚本单独构页）父级原样退回，不抛；
4. 内置字体加载成功并成为应用默认字体；
5. **qfluentwidgets 的 getFont 补丁生效** —— 库里硬编码字体族，光 setFont 改不动组件库控件；
6. **切页不做位移动画** —— 上游 300ms 的整页 pos 动画会把整页重绘十几帧。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_shell.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

from app.common.config import FONT_ENGINES, cfg
from app.common.font import (
    PREFERRED_FAMILY,
    apply_app_font,
    apply_font_engine,
    font_families,
)
from app.common.resource import FONT_DIR, app_font_files

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


def wait_slide(bar, timeout: float = 2.0) -> None:
    """等 InfoBarManager 的滑入动画真正结束——光 processEvents 不推进时间。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ani = bar.property("slideAni")
        if ani is not None and ani.state() != QAbstractAnimation.State.Running:
            break
        settle(2)
        time.sleep(0.01)
    settle(2)


print("== 1. 内置字体 ==")
files = app_font_files()
check(bool(files), f"{FONT_DIR} 下有 Qt 认得的字体文件（{[p.name for p in files]}）")
check(
    all(p.suffix.lower() in (".ttf", ".otf", ".ttc") for p in files),
    "只收 TTF/OTF/TTC —— Qt 的 addApplicationFont 加载不了 woff2",
)
# 字体加载 + 打补丁必须在导入任何组件库控件之前完成（本脚本此刻还没建过控件）
family = apply_app_font(app)
check(family is not None, f"字体加载成功（族名 {family!r}）")
check(
    family == PREFERRED_FAMILY,
    f"用的是首选族 {PREFERRED_FAMILY!r} 而不是碰运气的文件名排序第一个（实际 {family!r}）",
)
check(
    app.font().families()[:1] == [family],
    f"应用默认字体首选内置字体（{app.font().families()}）",
)
check(
    font_families(family)[0] == family and "Microsoft YaHei" in font_families(family),
    "回落链：内置字体在前、系统字体兜底",
)

print("== 2. qfluentwidgets 字体补丁 ==")
from qfluentwidgets import BodyLabel, TitleLabel
from qfluentwidgets.common.font import getFont
from qfluentwidgets.components.widgets import label as fw_label

check(hasattr(getFont, "__wrapped__"), "qfluentwidgets.common.font.getFont 已被替换")
check(
    getattr(fw_label.getFont, "__wrapped__", None) is not None,
    "label.py 里导入时绑定的 getFont 也重绑了（import 那刻就绑死了函数对象）",
)
check(
    getFont(14).families()[:1] == [family],
    f"getFont 返回的族名以内置字体打头（{getFont(14).families()[:2]}）",
)
body = BodyLabel("测试文字")
title = TitleLabel("标题")
check(
    body.font().families()[:1] == [family],
    f"BodyLabel 用上了内置字体（{body.font().families()[:2]}）",
)
check(
    title.font().families()[:1] == [family],
    f"TitleLabel 用上了内置字体（{title.font().families()[:2]}）",
)
check(
    len(set(getFont(14).families())) == len(getFont(14).families()),
    "族名列表已去重（不重复堆上游那三个）",
)

print("== 2c. qss 里硬编码的字体族也换掉了（QSS 优先级高于 setFont） ==")
# 上游 23 个 qss 写死 `font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC'`，
# QSS 赢过 setFont —— 只打 getFont 补丁的话，按钮/勾选框/InfoBar 全都退回 Segoe UI
from qfluentwidgets import CheckBox, FluentStyleSheet, PushButton, Theme
from qfluentwidgets.common.style_sheet import getStyleSheetFromFile

check(
    getattr(getStyleSheetFromFile, "__wrapped__", None) is not None,
    "getStyleSheetFromFile 已被包一层（qss 编在 Qt 资源里，只能在读出来时替换）",
)
hardcoded = [
    name
    for name in ("BUTTON", "CHECK_BOX", "INFO_BAR", "EXPAND_SETTING_CARD", "SETTING_CARD")
    if "'Segoe UI', 'Microsoft YaHei'" in getattr(FluentStyleSheet, name).content(Theme.LIGHT)
]
check(not hardcoded, f"关键 qss 里不再有硬编码的 Segoe UI 族名（残留 {hardcoded}）")
check(
    family in FluentStyleSheet.BUTTON.content(Theme.LIGHT),
    "BUTTON qss 的 font 族名换成了内置字体",
)
for name, widget in (("PushButton", PushButton("按钮")), ("CheckBox", CheckBox("勾选框说明"))):
    widget.ensurePolished()  # QSS 的字体要 polish 之后才落到 widget.font()
    check(
        widget.font().families()[:1] == [family],
        f"{name} polish 后仍是内置字体（{widget.font().families()[:1]}）",
    )

print("== 2b. 字体渲染后端 ==")
# QT_QPA_PLATFORM 已被本脚本设成 offscreen，apply_font_engine 必须让路，
# 否则断言脚本会被拽回真实平台
check(FONT_ENGINES == ("default", "freetype"), f"只给实测有效的两种后端（{FONT_ENGINES}）")
before = os.environ.get("QT_QPA_PLATFORM")
cfg.font_engine.value = "freetype"
check(apply_font_engine() is None, "QT_QPA_PLATFORM 已被外部指定时不覆盖")
check(os.environ.get("QT_QPA_PLATFORM") == before, f"平台字符串没被改（{os.environ.get('QT_QPA_PLATFORM')!r}）")
os.environ.pop("QT_QPA_PLATFORM", None)
cfg.font_engine.value = "default"
check(apply_font_engine() is None, "default 不设任何平台参数")
check("QT_QPA_PLATFORM" not in os.environ, "default 下环境干净")
cfg.font_engine.value = "freetype"
engine = apply_font_engine()
check(
    (engine == "freetype" and os.environ.get("QT_QPA_PLATFORM") == "windows:fontengine=freetype")
    or sys.platform != "win32",
    f"freetype 写出平台参数（{os.environ.get('QT_QPA_PLATFORM')!r}）",
)
os.environ["QT_QPA_PLATFORM"] = before or "offscreen"
cfg.font_engine.value = "default"

print("== 3. 消息提示挂在内容区 ==")
from app.common.notify import _resolve_parent, notify_info, notify_success
from app.components.content_meta import content_meta
from app.components.video_cache import video_cache

content_meta.set_enabled(False)
video_cache.set_enabled(False)

from app.MainWindow import MainWindow

window = MainWindow()
window.resize(1100, 760)
window.show()
settle()

bar = notify_info("标题", "内容", parent=window.dressPage)
wait_slide(bar)
check(
    bar.parent() is window.stackedWidget,
    f"InfoBar 挂到窗口内容区而不是子页（parent={type(bar.parent()).__name__}）",
)
stacked = window.stackedWidget
check(
    bar.x() + bar.width() <= stacked.width() and bar.x() > stacked.width() // 2,
    f"贴在内容区右侧（x={bar.x()} w={bar.width()} 容器宽={stacked.width()}）",
)
check(
    0 <= bar.y() <= 40,
    f"贴在内容区顶部（y={bar.y()}，上游 InfoBarManager 的 margin 是 24）",
)
# 内容区已被 FluentWindowBase 的 widgetLayout 上边距 48 推到标题栏下方
check(
    stacked.mapTo(window, stacked.rect().topLeft()).y() >= 40,
    "内容区本身在标题栏下方，所以消息不会压住窗口控制按钮",
)

print("== 4. 切页后消息仍在 ==")
bar2 = notify_success("另一条", "从收藏集页发出", parent=window.dressPage)
wait_slide(bar2)
window.switchTo(window.downloadPage)
settle()
check(bar2.isVisible(), "切到别的页面后消息仍然可见（挂子页会被 QStackedWidget 藏掉）")
check(bar2.parent() is window.stackedWidget, "第二条也挂在内容区")

print("== 5. 切页不做位移动画 ==")
view = window.stackedWidget.view
# 上游 PopUpAniStackedWidget 切页要跑 300ms 的整页 pos 动画（deltaY=76），
# 整页每帧重绘一次 —— 主页/设置页单帧 11-12ms，肉眼就是卡
for page in (window.emojiPage, window.settingPage, window.homePage):
    window.switchTo(page)
    app.processEvents()  # 只给一轮：动画版这时候页还停在 +76px 上
    check(
        view.currentWidget() is page and page.y() == 0,
        f"切到 {page.objectName()} 一轮事件循环内就到位（y={page.y()}）",
    )
    check(
        view._ani is None or view._ani.state() != QAbstractAnimation.State.Running,
        f"切到 {page.objectName()} 没有残留的位移动画",
    )
# 标题栏返回按钮走 qrouter.pop() → stacked.setCurrentWidget，不经 switchTo
check(
    window.stackedWidget.setCurrentWidget == window._set_current_interface,
    "stackedWidget.setCurrentWidget 也被换掉了（覆盖返回按钮那条路径）",
)
window.stackedWidget.setCurrentWidget(window.downloadPage)
app.processEvents()
check(
    view.currentWidget() is window.downloadPage and window.downloadPage.y() == 0,
    "经 setCurrentWidget 切页同样即时到位",
)

print("== 6. 无窗口时的降级 ==")
orphan = QWidget()
check(_resolve_parent(orphan) is orphan, "没有 FluentWindow 时父级原样返回")
check(_resolve_parent(None) is None, "parent=None 不抛")
orphan.deleteLater()

bar.close()
bar2.close()
window.close()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
