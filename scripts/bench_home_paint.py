"""主页单帧重绘耗时基准（屏幕外、不联网）。

滚动流畅度的上限就是单帧重绘耗时：上游 `SmoothScroll` 把**一格滚轮摊成
`fps * duration / 1000 = 60 * 400 / 1000 = 24` 帧**（`qfluentwidgets/common/
smooth_scroll.py`），定时器 16ms 一跳。单帧只要超过 16.6ms，这 400ms 全程掉帧，
手感就是「滑不动」。所以优化主页滚动 = 把单帧重绘压下去，改动前后都跑这个脚本
对比数字——**不截图判断**（离屏渲染的观感和真机对不上）。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/bench_home_paint.py
      加 `--legacy` 跑改动前的画法（上游 `ImageLabel` + 400ms 平滑），用来做 A/B。
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
# 必须赶在 import app.* 之前隔离 APPDATA，否则会写脏真实的 config.json
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-bench-")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.components.content_meta import content_meta
from app.view import home_page as hp
from app.view.home_page import HomePage

content_meta.set_enabled(False)  # 队列卡片会为可见项懒加载内容数量

LEGACY = "--legacy" in sys.argv
if LEGACY:
    # 还原成改动前的画法：上游 ImageLabel（每帧组圆角路径 + 抗锯齿裁剪 + 缩放），
    # 好在同一台机器、同一个进程里做 A/B，而不是拿两次运行的数字对着猜。
    from qfluentwidgets import ImageLabel

    class _LegacyImageLabel(ImageLabel):
        def _postInit(self) -> None:
            self._radius = 0

        def set_radius(self, radius: int) -> None:
            self._radius = radius
            self.setBorderRadius(radius, radius, radius, radius)

        def set_flat_image(self, image, width: int, height: int) -> None:
            dpr = self.devicePixelRatioF()
            target = QSize(max(1, int(width * dpr)), max(1, int(height * dpr)))
            if not image.isNull():
                self.setImage(
                    image.scaled(
                        target,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            self.setFixedSize(width, height)

    hp._FlatImageLabel = _LegacyImageLabel

WINDOW = (1100, 820)  # 一个典型的窗口尺寸
ROUNDS = 40
WARMUP = 5


def bench(name: str, widget) -> float:
    """渲染 widget 若干次，返回单帧耗时中位数（ms）。"""
    size = widget.size()
    if size.width() <= 0 or size.height() <= 0:
        print(f"{name:26s}   —      （尺寸为 0，跳过）")
        return 0.0
    pixmap = QPixmap(size)
    samples = []
    for index in range(ROUNDS + WARMUP):
        start = time.perf_counter()
        widget.render(pixmap)
        elapsed = (time.perf_counter() - start) * 1000
        if index >= WARMUP:  # 前几帧含首次 polish / 字体缓存，不计入
            samples.append(elapsed)
    median = statistics.median(samples)
    print(
        f"{name:26s} {median:6.2f} ms   "
        f"(min {min(samples):5.2f} / max {max(samples):5.2f}) "
        f"{size.width()}x{size.height()}"
    )
    return median


page = HomePage()
page.resize(*WINDOW)
page.show()
app.processEvents()

if LEGACY:
    # 老路径也要老的滚动时长，否则 A/B 里混了两个变量
    page.scrollArea.scrollDelagate.verticalSmoothScroll.duration = 400

mode = "改动前（上游 ImageLabel + 400ms 平滑）" if LEGACY else "当前"
print(f"{mode}｜窗口 {WINDOW[0]}x{WINDOW[1]}，每项取 {ROUNDS} 帧中位数\n")
total = bench("整页 HomePage", page)
bench("英雄卡 _HeroCard", page.heroCard)
bench("功能卡 表情包", page.emojiCard)
bench("功能卡 下载", page.downloadCard)
bench("展示图带 _ShowcaseStrip", page.emojiStrip)
bench("快速上手卡", page.quickStartCard)
bench("关于卡", page.aboutCard)
bench("最近搜索卡", page.recentCard)
if page.emojiStrip.count():
    bench("单个 ImageLabel", page.emojiStrip._labels[0])

budget = 1000 / 60
smooth = page.scrollArea.scrollDelagate.verticalSmoothScroll  # 上游属性名拼错了
steps = smooth.fps * smooth.duration / 1000
print(
    f"\n一帧预算 {budget:.1f} ms（60fps）。整页 {total:.2f} ms → "
    f"{'超支，滚动必掉帧' if total > budget else '在预算内'}"
)
print(
    f"一格滚轮摊成 {steps:.0f} 帧 / {smooth.duration} ms → "
    f"单次滚动共 {total * steps:.0f} ms 的绘制"
    f"（{'装不下，会掉帧' if total * steps > smooth.duration else '装得下'}）"
)
