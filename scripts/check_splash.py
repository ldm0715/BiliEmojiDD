"""屏幕外验证开屏面板（不联网、不弹窗）。

1. 面板含图标 / 应用名 / 版本号 / 进度文案，尺寸与居中位置正常；
2. `set_message` 换文案且不进事件循环（同步 repaint）；
3. `finish()` 之后面板不可见；
4. 亮 / 暗两个主题各构造一次都不崩，背景色跟着主题走；
5. **`splash` 模块不 import 任何页面模块**——否则等于把要遮的启动开销
   提到了开屏之前，面板就白加了；
6. `MainWindow.__init__` 接受 `on_progress` 回调且真的会调它。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_splash.py
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA，否则会写脏真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from qfluentwidgets import Theme, setTheme

from app.common.config import APP_VERSION
from app.components.splash import _TITLE, SplashWindow

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------ 1. 内容
print("== 1. 面板内容 ==")
setTheme(Theme.LIGHT)
splash = SplashWindow()
splash.start()

check(splash.titleLabel.text() == _TITLE, f"标题是品牌名（{_TITLE}）")
check(_TITLE == "BiliEmojiDD", "品牌名与窗口标题 / 主页 / 设置页保持一致（大写 B）")
check(
    APP_VERSION in splash.versionLabel.text(),
    f"版本胶囊含版本号（{splash.versionLabel.text()}）",
)
check(not splash.iconWidget.icon.isNull(), "图标非空（static/logo.ico 读到了）")
check(splash.messageLabel.text().strip() != "", "初始就有进度文案")
check(splash.size().width() > 200 and splash.size().height() > 120, "尺寸不至于太小")

screen = QApplication.primaryScreen().availableGeometry()
center = splash.geometry().center()
check(
    abs(center.x() - screen.center().x()) <= 1
    and abs(center.y() - screen.center().y()) <= 1,
    "面板居中于主屏可用区",
)

# ------------------------------------------------------------------ 2. 进度
print("\n== 2. 进度文案 ==")
splash.set_message("正在准备表情包页…")
check(splash.messageLabel.text() == "正在准备表情包页…", "set_message 换掉了文案")
splash.set_message("正在装配窗口…")
check(splash.messageLabel.text() == "正在装配窗口…", "可以反复更新")

# 回归：布局整体设 AlignHCenter 会让带 wordWrap 的 Label 只拿到 sizeHint 宽度，
# 进度文案被挤成细细一条、折行还看不清（真实反馈）。文案行必须铺满可用宽度。
margins = splash.layout().contentsMargins()
inner = splash.width() - margins.left() - margins.right()
label = splash.messageLabel
check(
    label.width() >= inner - 1,
    f"进度文案铺满可用宽度（{label.width()} / {inner}），不会被挤成一条",
)
widest = max(
    label.fontMetrics().horizontalAdvance(t)
    for t in ("正在加载界面组件…", "正在准备收藏集页…", "正在装配窗口…")
)
check(widest <= label.width(), f"最长的一条文案也能单行放下（{widest} ≤ {label.width()}）")

# ------------------------------------------------------------------ 3. 关闭
print("\n== 3. 关闭 ==")
splash.finish()
check(not splash.isVisible(), "finish() 之后面板不可见")

# ------------------------------------------------------------------ 4. 主题
print("\n== 4. 主题 ==")
for theme, name in ((Theme.DARK, "暗色"), (Theme.LIGHT, "亮色")):
    setTheme(theme)
    probe = SplashWindow()
    probe.start()
    check(probe.isVisible(), f"{name}主题下能正常构造并显示")
    probe.finish()

# ------------------------------------------------------------------ 5. 依赖
print("\n== 5. 模块依赖 ==")
# 按 import 语句判，不能按「源码里出没出现过这个词」——docstring 里就会提到 MainWindow
source = (Path(__file__).resolve().parent.parent / "app/components/splash.py").read_text(
    encoding="utf-8"
)
imported: set[str] = set()
for node in ast.walk(ast.parse(source)):
    if isinstance(node, ast.Import):
        imported.update(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module)
heavy = {m for m in imported if m.startswith("app.view") or m == "app.MainWindow"}
check(not heavy, f"splash 不 import 页面 / 主窗口模块（实际多出：{heavy or '无'}）")
check(
    all(not m.startswith("biliemoji") for m in imported),
    "splash 不 import biliemoji（SDK 导入也是启动开销的一部分）",
)

# ------------------------------------------------------------------ 6. 回调
print("\n== 6. MainWindow 进度回调 ==")
import inspect

from app.MainWindow import MainWindow

signature = inspect.signature(MainWindow.__init__)
check("on_progress" in signature.parameters, "MainWindow.__init__ 收 on_progress")
check(
    signature.parameters["on_progress"].default is None,
    "on_progress 可省略（屏幕外脚本 / 测试照旧无参构造）",
)

from app.components import cookie_status, updater

updater.set_enabled(False)  # 启动 3 秒后的自动检查会真发网络请求
cookie_status.set_enabled(False)  # 主页 showEvent 会触发一次 Cookie 检测

messages: list[str] = []
window = MainWindow(on_progress=messages.append)
check(len(messages) >= 5, f"构造五个页面时各报了一次进度（收到 {len(messages)} 条）")
check(all(isinstance(m, str) and m for m in messages), "进度文案都是非空字符串")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
