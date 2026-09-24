"""屏幕外验证「一格滚轮 = 一行卡片」：网格位移口径、自适应、页面不受影响、幂等。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_wheel_step.py

位移公式（上游 `qfluentwidgets/common/smooth_scroll.py`）：
    px = angleDelta * stepRatio * wheelScrollLines * singleStep / 120
ItemView 的 `singleStep` 就是一行卡片的像素高（Qt 口径），所以 `stepRatio` 取
`1 / wheelScrollLines` 就恰好是一行；整页 `ScrollArea` 的 `singleStep` 是 20px 文本行，
`stepRatio` 保持上游的 1.5 —— 本脚本把两条都钉住。

**必须走真实布卡路径**：单元格尺寸是在 `_layout_items()` 里才写进 item 的 sizeHint，
而 `singleStep` 正是从 sizeHint 推出来的。绕开 `set_cards()` 自己 `addItem` 会得到
39 而不是 176，量出来的位移差 4 倍多（本脚本第一版就踩了这个坑）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA，否则写脏用户真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import ScrollArea

app = QApplication(sys.argv)

from app.components.page_scaffold import (
    WHEEL_ROWS_PER_NOTCH,
    _wheel_lines,
    tune_scroll,
)
from app.components.widgets import EmojiGrid, PackageGrid

FAILS: list[str] = []
LINES = QApplication.wheelScrollLines()
CARD_COUNT = 60


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class _StubCard(QWidget):
    """占位卡片：`_CardGridBase` 在 set_cards / _update_visible / _layout_items
    里会去调的那几个接口。少一个就 AttributeError 当场炸，不会静默放过。"""

    clicked = Signal()
    toggled = Signal(bool)

    def __init__(self, item, parent=None) -> None:
        super().__init__(parent)

    def set_selectable(self, _flag: bool) -> None: ...
    def set_checked(self, _flag: bool) -> None: ...
    def set_spinner_wanted(self, _flag: bool) -> None: ...
    def set_pixmap(self, _pixmap) -> None: ...
    def set_cell(self, cell) -> None:
        self.setFixedSize(cell)


def pump(ms: int) -> None:
    """等真实时间（`processEvents` 不推进时钟，滚动定时器不会 tick）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def build(cls):
    """按 `set_cards` 的真实路径布卡，再返回网格。"""
    cls._card_class = _StubCard
    grid = cls()
    grid._cover_url = lambda _item: ""  # 没有封面地址 → 不排缩略图请求
    grid.resize(878, 500)
    grid.show()
    app.processEvents()
    grid.set_cards(list(range(CARD_COUNT)))
    app.processEvents()
    return grid


def wheel_once(area) -> int:
    """合成一格标准滚轮（120 角度）打到 viewport，等平滑动画走完，返回位移像素。"""
    vbar = area.verticalScrollBar()
    vbar.setValue(vbar.maximum() // 2)  # 摆到中段，两边都留够余量防夹住
    before = vbar.value()
    app.processEvents()
    app.sendEvent(
        area.viewport(),
        QWheelEvent(
            QPointF(100, 100),
            QPointF(100, 100),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        ),
    )
    pump(600)  # duration=200ms，留足 3 倍余量
    after = vbar.value()
    check(
        0 < after < vbar.maximum(),
        f"测量没被滚动条两端夹住（value={after}, range=0..{vbar.maximum()}）",
    )
    return before - after


print("== 1. 行数口径 ==")
check(
    WHEEL_ROWS_PER_NOTCH == 1,
    f"一格滚轮 = 1 行卡片（实际 {WHEEL_ROWS_PER_NOTCH}）",
)
check(
    _wheel_lines() == (LINES if LINES > 0 else 3),
    f"行数读系统「一次滚动下列行数」（wheelScrollLines={LINES} → {_wheel_lines()}），"
    "非正数按 3 兜底",
)

print("== 2. PackageGrid：一格 = 一行（上游口径是 4.9 行）==")
pkg = build(PackageGrid)
pkg_row = pkg.gridSize().height()
pkg_delta = wheel_once(pkg)
pkg_ratio = pkg_delta / pkg_row
check(
    1.0 <= pkg_ratio <= 1.25,
    f"一格位移 {pkg_delta} px ÷ 行高 {pkg_row} = {pkg_ratio:.2f} 行，落在 [1.0, 1.25]",
)
check(pkg_ratio < 2.0, f"明显小于上游的 4.9 行口径（实际 {pkg_ratio:.2f} 行）")
check(
    abs(pkg.scrollDelegate.verticalSmoothScroll.stepRatio - 1 / _wheel_lines()) < 1e-9,
    "纵向 stepRatio = 1 / wheelScrollLines"
    f"（实际 {pkg.scrollDelegate.verticalSmoothScroll.stepRatio:.4f}）",
)
check(
    abs(pkg.scrollDelegate.horizonSmoothScroll.stepRatio - 1 / _wheel_lines()) < 1e-9,
    "横向 SmoothScroll 口径一致（触控板横向滚动不会忽快忽慢）",
)

print("== 3. EmojiGrid：换一种行高仍是一行（证明自适应，不是写死的像素）==")
emoji = build(EmojiGrid)
emoji_row = emoji.gridSize().height()
emoji_delta = wheel_once(emoji)
emoji_ratio = emoji_delta / emoji_row
check(
    1.0 <= emoji_ratio <= 1.25,
    f"一格位移 {emoji_delta} px ÷ 行高 {emoji_row} = {emoji_ratio:.2f} 行，落在 [1.0, 1.25]",
)
check(
    abs(pkg_delta - emoji_delta) > 15,
    f"两种行高（{pkg_row} / {emoji_row}）位移不同（{pkg_delta} / {emoji_delta} px），"
    "跟的是行高而不是固定像素",
)

print("== 4. 幂等：连调三次不会越除越小 ==")
before_ratio = pkg.scrollDelegate.verticalSmoothScroll.stepRatio
for _ in range(3):
    tune_scroll(pkg)
check(
    pkg.scrollDelegate.verticalSmoothScroll.stepRatio == before_ratio,
    f"连调三次后 stepRatio 不变（{before_ratio:.4f}）",
)
check(
    not pkg.scrollDelegate.verticalSmoothScroll.stepsLeftQueue,
    "调 tune_scroll 不会往滚动队列里塞东西",
)

print("== 5. 整页 ScrollArea 不受影响（主页 / 设置页保持上游口径）==")
area = ScrollArea()
area.resize(400, 300)
inner = QWidget()
inner.setFixedHeight(3000)
area.setWidget(inner)
area.show()
app.processEvents()
tune_scroll(area)
page_scroll = area.scrollDelagate.verticalSmoothScroll
check(
    page_scroll.stepRatio == 1.5,
    f"页面 stepRatio 仍是上游的 1.5（实际 {page_scroll.stepRatio}）",
)
page_delta = wheel_once(area)
check(
    page_delta < pkg_delta,
    f"页面一格 {page_delta} px 小于网格一格 {pkg_delta} px（没被顺手一起改掉）",
)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("ALL PASSED")
