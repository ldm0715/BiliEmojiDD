"""真机帧率测量（**需要真实窗口，由用户自己跑**）。

离屏脚本（`bench_grid_scroll.py` / `bench_home_paint.py`）只能做相对的 A/B，
量不出 DWM 合成、vblank 与真实调度下的绝对帧率。这个脚本补的就是这一段。

用法（项目根目录，**不要带 `QT_QPA_PLATFORM`**，要真窗口）：

    uv run python scripts/bench_app_fps.py --mode idle   --seconds 5
    uv run python scripts/bench_app_fps.py --mode scroll --page emoji --seconds 8
    uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300
    uv run python scripts/bench_app_fps.py --mode switch --seconds 8
    uv run python scripts/bench_app_fps.py --mode resize --seconds 8

参数：
  --mode     idle | scroll | switch | resize          （默认 scroll）
  --page     home | emoji | dress | download | setting（默认 emoji）
  --seconds  测量时长                                  （默认 8）
  --rate     交互间隔秒数（默认 0.2 = 每秒 5 次，接近真人连续滚动）。
             调得越小越容易把 Qt 平滑滚动的步进队列喂爆（上游 `SmoothScroll`
             按队列里每条事件各自插值，喂得比消费快就会堆起来），
             那种长批次是脚本造的，真人不会遇到。
  --fake N   往当前页的网格里塞 N 张假卡片（URL 预先塞进 QPixmapCache，
             不联网、不依赖 Cookie，便于复现与改动前后对比）
  --thumb-delay MS
             缩略图延迟 MS 毫秒才交付（默认 0 = 立即命中）。设成 ~800 就稳定复现
             「等图窗口期」—— 加载环转起来、滚动被拖慢，**那才是本轮优化真正见效的
             场景**。稳态（图都加载完）本来就贴着上游写死的 60 fps 上限，量不出差别。
  --legacy   还原改动前的三项行为，在真机上直接 A/B（配合 --thumb-delay 看差异）
  --warmup   计时前的预热秒数（默认 1）。启动后的静默预拉取（Cookie 检测 / 读
             all_packages.json / 查更新）都在前几秒，**建议 ≥2 s**；配 `--fake 300`
             时建议 **≥5 s**（注入 300 张卡本身要好几秒，量完不留够预热会把
             注入的尾巴算进测量窗口）。
  --no-net   关掉联网开关（内容数量 / 视频缓存 / 更新检查 / 登录 / Cookie 直播）

Qt 没有现成的帧计数，这里**覆写 `QApplication.notify`** 给每个 `Paint` 事件计时：

* 一帧 = 一次事件循环拍里连续交付的一组 Paint（相邻两次 Paint 间隔 > 2 ms 视为下一帧）；
* 帧率 = 帧数 / 时长，同时给出帧间隔中位数反推的「实到帧率」；
* 单帧重绘耗时 = 该帧内所有 Paint 耗时之和 —— **这才是能和离屏基准对标的指标**，
  p99 决定主观卡不卡。

按项目规矩：先隔离 `APPDATA` 再 import `app.*`（否则写脏真实 config / 历史 / 缓存）。
"""
from __future__ import annotations

import argparse
import os
import statistics as st
import sys
import tempfile
import time
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-fps-")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap, QPixmapCache, QWheelEvent

# 相邻两次 Paint 间隔超过这个值（秒）就当成新的一帧：同一帧的 Paint 是背靠背交付的
_FRAME_GAP = 0.002

RECORDS: list[tuple[float, float, str]] = []  # (Paint 起始挂钟, 耗时 ms, 接收者类名)
# 只有测量窗口内的 Paint 才计入：预热期的 polish / 首帧会污染分布
MEASURING: list[dict] = []


def build_app():
    """QApplication 子类：覆写 `notify` 给 Paint 计时。必须在 import app.* 之前建。"""
    from PySide6.QtWidgets import QApplication

    class TimedApplication(QApplication):
        def notify(self, receiver, event):
            if event.type() == QEvent.Type.Paint and MEASURING and MEASURING[0]["measuring"]:
                started = time.perf_counter()
                try:
                    return super().notify(receiver, event)
                finally:
                    RECORDS.append(
                        (started, (time.perf_counter() - started) * 1000,
                         type(receiver).__name__)
                    )
            return super().notify(receiver, event)

    return TimedApplication(sys.argv)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真机帧率测量")
    parser.add_argument("--mode", default="scroll",
                        choices=["idle", "scroll", "switch", "resize"])
    parser.add_argument("--page", default="emoji",
                        choices=["home", "emoji", "dress", "download", "setting"])
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--rate", type=float, default=0.2,
                        help="交互间隔秒数（默认 0.2 = 每秒 5 次）。调大更接近真人操作")
    parser.add_argument("--fake", type=int, default=0)
    parser.add_argument("--thumb-delay", type=int, default=0, metavar="MS",
                        help="缩略图延迟交付的毫秒数（默认 0 = 立即命中缓存）。"
                             "设成 800 左右就能稳定复现「等图窗口期」——"
                             "那正是加载环拖慢滚动的场景，也是本轮优化真正见效的地方")
    parser.add_argument("--legacy", action="store_true",
                        help="还原改动前的三项行为（环启停策略 / 滚动时长 / 缩放 memo），"
                             "用来在真机上直接 A/B")
    parser.add_argument("--warmup", type=float, default=1.0)
    parser.add_argument("--scroll-fps", type=int, default=0, choices=[0, 60, 120],
                        help="本次测量用哪档滚动帧率（0 = 用配置里的，默认 60）。"
                             "在构造 MainWindow 之前写进 cfg，所以所有滚动区域都按它走")
    parser.add_argument("--no-net", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 与 main.py 同一套启动顺序：字体渲染后端是平台插件的启动参数，必须在 QApplication 之前
    from app.common.font import apply_font_engine

    apply_font_engine()

    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = build_app()

    from qfluentwidgets import setTheme

    from app.common.config import cfg
    from app.common.font import apply_app_font

    apply_app_font(app)
    setTheme(cfg.theme.value)
    if args.scroll_fps:
        # 必须在 MainWindow 构造之前：页面 / 网格在构造时就 tune_scroll，读的就是这个值
        cfg.scroll_fps.value = args.scroll_fps

    # 联网开关必须赶在 MainWindow 构造之前关掉，否则构造期就会排任务出去
    from app.components import cookie_status, updater
    from app.components.content_meta import content_meta
    from app.components.video_cache import video_cache

    if args.no_net:
        from app.components import bili_login, live_emoji

        for module in (content_meta, video_cache, updater, cookie_status, live_emoji, bili_login):
            module.set_enabled(False)

    from app.common.config import cfg as _cfg
    from app.MainWindow import MainWindow

    window = MainWindow()
    window.resize(1100, 760)
    window.show()

    pages = {
        "home": window.homePage,
        "emoji": window.emojiPage,
        "dress": window.dressPage,
        "download": window.downloadPage,
        "setting": window.settingPage,
    }
    window.switchTo(pages[args.page])
    pump(app, 0.6)

    grid = largest_grid(pages[args.page])
    # `--legacy` 必须在注入卡片之前生效：卡片构造时就会 start() 环，网格的差集同步
    # 一旦在注入期间跑过，视口外的环已经被关掉，之后再置空 `_sync_spinners` 也救不回来
    if args.legacy:
        enable_legacy()
    if args.fake and grid is not None:
        inject_fake(grid, args.fake, app, args.thumb_delay)
    print(
        f"页面 {args.page}｜网格 {type(grid).__name__ if grid else '无'}"
        f"｜卡片 {grid.count() if grid else 0}｜在转的加载环 {count_rings(grid)}"
        f"｜dpr {app.primaryScreen().devicePixelRatio()}"
        f"｜屏幕 {app.primaryScreen().refreshRate():.0f} Hz"
        f"｜滚动帧率 {_cfg.scroll_fps.value}"
    )
    if grid is None or grid.count() == 0:
        print("提示：这个页面没有卡片，帧率数字会失真 —— 加 --fake 300 再测一次。")

    drive = make_driver(args, app, window, grid)

    # **用真事件循环驱动，不要手写 `processEvents` + `sleep` 循环**：Windows 上
    # `time.sleep(0.002)` 实测会被系统休眠粒度放大到 ~15.6 ms，那个循环每秒只转
    # 60 来次，于是「可测帧率」被脚本自己卡在 ~64 fps —— 120 帧那档根本量不出来（踩过）。
    tick = QTimer()
    tick.setInterval(max(1, int(args.rate * 1000)))
    tick.timeout.connect(lambda: drive and drive(0.0))
    state = {"measuring": False}

    def begin() -> None:
        RECORDS.clear()
        state["measuring"] = True
        state["started"] = time.perf_counter()
        tick.start()
        QTimer.singleShot(int(args.seconds * 1000), finish)

    def finish() -> None:
        state["measuring"] = False
        tick.stop()
        app.quit()

    MEASURING.append(state)
    QTimer.singleShot(int(args.warmup * 1000), begin)
    app.exec()
    report(args.seconds)
    return 0


def pump(app, seconds: float) -> None:
    """只在**测量之外**的装配阶段用（切页后让界面落定）。

    测量窗口内**不能**用它：`time.sleep(0.002)` 在 Windows 上会被系统休眠粒度放大到
    ~15.6 ms，循环每秒只转 60 来次，会把可测帧率卡在 ~64 fps（踩过）。
    测量走 `app.exec()` + `QTimer`。
    """
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


def largest_grid(page):
    """页面上可见的、卡片最多的网格（有的页有好几个）。"""
    from app.components.widgets import _CardGridBase

    grids = [g for g in page.findChildren(_CardGridBase) if g.isVisible()]
    return max(grids, key=lambda g: g.count(), default=None)


def count_rings(grid) -> int:
    if grid is None:
        return 0
    return sum(
        1 for i in range(grid.count())
        if not grid.itemWidget(grid.item(i))._spinner.isHidden()
    )


def inject_fake(grid, count: int, app, thumb_delay_ms: int = 0) -> None:
    """塞假卡片。

    `thumb_delay_ms == 0`：URL 预置进 `QPixmapCache`，缩略图同步命中，全程不联网。
    大于 0：**不预置**，改成用一个定时器延迟交付 —— 这样卡片会真的进入「等图」
    状态、加载环转起来，正是复现「等图窗口期」的方式（延迟按 URL 的哈希抖动，
    避免所有环同时起停）。全程仍然不碰网络。
    """
    from app.components import thumb
    from app.components.widgets import EmojiGrid, PackageGrid

    urls = [f"https://x.invalid/fps{i}.png" for i in range(count)]
    thumb_pixmap = QPixmap(128, 128)
    thumb_pixmap.fill(QColor("#3a7bd5"))
    if thumb_delay_ms:
        _delay_thumbs(thumb, urls, thumb_pixmap, thumb_delay_ms)
    else:
        for url in urls:
            QPixmapCache.insert(url, thumb_pixmap)
    if isinstance(grid, PackageGrid):
        grid.set_packages([
            SimpleNamespace(id=i, text=f"包{i}", emote=(), meta=None,
                            url=urls[i], is_gif=False)
            for i in range(count)
        ])
    elif isinstance(grid, EmojiGrid):
        grid.set_emotes([(f"e{i}", urls[i]) for i in range(count)])
    else:
        print("提示：这个网格不吃假数据（自己建卡 / 走队列数据），跳过注入")
    app.processEvents()


def _delay_thumbs(thumb_module, urls, pixmap, delay_ms: int) -> None:
    """把 `thumb_manager.request` 换成一个「延迟 N 毫秒后交付假图」的实现。

    只替换这一个入口：`_update_visible` 请求缩略图时不再同步命中，卡片进入等图态。
    延迟按 URL 散列在 [0.6, 1.4] × delay_ms 之间抖动，更像真实网络。
    """
    from app.common.signal_bus import signal_bus

    def request(url):
        if not url or url not in _FAKE_DELAY:
            return
        jitter = 0.6 + (_FAKE_DELAY[url] % 9) / 10  # 0.6 ~ 1.4
        QTimer.singleShot(
            int(delay_ms * jitter),
            lambda u=url: signal_bus.thumbLoaded.emit(u, pixmap),
        )

    _FAKE_DELAY.update({url: index for index, url in enumerate(urls)})
    thumb_module.thumb_manager.request = request


def enable_legacy() -> None:
    """还原改动前的三项行为，用于在真机上直接 A/B。

    ⚠️ 滚动时长**必须逐个滚动区域现设**：`tune_scroll(area, duration=SCROLL_DURATION)`
    的默认参数在函数定义时就绑定了 200，改模块常量 `SCROLL_DURATION` 对它无效
    （踩过：改成 400 其实什么都没发生）。
    """
    from app.common.config import cfg
    from app.components import page_scaffold
    from app.components.widgets import _CardGridBase, _SpinnerMixin

    _CardGridBase._sync_spinners = lambda self, first, last: None
    _SpinnerMixin.set_spinner_wanted = lambda self, wanted: None
    _SpinnerMixin._rescale = lambda self, pm, size: pm.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    # 改动前没有「滚动帧率」这个设置项，一直是上游默认的 60 fps + 库默认 400 ms
    cfg.scroll_fps.value = 60
    restored = 0
    for widget in page_scaffold.iter_scroll_areas():
        page_scaffold.tune_scroll(widget, 400)
        restored += 1
    print(f"已切到 --legacy：视口外的加载环照转、滚动 {restored} 个区域回到 400 ms、缩放不 memo")


_FAKE_DELAY: dict[str, int] = {}


def make_driver(args, app, window, grid):
    """返回「推进一次交互」的闭包；idle 或没有网格时返回 None。"""
    if args.mode == "idle" or grid is None:
        return None

    if args.mode == "scroll":
        state = [0]

        def scroll(_elapsed: float) -> None:
            state[0] += 1
            delta = -120 if (state[0] // 12) % 2 == 0 else 120  # 来回滚，别撞到底
            app.sendEvent(grid.viewport(), QWheelEvent(
                QPointF(100, 100),
                grid.viewport().mapToGlobal(QPoint(100, 100)),
                QPoint(0, delta), QPoint(0, delta),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            ))

        return scroll

    if args.mode == "switch":
        order = [window.homePage, window.emojiPage, window.dressPage,
                 window.downloadPage, window.settingPage]
        state = [0]

        def switch(_elapsed: float) -> None:
            state[0] = (state[0] + 1) % len(order)
            window.switchTo(order[state[0]])

        return switch

    widths = [1100, 980, 1180, 900, 1120]
    state = [0]

    def resize(_elapsed: float) -> None:
        state[0] = (state[0] + 1) % len(widths)
        window.resize(widths[state[0]], 760)

    return resize


def group_frames(records) -> tuple[list[float], list[float]]:
    """按相邻 Paint 的间隔分组：返回（每帧重绘耗时 ms, 每帧起始挂钟）。"""
    durations: list[float] = []
    starts: list[float] = []
    last_at = None
    for started, cost, _name in records:
        if last_at is None or started - last_at > _FRAME_GAP:
            durations.append(cost)
            starts.append(started)
        else:
            durations[-1] += cost
        last_at = started
    return durations, starts


def report(seconds: float) -> None:
    if len(RECORDS) < 2:
        print("没收集到重绘事件：确认窗口在前台、别被遮住，或加大 --seconds。")
        return
    durations, starts = group_frames(RECORDS)
    intervals = [(b - a) * 1000 for a, b in pairwise(starts)]
    span = starts[-1] - starts[0]
    frames = len(durations)

    def pct(values, q):
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(len(ordered) * q))]

    print(f"\n测量 {seconds:.1f} s｜重绘 {len(RECORDS)} 次｜成帧 {frames} 个")
    # 「绘制占用」= 测量窗口内所有 Paint 耗时之和 / 时长。这是能直接和「一帧预算」比
    # 的数，也不依赖测量方式（比手写 processEvents 循环时的「事件循环占用」可靠）
    print(f"绘制占用          {sum(durations) / 1000:6.2f} s / {seconds:.1f} s"
          f"（= {sum(durations) / 10 / seconds:5.1f}% 单核）")
    if span > 0:
        print(f"实到帧率          {frames / span:6.1f} fps"
              f"（{frames} 帧 / {span:.2f} s，只算有重绘的时段）")
    if intervals:
        print(f"帧间隔            中位 {st.median(intervals):6.2f} ms"
              f"  p90 {pct(intervals, 0.9):6.2f} ms  p99 {pct(intervals, 0.99):6.2f} ms")
        print(f"反推帧率          中位 {1000 / st.median(intervals):6.1f} fps")
    print(f"单帧重绘耗时      中位 {st.median(durations):6.2f} ms"
          f"  p90 {pct(durations, 0.9):6.2f} ms  p99 {pct(durations, 0.99):6.2f} ms")
    print(f"单帧重绘上限      {1000 / st.median(durations):6.1f} fps"
          "（只算绘制，不合成的理论上限）")

    # 最长的几次停顿单独列出来：一次性的大数字往往是「某个同步操作撞进来了」，
    # 比 p99 更有指向性（p99 会被一次 GC / 一次磁盘读吃掉）
    worst = sorted(range(len(intervals)), key=lambda i: -intervals[i])[:3]
    if worst and intervals[worst[0]] > 100:
        print("最长停顿：")
        for i in worst:
            print(f"           {intervals[i]:7.0f} ms  出现在第 {starts[i] - starts[0]:5.1f} s")

    # 谁在重绘：idle 下本该 0 次，有的话这里直接点名
    by_widget: dict[str, int] = {}
    for _started, _cost, name in RECORDS:
        by_widget[name] = by_widget.get(name, 0) + 1
    top = sorted(by_widget.items(), key=lambda kv: -kv[1])[:6]
    print("重绘来源（谁在画）：")
    for name, count in top:
        print(f"           {name:<28} {count:>6} 次")
    print("\n对表：离屏基准里同一网格的「滚动一步 / 纯绘制单帧」见"
          " QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py")


if __name__ == "__main__":
    sys.exit(main())
