"""屏幕外验证「窗口 resize 后网格该更新的都更新了」：单元格重算、卡片换尺寸、缩略图跟着缩放。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_reflow.py

两类 bug 都在这里钉住：
1. 网格尺寸重算了，但卡片控件 / 缩略图没跟着变。`QLabel` 不会自己缩放 pixmap
   （没设 `scaledContents`），`EmojiCard` 曾经漏了重设这一步，表现是
   「放大窗口缩略图过小、缩窗口被裁成放大」，而收藏集详情的 `DetailCard` 有这一步。
2. 重排被短路吞掉（`_layout_items` 里 `cell == _last_cell` 直接 return），
   resize 后尺寸原地不动。

**必须走真实布卡路径**（`set_cards`）：单元格尺寸是在 `_layout_items()` 里才写进 item 的
sizeHint，而且卡片控件要真的存在才量得到 `set_cell` 有没有落下去。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA，否则写脏用户真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

from app.components.widgets import EmojiGrid, PackageGrid

FAILS: list[str] = []


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


def build_grid() -> PackageGrid:
    PackageGrid._card_class = _StubCard
    grid = PackageGrid()
    grid._cover_url = lambda _item: ""  # 没有封面地址 → 不排缩略图请求
    grid.resize(880, 520)
    grid.show()
    app.processEvents()
    grid.set_cards(list(range(60)))
    app.processEvents()
    return grid


def resize_to(grid: PackageGrid, vw: int) -> int:
    """把网格调到「视口宽度 = vw」，返回实际视口宽。"""
    grid.resize(vw + (grid.width() - grid.viewport().width()), 520)
    app.processEvents()
    return grid.viewport().width()


def overflow_count(grid: PackageGrid, vw: int) -> int:
    return sum(
        1 for i in range(grid.count()) if grid.visualItemRect(grid.item(i)).right() > vw
    )


grid = build_grid()
MIN_W = PackageGrid._min_cell.width()

print("== 1. resize 每一档都真的重算了单元格（防 _last_cell 短路吞掉）==")
cells: list[int] = []
for target in (880, 1050, 1370):
    resize_to(grid, target)
    cells.append(grid.gridSize().width())
    print(f"  视口 {grid.viewport().width()} → 单元格 {cells[-1]}px")
check(len(set(cells)) == 3, f"三档视口算出三个不同单元格（实际 {cells}）")

print("== 2. 卡片控件跟着换尺寸 ==")
resize_to(grid, 1370)
check(
    grid.itemWidget(grid.item(0)).size() == grid.gridSize(),
    f"itemWidget 尺寸 == gridSize（{grid.itemWidget(grid.item(0)).size()} "
    f"vs {grid.gridSize()}）",
)

print("== 3. 窄窗口 / 宽窗口都不横向溢出，且不低于最小单元格 ==")
for target in (590, 880, 1690):
    vw = resize_to(grid, target)
    cell = grid.gridSize().width()
    right = max(grid.visualItemRect(grid.item(i)).right() for i in range(grid.count()))
    check(cell >= MIN_W, f"视口 {vw} 时单元格 {cell}px 不低于最小单元格 {MIN_W}px")
    check(
        overflow_count(grid, vw) == 0,
        f"视口 {vw} 时无横向溢出（单元格 {cell}px，右边缘最大 {right}）",
    )

print("== 4. 缩略图跟着卡片缩放（EmojiCard 走 QLabel pixmap，QLabel 不会自己缩）==")
# 预置 QPixmapCache：假 URL 不预置的话每张排一个 15s 超时的真实网络任务，脚本退不出去
urls = [f"http://check.invalid/emoji/{i}.png" for i in range(24)]
fake = QPixmap(512, 512)
fake.fill(QColor("red"))
for url in urls:
    QPixmapCache.insert(url, fake)

emoji_grid = EmojiGrid()
emoji_grid.resize(900, 500)
emoji_grid.show()
app.processEvents()
emoji_grid.set_emotes([(f"表情{i}", url, False) for i, url in enumerate(urls)])
app.processEvents()
emoji_cards = [emoji_grid.itemWidget(emoji_grid.item(i)) for i in range(4)]
for card in emoji_cards:  # 直接喂假图，不等缩略图流水线
    card.set_pixmap(fake)
app.processEvents()

icon_sizes: list[int] = []
for target in (700, 1200):
    emoji_grid.resize(target, 500)
    app.processEvents()
    icon = emoji_cards[0].iconLabel
    icon_sizes.append(icon.pixmap().width())
    check(
        icon.pixmap().width() == icon.width(),
        f"视口 {emoji_grid.viewport().width()} 时缩略图 {icon.pixmap().width()}px "
        f"跟得上图标框 {icon.width()}px",
    )
check(
    len(set(icon_sizes)) == 2,
    f"两档视口下缩略图真的重缩放了（实际 {icon_sizes}，相同就说明 pixmap 停在旧尺寸）",
)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("ALL PASSED")
