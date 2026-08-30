"""屏幕外验证图片查看器：letterbox 尺寸恒等、翻页、UI 同步、点击遮罩关闭。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_image_viewer.py
不走网络：直接把假 QPixmap 预置进 QPixmapCache，thumb_manager.request 会同步命中。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget

# 先建 QApplication 再导入组件（thumb_manager 是模块级 QObject，须在主线程构造）
app = QApplication(sys.argv)

from app.components.image_viewer import ImageViewer, _canvas_size

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# 三张不同宽高比的假图（横 / 竖 / 小方），预置进缓存
SPECS = [("wide", 1600, 900), ("tall", 600, 1400), ("tiny", 64, 64)]
items = []
for name, w, h in SPECS:
    url = f"https://example.invalid/{name}.png"
    pm = QPixmap(w, h)
    pm.fill(QColor("#3478f6"))
    QPixmapCache.insert(url, pm)
    items.append((name, url))

host = QWidget()
host.resize(1280, 860)
host.show()

viewer = ImageViewer(items, 1, host)
viewer.show()
app.processEvents()

fv = viewer.flipView
canvas = _canvas_size(viewer._item_size, viewer._dpr)

print("== 构造 ==")
check(fv.count() == 3, f"flipView.count() == 3（实际 {fv.count()}）")
check(fv.currentIndex() == 1, f"初始 currentIndex == 1（实际 {fv.currentIndex()}）")

print("== letterbox：所有 item 图与 sizeHint 恒等 ==")
for i, (name, _) in enumerate(items):
    img = fv.itemImage(i)
    check(not img.isNull(), f"item[{i}] ({name}) 图片非空")
    check(
        img.size() == canvas,
        f"item[{i}] ({name}) 画布 {img.size().toTuple()} == itemSize*dpr {canvas.toTuple()}",
    )
    check(
        fv.item(i).sizeHint() == viewer._item_size,
        f"item[{i}] ({name}) sizeHint 固定为 itemSize",
    )

print("== UI 同步 ==")
check(viewer.countLabel.text() == "2 / 3", f"页码文字（实际 {viewer.countLabel.text()!r}）")
check(viewer.nameLabel.text() == "tall", f"名称文字（实际 {viewer.nameLabel.text()!r}）")
check(viewer.pips.currentIndex() == 1, f"pips 同步（实际 {viewer.pips.currentIndex()}）")

print("== 翻页 + 首尾禁用 ==")
check(fv.preButton.isHidden() and fv.nextButton.isHidden(), "上游那两个贴边小箭头已藏起")
fv.scrollNext()
app.processEvents()
check(fv.currentIndex() == 2, f"scrollNext → index 2（实际 {fv.currentIndex()}）")
check(viewer.countLabel.text() == "3 / 3", f"页码跟随（实际 {viewer.countLabel.text()!r}）")
check(viewer.pips.currentIndex() == 2, "pips 跟随")
check(not viewer.nextBtn.isEnabled(), "末张禁用「下一张」")
check(viewer.prevBtn.isEnabled(), "末张「上一张」可用")

fv.scrollNext()
app.processEvents()
check(fv.currentIndex() == 2, "末张再 scrollNext 不越界")

print("== 底部翻页按钮驱动 flipView ==")
viewer.prevBtn.click()
app.processEvents()
check(fv.currentIndex() == 1, f"点「上一张」→ index 1（实际 {fv.currentIndex()}）")
viewer.nextBtn.click()
app.processEvents()
check(fv.currentIndex() == 2, f"点「下一张」→ index 2（实际 {fv.currentIndex()}）")

for _ in range(3):
    fv.scrollPrevious()
    app.processEvents()
check(fv.currentIndex() == 0, f"回到首张（实际 {fv.currentIndex()}）")
check(not viewer.prevBtn.isEnabled(), "首张禁用「上一张」")
check(viewer.nextBtn.isEnabled(), "首张「下一张」可用")

print("== pips 反向驱动 flipView ==")
viewer.pips.setCurrentIndex(2)
app.processEvents()
check(fv.currentIndex() == 2, f"点 pips → flipView 跟随（实际 {fv.currentIndex()}）")
check(viewer.countLabel.text() == "3 / 3", "反向驱动后页码正确")

print("== 内容区未铺满整个遮罩（否则点击遮罩关闭失效）==")
geo = viewer.widget.geometry()
check(
    geo.width() < viewer.width() and geo.height() < viewer.height(),
    f"widget {geo.size().toTuple()} 小于 dialog {viewer.size().toTuple()}",
)
check(not geo.contains(QPoint(4, 4)), "遮罩左上角落在内容区之外")

print("== 关闭按钮贴在图片框右上角且不出界 ==")
for w, h in ((1280, 860), (598, 520)):
    host.resize(w, h)
    viewer.resize(host.size())
    app.processEvents()
    viewer._place_close_button()
    btn = viewer.closeBtn.geometry()
    content = viewer.widget.geometry()
    check(
        viewer.rect().contains(btn),
        f"{w}x{h}：按钮 {btn.getRect()} 完全在遮罩内",
    )
    check(
        btn.left() >= content.center().x(),
        f"{w}x{h}：按钮在图片框右半边（btn.x={btn.left()} content.cx={content.center().x()}）",
    )
    check(
        btn.top() <= content.center().y(),
        f"{w}x{h}：按钮在图片框上半边（btn.y={btn.top()} content.cy={content.center().y()}）",
    )
host.resize(1280, 860)
viewer.resize(host.size())
app.processEvents()

print("== 右键重新加载 ==")
reload_url = items[fv.currentIndex()][1]
QPixmapCache.insert(reload_url, QPixmap(32, 32))  # 确保缓存里有东西可清
viewer._reload_current()
app.processEvents()
probe = QPixmap()
check(
    not QPixmapCache.find(reload_url, probe),
    "重新加载后内存缓存已作废（下次 request 会真的重下）",
)

print("== 键盘方向键 ==")
before = fv.currentIndex()
viewer.keyPressEvent(
    QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier
    )
)
app.processEvents()
check(fv.currentIndex() == before - 1, f"Left 键翻上一张（{before} → {fv.currentIndex()}）")

print("== 点击遮罩空白处关闭 ==")
closed = {"v": False}
viewer.finished.connect(lambda _: closed.__setitem__("v", True))
viewer.mousePressEvent(
    QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(4, 4),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
)
# MaskDialogBase.done 走 100ms 淡出动画，轮询等它真正结束
for _ in range(60):
    app.processEvents()
    if closed["v"]:
        break
    app.thread().msleep(10)
check(closed["v"], "点击遮罩空白处触发关闭")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
