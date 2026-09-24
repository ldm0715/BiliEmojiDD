"""屏幕外验证「滚动帧率」设置项：配置项、即时生效、整除约束、设置页接线。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_scroll_fps.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA：本脚本会真的改 cfg.scroll_fps，
# 不隔离就把用户真实的 config.json 写脏了
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.common.config import SCROLL_FPS, cfg
from app.components.page_scaffold import (
    SCROLL_DURATION,
    apply_scroll_fps,
    tune_scroll,
)
from app.components.widgets import PackageGrid

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def smooths(area):
    """该控件上的两个 SmoothScroll（拿不到返回空列表）。"""
    delegate = getattr(area, "scrollDelagate", None) or getattr(
        area, "scrollDelegate", None
    )
    if delegate is None:
        return []
    return [delegate.verticalSmoothScroll, delegate.horizonSmoothScroll]


print("== 1. 配置项 ==")
check(cfg.scroll_fps.value == 60, f"默认值是省 CPU 的 60（实际 {cfg.scroll_fps.value}）")
check(
    list(SCROLL_FPS) == [60, 120],
    f"可选值是 (60, 120)，且 60 排第一（非法值兜底取 options[0] 才不会突然费 CPU）"
    f"（实际 {list(SCROLL_FPS)}）",
)

print("== 2. 整除约束：两档都必须能整除，否则滚动队列永不清空 ==")
for fps in SCROLL_FPS:
    check(
        fps * SCROLL_DURATION % 1000 == 0,
        f"fps={fps} × duration={SCROLL_DURATION} = {fps * SCROLL_DURATION}，是 1000 的整数倍",
    )

print("== 3. tune_scroll 把配置里的 fps 设上去（网格与页面两种容器）==")
grid = PackageGrid()
grid.resize(900, 500)
grid.show()
app.processEvents()
for fps in (120, 60):
    cfg.scroll_fps.value = fps
    tune_scroll(grid)
    got = [s.fps for s in smooths(grid)]
    check(
        got == [fps, fps],
        f"cfg.scroll_fps={fps} 时网格两个方向都设成 {fps}（实际 {got}）",
    )
check(
    all(s.duration == SCROLL_DURATION for s in smooths(grid)),
    f"duration 固定 {SCROLL_DURATION}（两档都整除，改 fps 就够了）",
)

print("== 4. apply_scroll_fps 刷已存在的滚动区域（所以不需要重启）==")
cfg.scroll_fps.value = 120
applied = apply_scroll_fps()
check(applied > 0, f"刷到了 {applied} 个滚动区域（0 个就说明设置页改了没反应）")
check(
    all(s.fps == 120 for s in smooths(grid)),
    "已存在的网格滚动区域被刷成 120",
)
cfg.scroll_fps.value = 60
apply_scroll_fps()
check(
    all(s.fps == 60 for s in smooths(grid)),
    "改回 60 也能即时刷回去（幂等、可来回切）",
)

print("== 5. 设置页接线：下拉存在、文案与取值对齐、选中项跟配置 ==")
from app.view.setting_page import _SCROLL_FPS, SettingPage

page = SettingPage()
app.processEvents()
combo = page.scrollFpsCombo
values = [combo.itemData(i) for i in range(combo.count())]
check(values == list(SCROLL_FPS), f"下拉取值与 config.SCROLL_FPS 一致（实际 {values}）")
check(
    [text for text, _ in _SCROLL_FPS] == [combo.itemText(i) for i in range(combo.count())],
    "下拉文案与 _SCROLL_FPS 一致",
)
check(combo.currentData() == 60, f"打开时选中当前配置（60，实际 {combo.currentData()}）")

print("== 6. 改下拉 → 落库 + 即时生效 ==")
combo.setCurrentIndex(1)  # 切到 120
app.processEvents()
check(cfg.scroll_fps.value == 120, f"选中后写进配置（实际 {cfg.scroll_fps.value}）")
check(
    all(s.fps == 120 for s in smooths(grid)),
    "选中后已存在的滚动区域立刻变成 120（无需重启）",
)
combo.setCurrentIndex(0)
app.processEvents()
check(cfg.scroll_fps.value == 60, f"切回去也落库（实际 {cfg.scroll_fps.value}）")

print("== 7. 非法值兜底 ==")
cfg.scroll_fps.value = 999
check(
    cfg.scroll_fps.value == 60,
    f"非法帧率被 OptionsValidator 兜成 options[0]（= 省 CPU 的 60，实际 {cfg.scroll_fps.value}）",
)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("ALL PASSED")
