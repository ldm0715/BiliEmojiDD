"""屏幕外验证「记住窗口位置与大小」（app/components/window_state.py）。

1. 首次运行没有记录 → restore 返回 False，窗口保持调用方给的默认尺寸；
2. 往返：setGeometry 后 save，新窗口 restore 出来的几何逐字段相等；
3. 最大化状态一起记：最大化后 save，新窗口 restore 出来仍是最大化，
   且还原（showNormal）后的尺寸是最大化之前那个；
4. 记录跑到屏幕外 → 恢复后被拉回可用屏幕内（Qt 自己处理）；
5. 坏数据（键是数字 / 是乱码字符串）→ 不抛异常，返回 False；
6. 端到端：真的 MainWindow 改几何 → close() → 再构造一个 → 尺寸一致
   （只有这条能证明 closeEvent 真的写了盘）。

用法：QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_window_state.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 隔离配置目录：APP_CONFIG_DIR 在 import 时按 APPDATA 计算，必须早于 app.* 的导入，
# 否则会写脏用户真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-winstate-")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from qfluentwidgets import FluentWindow, qconfig

from app.common.config import cfg
from app.components.window_state import restore_window_state, save_window_state

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def make_window() -> FluentWindow:
    window = FluentWindow()
    window.setMinimumSize(820, 600)
    window.resize(1100, 760)
    return window


def forget() -> None:
    """把「没有记录」这个前提摆正。"""
    qconfig.set(cfg.window_geometry, "")


def rect(window) -> tuple[int, int, int, int]:
    g = window.geometry()
    return (g.x(), g.y(), g.width(), g.height())


# ---------------------------------------------------------------- 1. 首次运行
print("\n[首次运行]")
forget()
window = make_window()
check(not restore_window_state(window), "没有记录时 restore 返回 False")
check(
    window.size().toTuple() == (1100, 760),
    f"没有记录时窗口保持调用方给的默认尺寸（得到 {window.size().toTuple()}）",
)
window.close()
settle()

# ---------------------------------------------------------------- 2. 往返
print("\n[位置与大小的往返]")
forget()
source = make_window()
source.setGeometry(120, 90, 940, 680)
settle()
saved = rect(source)
save_window_state(source)
check(bool(cfg.window_geometry.value), "save 之后配置里有了记录")
check(
    all(ord(c) < 128 for c in cfg.window_geometry.value),
    "记录是纯 ASCII（base64），不依赖文件编码",
)

restored = make_window()
check(restore_window_state(restored), "有记录时 restore 返回 True")
check(rect(restored) == saved, f"恢复出来的几何与写之前一致（{rect(restored)} == {saved}）")
source.close()
restored.close()
settle()

# ---------------------------------------------------------------- 3. 最大化
print("\n[最大化状态]")
forget()
maxi = make_window()
maxi.setGeometry(140, 100, 900, 640)
maxi.show()
settle()
maxi.showMaximized()
settle()
check(
    maxi.isMaximized() and maxi.normalGeometry().getRect() == (140, 100, 900, 640),
    "前置条件：窗口确实最大化了，且 normalGeometry 是最大化之前那一组",
)
save_window_state(maxi)
maxi.close()
settle()

again = make_window()
check(restore_window_state(again), "最大化状态也能恢复")
again.show()
settle()
check(again.isMaximized(), "恢复出来仍是最大化")
# 断言 normalGeometry() 而不是「showNormal() 之后的 size」：离屏平台没有真的窗口管理器，
# `showNormal()` 会把 normalGeometry 丢掉、退回它自己的默认值（实测 640x480），
# 而 blob 里那个「最大化之前的大小」在 show() 之后已经正确落到 normalGeometry() 上了
# ——**这才是「最大化关窗 → 下次最大化，但还原后是原尺寸」依赖的那个值**。
# 真机上的 showNormal() 行为需要人工确认（见文件末尾）。
normal = again.normalGeometry()
saved_normal = (140, 100, 900, 640)  # 上面 setGeometry 的那一组，且已确认最大化前确实是它
check(
    (normal.x(), normal.y(), normal.width(), normal.height()) == saved_normal,
    f"最大化之前的大小被记住了（{normal.getRect()} == {saved_normal}）",
)
again.close()
settle()

# ---------------------------------------------------------------- 4. 跑到屏幕外
print("\n[记录跑到屏幕外]")
forget()
offscreen = make_window()
offscreen.setGeometry(40, 40, 1000, 700)
offscreen.show()
settle()
# 把窗口挪到 +20000（远在屏幕之外）再存——记录只能由窗口自己算出来，
# 没法手工拼一条「跑出屏幕」的 blob
offscreen.move(20000, 20000)
settle()
save_window_state(offscreen)
offscreen.close()

pulled = make_window()
restore_window_state(pulled)
settle()
rect_pulled = pulled.geometry()
inside = any(
    screen.availableGeometry().intersects(rect_pulled)
    for screen in QApplication.screens()
)
check(
    inside,
    f"跑到屏幕外的记录被拉回可用屏幕内（恢复成 {rect_pulled.getRect()}）",
)
pulled.close()
settle()

# ---------------------------------------------------------------- 5. 坏数据
print("\n[坏数据不崩]")
for bad in ("12345", "这不是 base64", "!!!", "AAAA"):
    qconfig.set(cfg.window_geometry, bad)
    broken = make_window()
    try:
        result = restore_window_state(broken)
    except Exception as exc:  # noqa: BLE001 就是想确认它不抛
        check(False, f"记录为 {bad!r} 时抛了 {type(exc).__name__}: {exc}")
    else:
        check(
            result is False,
            f"记录为 {bad!r} 时不认，返回 False（得到 {result}）",
        )
    check(
        broken.size().toTuple() == (1100, 760),
        f"记录为 {bad!r} 时窗口没被动过（{broken.size().toTuple()}）",
    )
    broken.close()

# 键被改成非字符串（手改配置文件 / 外部工具写坏）
qconfig.set(cfg.window_geometry, 12345)
numeric = make_window()
try:
    result = restore_window_state(numeric)
except Exception as exc:  # noqa: BLE001
    check(False, f"键是数字时抛了 {type(exc).__name__}: {exc}")
else:
    check(result is False, f"键是数字时不认（得到 {result}）")
numeric.close()
settle()

# ---------------------------------------------------------------- 6. 端到端
print("\n[端到端：closeEvent 真的写盘]")
forget()
from app.components import cookie_status
from app.components.content_meta import content_meta
from app.components.updater import set_enabled as updater_set_enabled
from app.components.video_cache import video_cache

content_meta.set_enabled(False)
video_cache.set_enabled(False)
updater_set_enabled(False)  # 启动后会静默查一次新版本
cookie_status.set_enabled(False)  # 主页 showEvent 会触发一次 Cookie 检测

from app.MainWindow import MainWindow

first = MainWindow()
first.show()
settle()
first.setGeometry(160, 130, 920, 660)
settle()
expected = rect(first)
first.close()
settle()
check(bool(cfg.window_geometry.value), "关窗后配置里留下了记录")

second = MainWindow()
settle()
check(
    rect(second) == expected,
    f"再开一个窗口恢复到关窗时的几何（{rect(second)} == {expected}）",
)
second.close()
settle()

# ---------------------------------------------------------------- 收尾
print()
if FAILS:
    print(f"{len(FAILS)} 项失败：")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("全部通过")
