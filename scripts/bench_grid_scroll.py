"""网格性能基准：滚动一步 / 单帧绘制 / 加载环代价 / 一格滚轮 / 窗口宽度变化。

**必须带 `QT_SCALE_FACTOR`**：本机 Windows 缩放 125%，真实绘制是 1.25 倍像素。
不加这个变量时 dpr=1.0，数字会乐观约 1.56 倍，对不上真机。

用法：
    QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py
    ... --legacy     # 同进程还原改动前的三项（环启停策略 / 滚动时长 / 缩放 memo），做 A/B

三项被还原的行为：
  1. `_CardGridBase._sync_spinners` 置空 + `set_spinner_wanted` 变 no-op
     → 视口外与隐藏页的卡片环照旧常转（改动前行为）；
  2. 网格平滑滚动时长恢复库默认 400 ms（一格滚轮 24 帧，改动后 200 ms / 12 帧）；
  3. `_SpinnerMixin._rescale` 不再 memo（每次 resize 都重做 SmoothTransformation）。

「滚动一步」用 `verticalScrollBar().setValue()` 逐档推进，每档 `processEvents()` 后计时
——这正是 `scrollContentsBy` → `_update_visible` → 整块重绘的真实路径。
`QListView` 的 IconMode 每次滚动都**整块重绘 viewport**（实测绘制区域就是整个视口，
不是暴露出来的那 60 px 条带），所以这个数字直接就是单帧上限。

对照口径见 docs/performance.md。非断言脚本，不进收尾批跑。
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA，否则会写脏真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-bench-")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPixmap, QPixmapCache, QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.components import cookie_status, page_scaffold
from app.components.content_meta import content_meta
from app.components.widgets import EmojiGrid

content_meta.set_enabled(False)  # 队列卡会为可见项懒加载内容数量
cookie_status.set_enabled(False)  # 构造页面时会碰 Cookie 检测

N = 300  # 每格网格塞多少张卡：够大才量得出「视口外也常转」的代价
WINDOW = (1080, 620)
URLS = [f"https://x.invalid/bench{i}.png" for i in range(N)]
PKGS = [
    SimpleNamespace(id=i, text=f"包{i}", emote=(), meta=None, url=URLS[i], is_gif=False)
    for i in range(N)
]

# 假图必须预置进 QPixmapCache：不预置的话每个 URL 都会排一个 15 s 超时的真网络任务
# （x.invalid 解析要等超时），脚本跑完退不出去、CPU 数字也全废。
# 尺寸要小：QPixmapCache 上限 64 MB，600×600 × 300 张 = 432 MB 会把先塞的挤掉。
_THUMB = QPixmap(128, 128)
_THUMB.fill(QColor("#3a7bd5"))
for _url in URLS:
    QPixmapCache.insert(_url, _THUMB)

LEGACY = "--legacy" in sys.argv
LEGACY_DURATION = 400  # 改动前 = 上游默认 400 ms（60 fps ⇒ 一格滚轮 24 帧）
if LEGACY:
    # 还原改动前的行为，好在同一台机器、同一个进程里做 A/B，不拿两次运行的数字对着猜。
    # 三项：环的启停策略 / 滚动帧率与时长 / 缩放 memo。
    # ⚠️ 滚动时长必须**逐个滚动区域现设**：`tune_scroll(area, duration=SCROLL_DURATION)`
    # 的默认参数在函数定义时就绑定了 200，改模块常量 `SCROLL_DURATION` 对它无效（踩过）。
    from app.common.config import cfg
    from app.components.widgets import _CardGridBase, _SpinnerMixin

    _CardGridBase._sync_spinners = lambda self, first, last: None
    _SpinnerMixin.set_spinner_wanted = lambda self, wanted: None
    _SpinnerMixin._rescale = lambda self, pm, size: pm.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    cfg.scroll_fps.value = 60  # 改动前没有这个设置项，一直是上游默认


def build(kind: str):
    grid = EmojiGrid()
    grid.resize(*WINDOW)
    grid.show()
    grid.set_emotes([(f"e{i}", URLS[i]) for i in range(N)])
    app.processEvents()
    if LEGACY:
        page_scaffold.tune_scroll(grid, LEGACY_DURATION)
    return grid


def rings_running(grid) -> int:
    return sum(
        1
        for i in range(grid.count())
        if not grid.itemWidget(grid.item(i))._spinner.isHidden()
    )


def scroll_step(grid, steps: int = 20) -> tuple[float, float]:
    """滚动一步的耗时（中位 / 最小，ms）。逐档推进、每档跑一轮事件循环。"""
    bar = grid.verticalScrollBar()
    samples = []
    for k in range(steps):
        bar.setValue(80 + k * 60)
        start = time.perf_counter()
        app.processEvents()
        samples.append((time.perf_counter() - start) * 1000)
    bar.setValue(0)
    app.processEvents()
    return statistics.median(samples), min(samples)


def idle_cpu(seconds: float) -> float:
    """空转 CPU（ms）：用来从滚轮数字里扣掉背景开销（环一直在转的那部分）。"""
    start = time.process_time()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)
    return (time.process_time() - start) * 1000


def wheel_cpu(grid, settle: float = 0.9) -> float:
    """一格滚轮扣掉背景后的净 CPU（ms）。走真实平滑滚动路径（合成 QWheelEvent）。"""
    event = QWheelEvent(
        QPointF(100, 100),
        grid.viewport().mapToGlobal(QPoint(100, 100)),
        QPoint(0, -120),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    background = idle_cpu(settle)
    start = time.process_time()
    app.sendEvent(grid.viewport(), event)
    end = time.perf_counter() + settle
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)
    return (time.process_time() - start) * 1000 - background


def resize_cost(grid) -> float:
    """窗口宽度变化一次的耗时中位（ms）：全量重排 + 每卡重缩放。"""
    grid.resize(*WINDOW)
    app.processEvents()
    samples = []
    for width in (900, 1300, 1080, 1180, 980):
        start = time.perf_counter()
        grid.resize(width, WINDOW[1])
        app.processEvents()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def frame_render(grid) -> float:
    """纯绘制单帧耗时中位（ms）：`viewport().render`，与 bench_home_paint 同一口径。"""
    buffer = QPixmap(grid.viewport().size())
    samples = []
    for index in range(25):
        start = time.perf_counter()
        grid.viewport().render(buffer)
        elapsed = (time.perf_counter() - start) * 1000
        if index >= 5:
            samples.append(elapsed)
    return statistics.median(samples)


mode = "改动前（--legacy）" if LEGACY else "当前"
print(f"{mode}｜EmojiGrid {N} 张卡，{WINDOW[0]}x{WINDOW[1]}，dpr={app.primaryScreen().devicePixelRatio()}")
print("（滚动一步 = scrollContentsBy + _update_visible + 整块 viewport 重绘）\n")

grid = build("emoji")
median, low = scroll_step(grid)
print(f"在转的加载环            {rings_running(grid):>4} / {grid.count()}")
print(f"滚动一步                中位 {median:6.2f} ms  最小 {low:6.2f} ms  → {1000/median:4.0f} fps 上限")
print(f"纯绘制单帧              {frame_render(grid):6.2f} ms  → {1000/frame_render(grid):4.0f} fps 上限")
print(f"一格滚轮净 CPU          {wheel_cpu(grid):6.0f} ms")
print(f"窗口宽度变化一次        {resize_cost(grid):6.0f} ms")

# 隐藏整个网格：改动前隐藏页里的环照样空转，改动后应归零
grid.hide()
app.processEvents()
hidden = idle_cpu(1.0)
print(f"网格隐藏后空闲 CPU      {hidden:6.0f} ms/s（= {hidden/10:.1f}% 单核）")
