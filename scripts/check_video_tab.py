"""屏幕外验证收藏集详情页的「动态视频」标签页。

1. 预览卡头挂着 Pivot，两项文字带数量；
2. 切到「动态视频」→ 内容区换成左播放器 + 右选择条，条目数等于视频数；
3. 点选择条第 N 张 → 播放器当前下标跟随、该卡高亮、其余卡不高亮；
   选择条单元格尺寸与滚动条有无无关（否则会来回抖动）；
4. 无视频的收藏集：视频 tab 禁用且停在图片页；换收藏集时重置回图片页；
5. 已下载过的收藏集：本地 .mp4 被登记进 video_cache，播放零等待；
6. VideoWidget 场景背景是纯黑实心 —— 上游 CompositionMode_Difference 的回归断言，
   背景一旦不是黑的，整段视频会反色（见 app/components/video_player.py 模块注释）；
7. 600px 窄窗口不越界。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_video_tab.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 必须等 app 模块导入完成后再 setTheme（config 导入会 qconfig.load 覆盖主题）
from qfluentwidgets import Pivot, Theme, setTheme

from app.common.config import cfg
from app.components.content_meta import content_meta
from app.components.video_cache import video_cache
from app.components.video_player import VideoLightbox
from app.components.widgets import VideoCard, VideoStrip
from app.view.dress_page import DressPage

setTheme(Theme.LIGHT)
# 队列 / 视频的懒加载都要关：假 URL 会排一堆 15s 超时请求把脚本挂住
content_meta.set_enabled(False)
video_cache.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def wait_until(cond, timeout: float = 2.0) -> None:
    """轮询等待（属性动画按真实时间推进，光 processEvents 不够）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cond():
        settle(2)
        time.sleep(0.01)
    settle(2)


def preload(url: str) -> str:
    """假图预置进 QPixmapCache，thumb_manager.request 同步命中不走网络。"""
    pm = QPixmap(8, 8)
    pm.fill(QColor("#888888"))
    QPixmapCache.insert(url, pm)
    return url


class _CollItem:
    def __init__(self, i: int, with_video: bool) -> None:
        self.card_name = f"内容{i}"
        self.card_img_download = preload(f"https://x.invalid/c{i}.png")
        self.video_list = [f"https://x.invalid/v{i}.mp4"] if with_video else []


class _Collection:
    def __init__(self, images: int = 5, videos: int = 3, name: str = "测试收藏集") -> None:
        self.name = name
        self.item_list = [_CollItem(i, i < videos) for i in range(images)]


class _Summary:
    def __init__(self, name: str) -> None:
        self.name = name
        self.raw = {
            "item_id": "999",
            "properties": {
                "type": "dlc_act",
                "dlc_act_id": "1",
                "dlc_lottery_id": "2",
            },
        }
        self.image_cover = ""
        self.sale_bp_forever = 6.0


# 下载目录改到临时目录，验证「已下载过 → 直接播本地文件」；结束时还原
tmp_root = Path(tempfile.mkdtemp(prefix="biliEmojiDD-check-"))
orig_download_dir = cfg.download_dir.value
cfg.download_dir.value = str(tmp_root)

dress = DressPage()
dress.resize(1000, 760)
dress.show()
dress._detail_summary = _Summary("测试收藏集")
dress.stacked.setCurrentWidget(dress.detailPage)
dress._show_detail(_Collection(images=5, videos=3))
settle()

print("== 1. 预览卡头的 Pivot ==")
check(isinstance(dress.contentPivot, Pivot), "内容分页是组件库 Pivot")
check(
    dress.contentPivot.parent() is dress.previewCard.headerView,
    "Pivot 挂在预览卡的卡头上",
)
check(
    dress.contentPivot.widget("image").text() == "静态图片 5",
    f"图片项带数量（{dress.contentPivot.widget('image').text()!r}）",
)
check(
    dress.contentPivot.widget("video").text() == "动态视频 3",
    f"视频项带数量（{dress.contentPivot.widget('video').text()!r}）",
)
check(
    dress.contentStack.currentWidget() is dress.detailGrid,
    "默认停在静态图片页",
)

print("== 2. 切到动态视频页 ==")
dress._show_video_tab()
settle()
check(dress.contentStack.currentWidget() is dress.videoPane, "内容区换成视频页")
check(isinstance(dress.videoStrip, VideoStrip), "选择条是 VideoStrip")
check(
    dress.videoStrip.count() == 3,
    f"选择条条目数 == 视频数（实际 {dress.videoStrip.count()}）",
)
check(
    dress.videoPlayer.count() == 3,
    f"播放器拿到 3 个视频（实际 {dress.videoPlayer.count()}）",
)
check(
    dress.videoPlayer.current_index() == 0,
    f"进页自动选中第一个（实际 {dress.videoPlayer.current_index()}）",
)
check(dress.videoStrip.isWrapping(), "选择条允许折行（多栏）")
check(
    dress.videoStrip.horizontalScrollBarPolicy()
    == Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
    "选择条关掉了横向滚动条",
)
check(
    dress.videoStrip.geometry().left() >= dress.videoPlayer.geometry().right(),
    f"选择条在播放器右侧（strip.left={dress.videoStrip.geometry().left()} "
    f">= player.right={dress.videoPlayer.geometry().right()}）",
)
check(
    dress.videoStrip.width() > dress.videoPlayer.width(),
    f"选择条比播放器宽——竖屏画面用不了太多宽度"
    f"（strip={dress.videoStrip.width()} > player={dress.videoPlayer.width()}）",
)
# 拖窗口时不能有「改宽 → 重新布局 → 又一次 resize」的耦合：播放器不得在
# resizeEvent 里写死宽度约束，否则实测画面畸形 + 卡顿
check(
    dress.videoPlayer.maximumWidth() >= 16777215,
    f"播放器没有宽度上限（宽度全交给布局 stretch，实际 max="
    f"{dress.videoPlayer.maximumWidth()}）",
)
before = (dress.videoPlayer.width(), dress.videoStrip.width())
for size in ((1400, 900), (820, 600), (1000, 760)):
    dress.resize(*size)
    settle(8)
check(
    (dress.videoPlayer.width(), dress.videoStrip.width()) == before,
    f"来回缩放后宽度回到原值（{before} -> "
    f"{(dress.videoPlayer.width(), dress.videoStrip.width())}）",
)
check(dress.videoStrip.columns() >= 2, f"选择条至少两栏（{dress.videoStrip.columns()}）")


def row_tops() -> list[int]:
    strip = dress.videoStrip
    return [strip.visualItemRect(strip.item(i)).y() for i in range(strip.count())]


check(
    len(row_tops()) >= 2 and row_tops()[0] == row_tops()[1],
    f"前两张卡在同一行（实际 y={row_tops()}）",
)


def active_flags() -> list[bool]:
    strip = dress.videoStrip
    return [strip.itemWidget(strip.item(i)).is_active() for i in range(strip.count())]


check(active_flags() == [True, False, False], f"首张高亮（{active_flags()}）")

print("== 2b. 播放控制条在画面下方，不盖住内容 ==")
player, bar = dress.videoPlayer, dress.videoPlayer.playBar
check(bar.parent() is player, "控制条已从 VideoWidget 里挪到播放器容器上")
check(
    bar.geometry().top() >= player.view.geometry().bottom(),
    f"控制条在画面下方（bar.top={bar.geometry().top()} "
    f">= view.bottom={player.view.geometry().bottom()}）",
)
check(
    not player.view.geometry().intersects(bar.geometry()),
    "控制条与画面区不重叠",
)
check(
    player.view.playBar is bar and player.view.player is bar.player,
    "VideoWidget 的 play/pause 仍然接在同一个控制条上",
)
# 播放/暂停图标必须跟着真实播放状态走：上游只在 mediaStatusChanged 时刷，
# 于是被 hideEvent 暂停（切页 / 全屏搬家）之后按钮还停在暂停图标上
try:
    player.view.player.playbackStateChanged.disconnect(player._sync_play_button)
    connected = True
    player.view.player.playbackStateChanged.connect(player._sync_play_button)
except (RuntimeError, TypeError):
    connected = False
check(connected, "playbackStateChanged 已接到 _sync_play_button（暂停后图标会复位）")
bar.playButton.setPlay(True)  # 伪造「按钮停在暂停图标」的状态
player._sync_play_button()
check(
    bar.playButton.toolTip() != "Pause",
    f"同步后按钮回到「播放」（tooltip={bar.playButton.toolTip()!r}）",
)

print("== 2c. 控制条：上一个 / 下一个 / 全屏 ==")
check(
    player.prevBtn is bar.skipBackButton and player.nextBtn is bar.skipForwardButton,
    "上一个/下一个复用了上游的两个 skip 按钮",
)
check(
    player.fullscreenBtn.parent() is bar.rightButtonContainer,
    "全屏按钮挂在控制条右侧容器上",
)
check(not player.prevBtn.isEnabled(), "当前是第 1 个：「上一个」禁用")
check(player.nextBtn.isEnabled(), "还有后续：「下一个」可用")
player.play_next()
settle()
check(player.current_index() == 1, f"下一个 → 索引 1（实际 {player.current_index()}）")
check(player.prevBtn.isEnabled(), "非首个：「上一个」恢复可用")
player.play_next()
settle()
check(player.current_index() == 2, "再下一个 → 索引 2")
check(not player.nextBtn.isEnabled(), "已是最后一个：「下一个」禁用")
player.play_next()  # 越界：应当什么都不做且不报错
settle()
check(player.current_index() == 2, "在最后一个上点「下一个」不越界、不报错")
player.play(0)
settle()
player.play_prev()  # 越界：应当什么都不做且不报错
settle()
check(player.current_index() == 0, "在第 1 个上点「上一个」不越界、不报错")
player.set_videos([])
check(
    not player.fullscreenBtn.isEnabled()
    and not player.prevBtn.isEnabled()
    and not player.nextBtn.isEnabled(),
    "空列表：三个按钮全禁用",
)
dress._show_detail(_Collection(images=5, videos=3))
dress._show_video_tab()
settle()
player.play(2)
settle()

print("== 2d. 全屏遮罩：搬进去再搬回来 ==")
home = dress.videoPane.layout()
box = VideoLightbox(player, dress.window())
box.show()
settle()
check(player.parent() is box.widget, "播放器被搬进了遮罩容器")
check(
    box.graphicsEffect() is None,
    "跳过了上游的淡入特效（QGraphicsOpacityEffect 叠在刷帧的视频上会卡）",
)
check(home.indexOf(player) == -1, "已从视频页布局里移出")
check(player.current_index() == 2, "全屏不影响当前播放的下标")
check(
    box.widget.height() > dress.videoPane.height(),
    f"全屏容器比内嵌区域高（{box.widget.height()} > {dress.videoPane.height()}）",
)
box.reject()
# 淡入淡出已被跳过（特效叠在刷帧的视频上会卡），但 finished 仍是排队投递的
wait_until(lambda: home.indexOf(player) == 0)
check(home.indexOf(player) == 0, f"关闭后搬回原位置（下标 {home.indexOf(player)}）")
check(player.parent() is dress.videoPane, "父控件回到视频页")
check(
    dress.videoStrip.geometry().left() >= player.geometry().right(),
    "左右版式复原：选择条仍在播放器右侧",
)

print("== 3. 点选择条切换视频 ==")
dress.videoStrip.videoClicked.emit(2)
settle()
check(
    dress.videoPlayer.current_index() == 2,
    f"播放器切到第 3 个（实际 {dress.videoPlayer.current_index()}）",
)
check(active_flags() == [False, False, True], f"高亮跟随切换（{active_flags()}）")
card = dress.videoStrip.itemWidget(dress.videoStrip.item(2))
check(isinstance(card, VideoCard), "选择条卡片是 VideoCard")
check(not card.playBadge.isHidden(), "卡片有播放角标")
check(
    "VideoCard" in card.styleSheet(),
    "高亮样式表用类选择器限定自身（不级联到子 label）",
)
check(
    dress.contentPivot.currentItem() is dress.contentPivot.widget("video"),
    "Pivot 指示条跟着切到动态视频（程序化调用也同步）",
)

print("== 3b. 离开视频页再回来 ==")
dress._show_image_tab()
settle()
check(dress.contentStack.currentWidget() is dress.detailGrid, "切回图片页")
check(
    dress.contentPivot.currentItem() is dress.contentPivot.widget("image"),
    "Pivot 指示条同步回静态图片",
)
check(dress.videoPlayer.is_idle(), "离开视频页即停播（source 已释放）")
dress._show_video_tab()
settle()
check(
    dress.videoPlayer.current_index() == 2,
    f"回到视频页续播上次选中的那个（实际 {dress.videoPlayer.current_index()}）",
)
check(active_flags() == [False, False, True], f"高亮仍在第 3 张（{active_flags()}）")

print("== 3c. 单元格尺寸与滚动条有无无关（防来回抖动）==")
dress._show_detail(_Collection(images=10, videos=10))
dress._show_video_tab()
settle()
strip = dress.videoStrip
check(strip.verticalScrollBar().maximum() > 0, "10 个视频时确实出现了竖向滚动条")
# 同一批视频、只切换滚动条有无：单元格必须一模一样，否则会「变窄→变矮→不需要
# 滚动条→变宽」来回抖
strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
settle()
with_bar = strip._cell_size()
strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
settle()
without_bar = strip._cell_size()
strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
settle()
check(
    with_bar == without_bar,
    f"有无滚动条时单元格一致（{with_bar.width()}x{with_bar.height()} == "
    f"{without_bar.width()}x{without_bar.height()}）——按控件宽度而非 viewport 宽度算",
)
dress._show_detail(_Collection(images=2, videos=1))
dress._show_video_tab()
settle()
check(
    strip.columns() == 1 and strip._cell_size().height() <= strip.viewport().height(),
    f"只有 1 个视频时收敛成单栏且不高过视口"
    f"（{strip.columns()} 栏，{strip._cell_size().height()} <= {strip.viewport().height()}）",
)

print("== 4. 无视频 / 换收藏集的重置 ==")
dress._show_detail(_Collection(images=4, videos=0, name="无视频收藏集"))
settle()
check(
    not dress.contentPivot.widget("video").isEnabled(), "无视频：动态视频 tab 被禁用"
)
check(
    dress.contentStack.currentWidget() is dress.detailGrid, "无视频：强制回到图片页"
)
check(dress.videoStrip.count() == 0, "无视频：选择条清空")
check(
    dress.videoPlayer.current_index() == -1,
    f"无视频：播放器下标重置（实际 {dress.videoPlayer.current_index()}）",
)
dress._show_detail(_Collection(images=5, videos=2))
settle()
check(dress.contentPivot.widget("video").isEnabled(), "有视频：tab 恢复可用")
check(
    dress.contentStack.currentWidget() is dress.detailGrid,
    "换收藏集后回到图片页（不继承上一个的视频页状态）",
)

print("== 5. 已下载过的收藏集直接播本地文件 ==")
folder = tmp_root / "测试收藏集"
folder.mkdir(parents=True, exist_ok=True)
(folder / "内容0.mp4").write_bytes(b"\x00" * 16)
(folder / "内容1.mp4").write_bytes(b"\x00" * 16)
dress._detail_summary = _Summary("测试收藏集")
dress._show_detail(_Collection(images=5, videos=2))
settle()
v0 = dress._detail_videos[0][1]
check(
    video_cache.local_path(v0) == str(folder / "内容0.mp4"),
    f"本地 .mp4 被登记进缓存（{video_cache.local_path(v0)!r}）",
)
dress._show_video_tab()
settle()
check(
    dress.videoPlayer.spinner.isHidden(),
    "命中本地文件时不转加载环（直接播）",
)

print("== 6. VideoWidget 背景是纯黑（防上游 Difference 反色）==")
for theme in (Theme.LIGHT, Theme.DARK):
    setTheme(theme)
    settle()
    brush = dress.videoPlayer.view.backgroundBrush()
    check(
        brush.style() == Qt.BrushStyle.SolidPattern
        and brush.color().getRgb()[:3] == (0, 0, 0),
        f"{theme}：场景背景是纯黑实心（style={brush.style()}, "
        f"color={brush.color().getRgb()[:3]}）",
    )
setTheme(Theme.LIGHT)
settle()

print("== 7. 窄窗口不越界 ==")
dress._show_video_tab()
settle()
dress.resize(600, 700)
settle(8)
check(dress.width() == 600, f"页面确实缩到 600（实际 {dress.width()}）")
check(
    0 < dress.videoStrip.geometry().right() <= dress.videoPane.width(),
    f"选择条不越界（{dress.videoStrip.geometry().right()} <= {dress.videoPane.width()}）",
)
check(
    dress.videoStrip.columns() >= 2,
    f"窄窗口下仍是两栏以上（{dress.videoStrip.columns()}）",
)
check(
    dress.videoPlayer.height() > 0 and dress.videoStrip.height() > 0,
    f"播放器与选择条都有高度（{dress.videoPlayer.height()} / {dress.videoStrip.height()}）",
)

dress.videoPlayer.release()
dress.close()
cfg.download_dir.value = orig_download_dir
shutil.rmtree(tmp_root, ignore_errors=True)  # 脚本自己 mkdtemp 出来的目录
video_cache.cleanup()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
