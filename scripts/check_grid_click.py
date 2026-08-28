"""屏幕外验证两个详情网格的点击 → imageClicked(index) 接线是否正确。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.components.widgets import DressDetailGrid, EmojiGrid, PackageGrid, QueueList

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


print("== EmojiGrid：空 url 被过滤，索引与 items() 对齐 ==")
grid = EmojiGrid()
raw = [
    ("a", "https://x.invalid/a.png"),
    ("skipped", ""),          # 空 url 应被跳过
    ("b", "https://x.invalid/b.png"),
    ("dup", "https://x.invalid/a.png"),  # 同 url 复用
]
grid.set_emotes(raw)
got: list[int] = []
grid.imageClicked.connect(got.append)

check(grid.items() == [
    ("a", "https://x.invalid/a.png"),
    ("b", "https://x.invalid/b.png"),
    ("dup", "https://x.invalid/a.png"),
], f"items() 已过滤空 url（实际 {grid.items()}）")
check(grid.count() == 3, f"建了 3 张卡（实际 {grid.count()}）")

for i in range(grid.count()):
    card = grid.itemWidget(grid.item(i))
    card.clicked.emit(card)
check(got == [0, 1, 2], f"点击各卡发出的索引（实际 {got}）")
check(
    all(grid.items()[i][1] == grid.itemWidget(grid.item(i)).url for i in got),
    "索引指向的 url 与卡片自身 url 一致",
)

print("== DressDetailGrid：内容重复（甚至同一对象）也不串位 ==")
dgrid = DressDetailGrid()
same = ("同名", "https://x.invalid/same.png")
# 注意：CPython 会把内容相同的元组字面量常量折叠成同一对象，所以这里第 2/3 项
# 很可能就是同一个 tuple —— 下标必须由建卡顺序决定，不能靠载荷身份反查
items = [("first", "https://x.invalid/1.png"), same, same]
dgrid.set_items(items)
dgot: list[int] = []
dgrid.imageClicked.connect(dgot.append)

check(dgrid.count() == 3, f"建了 3 张卡（实际 {dgrid.count()}）")
for i in range(dgrid.count()):
    card = dgrid.itemWidget(dgrid.item(i))
    card.clicked.emit(card.item)
check(dgot == [0, 1, 2], f"载荷是同一对象时仍各自定位（实际 {dgot}）")

print("== DetailCard 图片按钮点击也触发 ==")
card0 = dgrid.itemWidget(dgrid.item(0))
dgot.clear()
card0._on_image_clicked()
check(dgot == [0], f"imageBtn 点击（实际 {dgot}）")

print("== 其余复用 _CardGridBase 的网格：itemClicked 转发未被改坏 ==")


class _Pkg:
    """够 PackageCard / QueueCard 用的最小 EmotePackage 替身。"""

    def __init__(self, pid: int) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = []
        self.url = f"https://x.invalid/p{pid}.png"


for grid_cls, signal_name, setter in (
    (PackageGrid, "packageClicked", "set_packages"),
    (QueueList, "queueClicked", "set_items"),
):
    g = grid_cls()
    payloads = [_Pkg(1), _Pkg(2)]
    getattr(g, setter)(payloads)
    seen: list = []
    getattr(g, signal_name).connect(seen.append)
    g.itemWidget(g.item(1)).clicked.emit(payloads[1])
    check(
        seen == [payloads[1]],
        f"{grid_cls.__name__}.{signal_name} 转发正常（实际 {[p.id for p in seen]}）",
    )

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
